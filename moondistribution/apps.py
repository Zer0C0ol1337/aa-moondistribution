"""App config for Moon Distribution."""

from django.apps import AppConfig

from . import __version__


class MoonDistributionConfig(AppConfig):
    """Django app config – registers the app under the label 'moondistribution'."""

    name = "moondistribution"
    label = "moondistribution"
    verbose_name = f"Moon Distribution v{__version__}"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Register the system checks (no database access at startup)."""
        from . import checks  # noqa: F401
