"""Database models for Moon Distribution."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from solo.models import SingletonModel

from allianceauth.eveonline.models import EveCorporationInfo


class General(models.Model):
    """Unmanaged model that only carries the app permissions."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", "Can access Moon Distribution (view rounds, apply as CEO/Director)"),
            ("mining_officer", "Can manage rounds, moons and settings"),
        )


class DistributionSettings(SingletonModel):
    """Singleton with all settings that the Mining Officer can change in the UI."""

    alliance_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("EVE alliance ID whose corps may apply and whose refineries are imported."),
    )

    # Weights of the three criteria – 0 disables a criterion completely
    weight_pvp = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
    weight_members = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(100)])
    weight_fleet = models.PositiveSmallIntegerField(default=40, validators=[MaxValueValidator(100)])

    per_member = models.BooleanField(
        default=False,
        help_text=_(
            "Divide PvP and fleet values by the active members, "
            "so small but very active corps are not outranked by size alone."
        ),
    )

    # --- Fairness ---
    exclude_r64 = models.BooleanField(
        default=True, help_text=_("R64 moons are kept by the alliance and never put into a round."),
    )
    max_r32_per_corp = models.PositiveSmallIntegerField(
        null=True, blank=True, default=1,
        help_text=_("Max. R32 moons per corp and round. Empty = no limit."),
    )
    max_r16_per_corp = models.PositiveSmallIntegerField(
        null=True, blank=True, default=None,
        help_text=_("Max. R16 moons per corp and round. Empty = no limit."),
    )
    bonus_no_moon = models.PositiveSmallIntegerField(
        default=15, validators=[MaxValueValidator(100)],
        help_text=_("Bonus points if the corp applied in the previous round and got no moon at all. 0 = off."),
    )
    bonus_no_r32 = models.PositiveSmallIntegerField(
        default=8, validators=[MaxValueValidator(100)],
        help_text=_("Bonus points if the corp got moons in the previous round, but no R32. 0 = off."),
    )
    max_moons_per_corp = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1)],
        help_text=_("Maximum number of moons a single corp can receive per round."),
    )
    max_wishes = models.PositiveSmallIntegerField(
        default=10, validators=[MinValueValidator(1)],
        help_text=_("Maximum number of moons a corp can put on its wishlist."),
    )
    active_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1)],
        help_text=_("A player counts as active if one of his characters logged in within this many days."),
    )
    application_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1)],
        help_text=_("Applications stay open this many days after a round is opened, then it is distributed once."),
    )
    allow_directors = models.BooleanField(
        default=True,
        help_text=_("Besides the CEO, also directors (Corptools role data) may apply for their corp."),
    )

    class Meta:
        default_permissions = ()
        verbose_name = _("settings")
        verbose_name_plural = _("settings")

    def __str__(self):
        return "Moon Distribution Settings"

    @property
    def rarity_limits(self) -> dict:
        """Per-corp limits by rarity – only rarities with a limit are included (None = unlimited)."""
        limits = {}
        if self.max_r32_per_corp is not None:
            limits["R32"] = self.max_r32_per_corp
        if self.max_r16_per_corp is not None:
            limits["R16"] = self.max_r16_per_corp
        return limits

    @property
    def weights(self) -> dict:
        """Weights as dict, keyed like the score fields."""
        return {
            "pvp": self.weight_pvp,
            "members": self.weight_members,
            "fleet": self.weight_fleet,
        }


