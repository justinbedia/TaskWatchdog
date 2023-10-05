from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from datetime import timedelta as td

from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.core.paginator import Paginator
from django.db.models import F, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django_stubs_ext import WithAnnotations

from hc.api.models import Channel, Check, Flip, Notification, Ping
from hc.lib.date import format_duration

Lookups = Iterable[tuple[str, str]]


@admin.register(Check)
class ChecksAdmin(ModelAdmin[Check]):
    class Media:
        css = {"all": ("css/admin/checks.css",)}

    search_fields = ["name", "code", "project__owner__email"]
    readonly_fields = ("code",)
    raw_id_fields = ("project",)
    list_select_related = ("project",)
    list_display = (
        "id",
        "name_tags",
        "project_",
        "created",
        "n_pings",
        "timeout_schedule",
        "status",
        "last_start",
        "last_ping",
    )
    list_filter = ("status", "kind", "last_ping", "last_start")

    actions = ["send_alert"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Check]:
        qs = super().get_queryset(request)
        qs = qs.annotate(email=F("project__owner__email"))
        return qs

    @mark_safe
    def project_(self, obj: Check) -> str:
        url = obj.project.checks_url(full=False)
        name = escape(obj.project.name or "Default")
        email = escape(obj.email)
        return f'{email} &rsaquo; <a href="{url}"">{name}</a>'

    @mark_safe
    def name_tags(self, obj: Check) -> str:
        url = obj.details_url(full=False)
        name = escape(obj.name or "unnamed")

        s = f'<a href="{url}"">{name}</a>'
        for tag in obj.tags_list():
            s += " <span>%s</span>" % escape(tag)

        return s

    @admin.display(description="Schedule")
    def timeout_schedule(self, obj: Check) -> str:
        if obj.kind == "simple":
            return format_duration(obj.timeout)
        elif obj.kind == "cron":
            return obj.schedule
        else:
            return "Unknown"

    @admin.action(description="Send Alert")
    def send_alert(self, request: HttpRequest, qs: QuerySet[Check]) -> None:
        for check in qs:
            for channel in check.channel_set.all():
                channel.notify(check)

        self.message_user(request, "%d alert(s) sent" % qs.count())


class SchemeListFilter(admin.SimpleListFilter):
    title = "Scheme"
    parameter_name = "scheme"

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin[Check]) -> Lookups:
        return (("http", "HTTP"), ("https", "HTTPS"), ("email", "Email"))

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[Check]
    ) -> QuerySet[Check]:
        if self.value():
            queryset = queryset.filter(scheme=self.value())
        return queryset


class MethodListFilter(admin.SimpleListFilter):
    title = "Method"
    parameter_name = "method"
    methods = ["HEAD", "GET", "POST", "PUT", "DELETE"]

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin[Ping]) -> Lookups:
        return zip(self.methods, self.methods)

    def queryset(self, request: HttpRequest, qs: QuerySet[Ping]) -> QuerySet[Ping]:
        if self.value():
            qs = qs.filter(method=self.value())
        return qs


class KindListFilter(admin.SimpleListFilter):
    title = "Kind"
    parameter_name = "kind"
    kinds = ["start", "fail"]

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin[Ping]) -> Lookups:
        return zip(self.kinds, self.kinds)

    def queryset(self, request: HttpRequest, qs: QuerySet[Ping]) -> QuerySet[Ping]:
        if self.value():
            qs = qs.filter(kind=self.value())
        return qs


class PingsPaginator(Paginator[Ping]):
    count = 1000
    page_range = range(1, 10)


@admin.register(Ping)
class PingsAdmin(ModelAdmin[Ping]):
    readonly_fields = ("owner", "has_body")
    list_select_related = ("owner",)
    list_display = ("id", "created", "owner", "scheme", "method", "object_size", "ua")
    list_filter = ("created", SchemeListFilter, MethodListFilter, KindListFilter)
    exclude = ("body",)

    paginator = PingsPaginator
    show_full_result_count = False


