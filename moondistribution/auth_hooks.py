"""Alliance Auth hooks: side menu entry and URL registration."""

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import app_settings, urls
from .utils import open_rounds_count


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
        """Render for members (basic_access) and officers (mining_officer); badge = number of open rounds."""
        user = request.user
        if user.has_perm("moondistribution.basic_access") or user.has_perm("moondistribution.mining_officer"):
            self.count = open_rounds_count() or None
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the side menu entry."""
    return MoonDistributionMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register the app URLs under /moondistribution/ (all views need a login)."""
    return UrlHook(urls, "moondistribution", r"^moondistribution/")