class Moon(models.Model):
    """A moon with an alliance refinery – imported from Corptools or added manually."""

    class Rarity(models.TextChoices):
        UNKNOWN = "", _("unknown")
        R4 = "R4", "R4"
        R8 = "R8", "R8"
        R16 = "R16", "R16"
        R32 = "R32", "R32"
        R64 = "R64", "R64"

    name = models.CharField(max_length=150, help_text=_("Moon name, e.g. 'R-ARKN VII - Moon 3'"))
    system_name = models.CharField(max_length=100, blank=True, default="")
    region_name = models.CharField(
        max_length=100, blank=True, default="",
        help_text=_("Filled automatically from the EVE map data (SDE) – used for the region tabs."),
    )
    structure_id = models.BigIntegerField(
        null=True, blank=True, unique=True,
        help_text=_("Refinery structure ID (set automatically by the Corptools import)."),
    )
    structure_name = models.CharField(max_length=150, blank=True, default="")
    owner_corporation = models.ForeignKey(
        EveCorporationInfo, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text=_("Corp that currently owns the moon (alliance corp known in AA)."),
    )
    owner_name = models.CharField(
        max_length=150, blank=True, default="",
        help_text=_("Owner as written in the sheet – kept even if the corp is not known in AA."),
    )
    rarity = models.CharField(max_length=3, choices=Rarity.choices, blank=True, default="")
    composition = models.JSONField(
        default=list, blank=True,
        help_text=_("Ore composition, e.g. [{'ore': 'Zircon', 'percent': 24.5}, ...] – filled by the scan/sheet import."),
    )
    notes = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(
        default=True, help_text=_("Inactive moons are not added to new rounds."),
    )
    last_seen = models.DateTimeField(null=True, blank=True, help_text=_("Last seen in Corptools import."))

    class Meta:
        default_permissions = ()
        ordering = ["region_name", "system_name", "name"]

    def __str__(self):
        return self.name

    @property
    def composition_display(self) -> list:
        """Composition with rarity per ore, best ore first – used by the templates."""
        from .rarity import RARITY_ORDER, ore_rarity

        rows = [{**c, "rarity": ore_rarity(c.get("ore", ""))} for c in (self.composition or [])]
        return sorted(rows, key=lambda r: (-RARITY_ORDER.get(r["rarity"], 0), -(r.get("percent") or 0)))

    @property
    def owner_display(self) -> str:
        """Owner corp name: the AA corp if linked, otherwise the name from the sheet."""
        if self.owner_corporation_id:
            return self.owner_corporation.corporation_name
        return self.owner_name

    @property
    def best_share(self):
        """Share (%) of the valuable ore: best ore of the moon's own rarity class, else the rarest ore,
        else the % from the simple sheet note ('28 %'). None if unknown."""
        rows = self.composition_display
        own = [r.get("percent") for r in rows if r["rarity"] == self.rarity and r.get("percent") is not None]
        if own:
            return max(own)
        if rows and rows[0].get("percent") is not None:
            return rows[0]["percent"]
        note = (self.notes or "").strip()
        if note.endswith("%"):
            try:
                return float(note.rstrip("% ").replace(",", "."))
            except ValueError:
                return None
        return None

    @property
    def rarity_sort(self) -> float:
        """Sort key 'rarity, then best share': R32 with 59.9 % → 32059.9 (used by the sortable tables)."""
        from .rarity import RARITY_ORDER

        return RARITY_ORDER.get(self.rarity, 0) * 1000 + (self.best_share or 0)


