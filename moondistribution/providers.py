"""Data collection: PvP, members and fleet activity per corp, plus moon import from Corptools.

Every activity is attributed via the *main character* of the AA user. That way
alt corps count for the corp of the player's main.
"""

import logging
import time
from datetime import date, timedelta

import requests

from django.apps import apps
from django.contrib.auth.models import User
from django.db.models import Count
from django.utils import timezone

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from . import app_settings
from .models import DistributionSettings, Moon

logger = logging.getLogger(__name__)

# Path from a corptools CharacterAudit to the corp ID of the owner's main
_MAIN_CORP = "character_ownership__user__profile__main_character__corporation_id"


# ---------------------------------------------------------------------------
# Alliance / eligibility helpers
# ---------------------------------------------------------------------------

def alliance_corporations():
    """All corps of the configured alliance (empty queryset if no alliance is set)."""
    alliance_id = DistributionSettings.get_solo().alliance_id
    if alliance_id is None:
        return EveCorporationInfo.objects.none()
    return EveCorporationInfo.objects.filter(alliance__alliance_id=alliance_id).order_by("corporation_name")


def eligible_corporations_for(user: User, include_officer: bool = True):
    """Corps the user may apply for: CEO (or director, if allowed) of an alliance corp.

    Mining Officers may apply for every alliance corp (e.g. on behalf of a CEO);
    include_officer=False returns only the corps the user leads himself.
    """
    corps = alliance_corporations()
    if include_officer and user.has_perm("moondistribution.mining_officer"):
        return corps

    chars = EveCharacter.objects.filter(character_ownership__user=user)
    char_ids = set(chars.values_list("character_id", flat=True))
    allowed_ids = set(corps.filter(ceo_id__in=char_ids).values_list("corporation_id", flat=True))

    if DistributionSettings.get_solo().allow_directors and apps.is_installed("corptools"):
        from corptools.models import CharacterRoles

        director_corp_ids = CharacterRoles.objects.filter(
            character__character__in=chars, director=True,
        ).values_list("character__character__corporation_id", flat=True)
        allowed_ids |= set(director_corp_ids)

    return corps.filter(corporation_id__in=allowed_ids)


# ---------------------------------------------------------------------------
# Activity collectors – each returns {corporation_id: value}
# ---------------------------------------------------------------------------

def collect_members(corp_ids: list, active_days: int) -> dict:
    """Total and active players (AA users) per corp, counted by their main character."""
    result = {cid: {"total": 0, "active": 0} for cid in corp_ids}

    totals = (
        User.objects.filter(profile__main_character__corporation_id__in=corp_ids)
        .values("profile__main_character__corporation_id")
        .annotate(n=Count("id"))
    )
    for row in totals:
        result[row["profile__main_character__corporation_id"]]["total"] = row["n"]

    if apps.is_installed("corptools"):
        from corptools.models import CharacterAudit

        since = timezone.now() - timedelta(days=active_days)
        active = (
            CharacterAudit.objects.filter(
                last_known_login__gte=since,
                **{f"character__{_MAIN_CORP}__in": corp_ids},
            )
            .values(f"character__{_MAIN_CORP}")
            .annotate(n=Count("character__character_ownership__user", distinct=True))
        )
        for row in active:
            result[row[f"character__{_MAIN_CORP}"]]["active"] = row["n"]

    # Fallback: without any login data (missing scope) treat all members as active
    if not any(v["active"] for v in result.values()):
        logger.info("No login data from Corptools – using total members as active members")
        for v in result.values():
            v["active"] = v["total"]
    return result