class LastNotifyDurationFilter(admin.SimpleListFilter):
    title = "last notify duration"

    parameter_name = "last_notify_duration"

    def lookups(self, r: HttpRequest, model_admin: ModelAdmin[Channel]) -> Lookups:
        return (
            ("1", "More than 1s"),
            ("6", "More than 6s"),
            ("10", "More than 10s"),
        )

    def queryset(self, r: HttpRequest, qs: QuerySet[Channel]) -> QuerySet[Channel]:
        v = self.value()
        if v:
            seconds = float(v)
            qs = qs.filter(last_notify_duration__gt=td(seconds=seconds))

        return qs


@admin.register(Channel)
class ChannelsAdmin(ModelAdmin[Channel]):
    class Media:
        css = {"all": ("css/admin/channels.css",)}

    search_fields = ["value", "project__owner__email", "name", "code"]
    readonly_fields = ("code",)
    list_display = (
        "id",
        "transport",
        "name",
        "project_",
        "created_",
        "chopped_value",
        "last",
        "status",
        "time",
    )
    list_filter = ("kind", LastNotifyDurationFilter, "disabled")
    raw_id_fields = ("project", "checks")

    def created_(self, obj: Channel) -> date:
        return obj.created.date()

    @mark_safe
    def project_(self, obj: WithAnnotations[Channel]) -> str:
        url = self.view_on_site(obj)
        name = escape(obj.project_name or "Default")
        email = escape(obj.owner_email)
        return f"{email} &rsaquo; <a href='{url}'>{name}</a>"

    def time(self, obj: Channel) -> str | None:
        if obj.last_notify_duration:
            return "%.1f" % obj.last_notify_duration.total_seconds()
        return None

    def get_queryset(self, request: HttpRequest) -> QuerySet[Channel]:
        qs = super().get_queryset(request)
        qs = qs.annotate(project_code=F("project__code"))
        qs = qs.annotate(project_name=F("project__name"))
        qs = qs.annotate(owner_email=F("project__owner__email"))
        return qs

    def view_on_site(self, obj: WithAnnotations[Channel]) -> str:
        return reverse("hc-channels", args=[obj.project_code])

    @mark_safe
    def transport(self, obj: Channel) -> str:
        note = ""
        if obj.kind == "email" and not obj.email_verified:
            note = " (not verified)"

        return f'<span class="ic-{ obj.kind }"></span> &nbsp; {obj.kind}{note}'

    @admin.display(description="Value")
    def chopped_value(self, obj: Channel) -> str:
        if len(obj.value) > 100:
            return "%s…" % obj.value[:100]

        return obj.value

    def last(self, obj: Channel) -> date | None:
        return obj.last_notify.date() if obj.last_notify else None

    @mark_safe
    def status(self, obj: Channel) -> str:
        if obj.disabled:
            return "<span class='d'>Disabled</span>"
        if obj.last_error:
            return "<span class='e'>Error</span>"
        if obj.last_notify:
            return "OK"
        return "-"


@admin.register(Notification)
class NotificationsAdmin(ModelAdmin[Notification]):
    class Media:
        css = {"all": ("css/admin/notifications.css",)}

    search_fields = ["owner__name", "owner__code", "channel__value", "error", "code"]
    readonly_fields = ("owner", "code")
    list_select_related = ("channel", "channel__project", "channel__project__owner")
    list_display = (
        "id",
        "created",
        "channel_kind",
        "check_status",
        "project",
        "channel_value",
        "error",
    )
    list_filter = ("created", "check_status", "channel__kind")
    raw_id_fields = ("channel",)

    def channel_kind(self, obj: Notification) -> str:
        return obj.channel.kind

    @mark_safe
    def channel_value(self, obj: Notification) -> str:
        return "<div>%s</div>" % escape(obj.channel.value)

    @mark_safe
    def project(self, obj: Notification) -> str:
        url = reverse("hc-channels", args=[obj.channel.project.code])
        name = escape(obj.channel.project)
        return f"<div><a href='{url}'>{name}</a></div>"


@admin.register(Flip)
class FlipsAdmin(ModelAdmin[Flip]):
    list_display = ("id", "created", "processed", "owner", "old_status", "new_status")
    raw_id_fields = ("owner",)