class Round(models.Model):
    """One distribution round (usually every 6 months)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        OPEN = "open", _("Applications open")
        CLOSED = "closed", _("Closed – waiting for evaluation")
        DONE = "done", _("Distributed")

    name = models.CharField(max_length=100, help_text=_("e.g. 'Moon Distribution H1/2027'"))
    description = models.TextField(blank=True, default="")
    application_start = models.DateTimeField(
        null=True, blank=True, help_text=_("Set automatically when the round is opened."),
    )
    application_end = models.DateTimeField(
        null=True, blank=True,
        help_text=_("Set automatically when the round is opened; the round is distributed once at this time."),
    )
    evaluation_start = models.DateField(help_text=_("Start of the activity period that is checked."))
    evaluation_end = models.DateField(help_text=_("End of the activity period that is checked."))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    moons = models.ManyToManyField(Moon, related_name="rounds", blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    distributed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    # Snapshot of the settings used for the evaluation, so later changes don't alter old results
    settings_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def is_open(self) -> bool:
        """True while corps may submit or change applications."""
        if self.status != self.Status.OPEN or not self.application_start or not self.application_end:
            return False
        return self.application_start <= timezone.now() < self.application_end

    @staticmethod
    def default_evaluation_window(application_end) -> tuple:
        """Default activity window: the 6 months before applications close."""
        end = application_end.date() if hasattr(application_end, "date") else application_end
        start = end - timedelta(days=182)
        return start, end


class Application(models.Model):
    """Application of one corp for one round."""

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="applications")
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name="+")
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    comment = models.TextField(blank=True, default="")

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["round", "corporation"], name="moondist_one_application_per_corp"),
        ]
        ordering = ["submitted_at"]

    def __str__(self):
        return f"{self.corporation} – {self.round}"


class ApplicationWish(models.Model):
    """One moon on the wishlist of an application. Priority 1 = most wanted."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="wishes")
    moon = models.ForeignKey(Moon, on_delete=models.CASCADE, related_name="+")
    priority = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["application", "moon"], name="moondist_wish_unique_moon"),
            models.UniqueConstraint(fields=["application", "priority"], name="moondist_wish_unique_priority"),
        ]
        ordering = ["priority"]

    def __str__(self):
        return f"{self.application.corporation} #{self.priority}: {self.moon}"


class RoundBonus(models.Model):
    """Manual bonus (or malus) points for a corp in a round, with a reason that everyone can see."""

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="bonuses")
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name="+")
    points = models.SmallIntegerField(validators=[MinValueValidator(-100), MaxValueValidator(100)])
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["round", "corporation"], name="moondist_one_bonus_per_corp"),
        ]
        ordering = ["corporation__corporation_name"]

    def __str__(self):
        return f"{self.corporation}: {self.points:+d}"


class CorporationScore(models.Model):
    """Collected activity and calculated score of an applying corp in a round."""

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="scores")
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name="+")

    # Raw values
    pvp_kills = models.PositiveIntegerField(default=0)
    members_total = models.PositiveIntegerField(default=0)
    members_active = models.PositiveIntegerField(default=0)
    fleet_participations = models.PositiveIntegerField(default=0)

    # Normalised sub-scores 0–100
    score_pvp = models.FloatField(default=0)
    score_members = models.FloatField(default=0)
    score_fleet = models.FloatField(default=0)

    base_score = models.FloatField(default=0, help_text=_("Weighted activity score before bonuses."))
    bonus_auto = models.FloatField(default=0, help_text=_("Compensation for a bad result in the previous round."))
    bonus_manual = models.FloatField(default=0, help_text=_("Bonus set by the Mining Officer."))
    bonus_note = models.CharField(max_length=500, blank=True, default="")
    total_score = models.FloatField(default=0)
    rank = models.PositiveSmallIntegerField(default=0)
    pvp_error = models.BooleanField(default=False, help_text=_("zKillboard could not be reached."))

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["round", "corporation"], name="moondist_one_score_per_corp"),
        ]
        ordering = ["rank"]

    def __str__(self):
        return f"{self.corporation}: {self.total_score:.1f}"


class Allocation(models.Model):
    """Result: which corp got which moon in a round."""

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="allocations")
    moon = models.ForeignKey(Moon, on_delete=models.CASCADE, related_name="allocations")
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name="+")
    wish_priority = models.PositiveSmallIntegerField(help_text=_("Which wish of the corp this was."))
    pick_number = models.PositiveSmallIntegerField(help_text=_("Order in which the moon was assigned."))

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["round", "moon"], name="moondist_moon_once_per_round"),
        ]
        ordering = ["pick_number"]

    def __str__(self):
        return f"{self.moon} → {self.corporation}"
