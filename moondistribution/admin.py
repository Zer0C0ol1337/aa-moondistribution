"""Django admin – mainly for debugging, day-to-day work happens in the app UI."""

from solo.admin import SingletonModelAdmin

from django.contrib import admin

from .models import (
    Allocation, Application, ApplicationWish, CorporationProbation, CorporationScore,
    DistributionSettings, Moon, Round, RoundBonus, Sig, SigClaim,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Results are written only by the distribution – visible in the admin, but not editable."""

    def has_add_permission(self, request):
        """No manual results."""
        return False

    def has_change_permission(self, request, obj=None):
        """No manual changes of results."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Results are replaced by 'Re-run distribution', never deleted by hand."""
        return False


@admin.register(DistributionSettings)
class DistributionSettingsAdmin(SingletonModelAdmin):
    """Singleton settings."""



@admin.register(Moon)
class MoonAdmin(admin.ModelAdmin):
    """Moons with refinery info."""

    list_display = ("name", "system_name", "region_name", "rarity", "owner_corporation", "owner_name", "is_active", "last_seen")
    list_filter = ("rarity", "is_active")
    search_fields = ("name", "system_name", "structure_name")


class ApplicationWishInline(admin.TabularInline):
    """Wishlist inside the application."""

    model = ApplicationWish
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    """Applications per round."""

    list_display = ("round", "corporation", "submitted_by", "submitted_at")
    list_filter = ("round",)
    inlines = [ApplicationWishInline]


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    """Rounds."""

    list_display = ("name", "status", "application_start", "application_end", "distributed_at")
    list_filter = ("status",)
    filter_horizontal = ("moons",)


@admin.register(RoundBonus)
class RoundBonusAdmin(admin.ModelAdmin):
    """Manual bonus points."""

    list_display = ("round", "corporation", "points", "reason", "created_by")
    list_filter = ("round",)


@admin.register(CorporationScore)
class CorporationScoreAdmin(ReadOnlyAdmin):
    """Calculated scores."""

    list_display = ("round", "rank", "corporation", "total_score", "base_score", "bonus_auto", "bonus_manual",
                    "pvp_kills",
                    "members_ingame", "members_active", "activity_rate", "fleet_participations")
    list_filter = ("round",)


@admin.register(Allocation)
class AllocationAdmin(ReadOnlyAdmin):
    """Distribution results."""

    list_display = ("round", "pick_number", "moon", "corporation", "wish_priority")
    list_filter = ("round",)


@admin.register(CorporationProbation)
class CorporationProbationAdmin(admin.ModelAdmin):
    """Alliance join dates (from ESI) and probation exceptions."""

    list_display = ("corporation", "joined_at", "checked_at", "exempt", "exempt_reason", "exempt_by")
    list_filter = ("exempt",)
    readonly_fields = ("joined_at", "checked_at")


@admin.register(Sig)
class SigAdmin(admin.ModelAdmin):
    """SIGs (AA groups whose leaders may claim moons)."""

    list_display = ("name", "group", "is_active")


@admin.register(SigClaim)
class SigClaimAdmin(admin.ModelAdmin):
    """SIG claims per round (normally handled on the SIG page)."""

    list_display = ("round", "sig", "moon", "status", "requested_by", "decided_by", "decided_at")
    list_filter = ("round", "sig", "status")
    raw_id_fields = ("moon",)

