# Generated by Django 4.0.6 on 2022-07-12 10:02

from django.db import migrations
from django.db.models import Case, F, When


def fill_kw(apps, schema_editor):
    Check = apps.get_model("api", "Check")
    Check.objects.update(
        success_kw=F("subject"),
        failure_kw=F("subject_fail"),
        filter_subject=Case(
            When(subject__gt="", then=True),
            When(subject_fail__gt="", then=True),
            default=False,
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0087_check_failure_kw_check_filter_body_and_more"),
    ]

    operations = [migrations.RunPython(fill_kw, migrations.RunPython.noop)]