def collect_fleets(corp_ids: list, start: date, end: date) -> dict:
    """Fleet participations per corp – aFAT if installed, otherwise the AA built-in FAT."""
    result = {cid: 0 for cid in corp_ids}

    if apps.is_installed("afat"):
        from afat.models import Fat

        rows = (
            Fat.objects.filter(
                fatlink__created__date__gte=start, fatlink__created__date__lte=end,
                **{f"character__{_MAIN_CORP}__in": corp_ids},
            )
            .values(f"character__{_MAIN_CORP}")
            .annotate(n=Count("id"))
        )
        key = f"character__{_MAIN_CORP}"
    elif apps.is_installed("allianceauth.fleetactivitytracking"):
        from allianceauth.fleetactivitytracking.models import Fat

        rows = (
            Fat.objects.filter(
                fatlink__fatdatetime__date__gte=start, fatlink__fatdatetime__date__lte=end,
                user__profile__main_character__corporation_id__in=corp_ids,
            )
            .values("user__profile__main_character__corporation_id")
            .annotate(n=Count("id"))
        )
        key = "user__profile__main_character__corporation_id"
    else:
        logger.warning("Neither aFAT nor the AA fleet activity tracking is installed – fleet score is 0")
        return result

    for row in rows:
        result[row[key]] = row["n"]
    return result


def fetch_zkill_kills(corporation_id: int, start: date, end: date) -> int:
    """Ships destroyed by a corp in the window, from the zKillboard monthly stats.

    Raises requests.RequestException if zKillboard is not reachable.
    """
    url = f"https://zkillboard.com/api/stats/corporationID/{corporation_id}/"
    response = requests.get(
        url,
        headers={"User-Agent": app_settings.MOONDIST_ZKILL_USER_AGENT, "Accept-Encoding": "gzip"},
        timeout=app_settings.MOONDIST_ZKILL_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json() or {}
    months = data.get("months") or {}

    first = start.year * 100 + start.month
    last = end.year * 100 + end.month
    kills = 0
    for month in months.values():
        key = int(month.get("year", 0)) * 100 + int(month.get("month", 0))
        if first <= key <= last:
            kills += int(month.get("shipsDestroyed") or 0)
    return kills


def collect_pvp(corp_ids: list, start: date, end: date) -> tuple:
    """Kills per corp from zKillboard. Returns ({corp_id: kills}, {corp_ids with errors})."""
    result, errors = {}, set()
    for i, cid in enumerate(corp_ids):
        if i:
            time.sleep(1)  # be nice to zKillboard
        try:
            result[cid] = fetch_zkill_kills(cid, start, end)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("zKillboard request for corp %s failed: %s", cid, exc)
            result[cid] = 0
            errors.add(cid)
    return result, errors


# ---------------------------------------------------------------------------
# Moon import
# ---------------------------------------------------------------------------

def sync_moons_from_corptools() -> dict:
    """Create/update moons from the refineries (Athanor/Tatara) of all alliance corps in Corptools."""
    stats = {"created": 0, "updated": 0, "skipped": 0}
    settings = DistributionSettings.get_solo()
    if settings.alliance_id is None:
        raise ValueError("No alliance configured in the Moon Distribution settings.")
    if not apps.is_installed("corptools"):
        raise ValueError("Corptools is not installed.")

    from corptools.models import Structure

    structures = Structure.objects.filter(
        type_id__in=app_settings.MOONDIST_REFINERY_TYPE_IDS,
        corporation__corporation__alliance__alliance_id=settings.alliance_id,
    ).select_related("closest_celestial", "system_name", "corporation__corporation")

    now = timezone.now()
    for structure in structures:
        celestial = structure.closest_celestial
        moon_name = celestial.celestial_name if celestial and celestial.celestial_name else ""
        if not moon_name:
            stats["skipped"] += 1  # celestial not resolved yet by Corptools
            continue
        _moon, created = Moon.objects.update_or_create(
            structure_id=structure.structure_id,
            defaults={
                "name": moon_name,
                "system_name": structure.system_name.name if structure.system_name else "",
                "structure_name": structure.name,
                "owner_corporation": structure.corporation.corporation,
                "last_seen": now,
            },
        )
        stats["created" if created else "updated"] += 1

    # Fill missing rarities from aa-moonmining (never overwrites a rarity that is already set)
    from .rarity import apply_rarities, fill_missing_regions, rarities_from_moonmining

    mm = rarities_from_moonmining()
    stats["rarity_from_moonmining"] = apply_rarities(mm)["updated"] if mm else 0
    stats["regions"] = fill_missing_regions()
    logger.info("Moon sync finished: %s", stats)
    return stats
