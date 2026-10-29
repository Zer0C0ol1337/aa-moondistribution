"""Django admin – mainly for debugging, day-to-day work happens in the app UI."""

from django.contrib import admin

from .models import (
    Allocation, Application, ApplicationWish, CorporationScore, DistributionSettings, Moon, Round, RoundBonus,
)


@admin.register(DistributionSettings)
class DistributionSettingsAdmin(admin.ModelAdmin):
    """Singleton settings."""

    list_display = ("__str__", "alliance_id", "weight_mining", "weight_pvp", "weight_members", "weight_fleet")


@admin.register(Moon)
class MoonAdmin(admin.ModelAdmin):
    """Moons with refinery info."""

    list_display = ("name", "system_name", "rarity", "owner_corporation", "is_active", "last_seen")
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
class CorporationScoreAdmin(admin.ModelAdmin):
    """Calculated scores."""

    list_display = ("round", "rank", "corporation", "total_score", "base_score", "bonus_auto", "bonus_manual",
                    "mining_volume", "pvp_kills",
                    "members_active", "fleet_participations")
    list_filter = ("round",)


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    """Distribution results."""

    list_display = ("round", "pick_number", "moon", "corporation", "wish_priority")
    list_filter = ("round",)
