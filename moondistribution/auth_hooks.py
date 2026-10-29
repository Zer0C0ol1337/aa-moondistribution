"""Alliance Auth hooks: side menu entry and URL registration."""

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import app_settings, urls
from .models import Round


class MoonDistributionMenuItem(MenuItemHook):
    """Side menu entry – shows a badge while a round is open for applications."""

    def __init__(self):
        """Set label, icon and the URL names that keep the entry highlighted."""
        MenuItemHook.__init__(
            self,
            app_settings.MOONDIST_APP_NAME,
            "fas fa-moon fa-fw",
            "moondistribution:index",
            navactive=["moondistribution:"],
        )

    def render(self, request):
        """Only render for users with basic_access; badge = number of open rounds."""
        if request.user.has_perm("moondistribution.basic_access"):
            open_rounds = Round.objects.filter(status=Round.Status.OPEN).count()
            self.count = open_rounds or None
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the side menu entry."""
    return MoonDistributionMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register the app URLs under /moondistribution/."""
    return UrlHook(urls, "moondistribution", r"^moondistribution/")
