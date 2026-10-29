"""Django system checks for Moon Distribution (run on startup and with `manage.py check`)."""

from django.apps import apps
from django.core.checks import Tags, Warning, register


@register(Tags.compatibility)
def data_sources_check(app_configs, **kwargs):
    """Warn if a data source for the scoring is missing (no database access here)."""
    warnings = []
    if not apps.is_installed("corptools"):
        warnings.append(Warning(
            "allianceauth-corptools is not in INSTALLED_APPS.",
            hint="Moon import, director roles and active-member logins need Corptools.",
            id="moondistribution.W001",
        ))
    if not apps.is_installed("afat") and not apps.is_installed("allianceauth.fleetactivitytracking"):
        warnings.append(Warning(
            "No fleet tracker installed (aFAT or allianceauth.fleetactivitytracking).",
            hint="The fleet criterion will be 0 for every corp – set its weight to 0 or install a fleet tracker.",
            id="moondistribution.W002",
        ))
    return warnings
