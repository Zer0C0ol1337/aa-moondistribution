"""Probation: corps may only apply after being in the alliance for a configurable number of months.

The join date is taken from the public EVE alliance history of the corp (ESI, no token needed)
and stored in CorporationProbation. Requests never call ESI – they only read the stored date;
the Celery task update_join_dates refreshes it (when a round is opened, on the officer's button
and right before a round is distributed).
"""

import calendar
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allianceauth.services.hooks import get_extension_logger

from . import __version__
from .models import CorporationProbation, DistributionSettings

logger = get_extension_logger(__name__)

ESI_COMPATIBILITY_DATE = "2025-12-16"
_esi = None
_LOOKUP = object()  # "record not passed – look it up"


def _esi_client():
    """ESI client limited to the one public operation we need (created on first use, not at import)."""
    global _esi
    if _esi is None:
        from esi.openapi_clients import ESIClientProvider

        _esi = ESIClientProvider(
            compatibility_date=ESI_COMPATIBILITY_DATE,
            ua_appname="aa-moondistribution",
            ua_version=__version__,
            ua_url="https://github.com/Zer0C0ol1337/aa-moondistribution",
            operations=["GetCorporationsCorporationIdAlliancehistory"],
        )
    return _esi.client


def _field(entry, name):
    """Read a field from an ESI result entry (object or dict)."""
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def _as_datetime(value):
    """ESI date (datetime or ISO string) → aware datetime."""
    if isinstance(value, str):
        value = parse_datetime(value)
    if isinstance(value, datetime) and timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value


def join_date_from_history(history, alliance_id: int):
    """Start of the CURRENT membership in the alliance from an alliance history list.

    The newest entry (highest record_id) is the current one. Returns None if the corp is
    not (or no longer) in that alliance according to the history.
    """
    entries = sorted(history or [], key=lambda e: _field(e, "record_id") or 0, reverse=True)
    if not entries:
        return None
    current = entries[0]
    if _field(current, "alliance_id") != alliance_id:
        return None
    return _as_datetime(_field(current, "start_date"))


def fetch_join_date(corporation_id: int, alliance_id: int):
    """Ask ESI for the alliance history of one corp. Raises on ESI errors."""
    history = _esi_client().Corporation.GetCorporationsCorporationIdAlliancehistory(
        corporation_id=corporation_id,
    ).result()
    return join_date_from_history(history, alliance_id)


def update_join_dates(corporations) -> dict:
    """Refresh the stored join date of the given corps from ESI. ESI errors keep the old value."""
    settings = DistributionSettings.get_solo()
    stats = {"updated": 0, "failed": 0}
    if not settings.alliance_id:
        return stats
    for corp in corporations:
        try:
            joined = fetch_join_date(corp.corporation_id, settings.alliance_id)
        except Exception:  # ESI down / timeout – never block anybody because of that
            logger.warning("Alliance history of corp %s not available from ESI", corp.corporation_id, exc_info=True)
            stats["failed"] += 1
            continue
        CorporationProbation.objects.update_or_create(
            corporation=corp, defaults={"joined_at": joined, "checked_at": timezone.now()},
        )
        stats["updated"] += 1
    return stats


def add_months(value: datetime, months: int) -> datetime:
    """value + months (end of month safe: Nov 30 + 3 months → Feb 28/29)."""
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def probation_status(corporation, record=_LOOKUP, months=None, now=None) -> dict:
    """Probation state of a corp.

    Returns {"blocked": bool, "joined_at", "ends_at", "unknown": bool, "exempt": bool, "reason": str}.
    blocked = still in probation and no exception. Unknown join dates never block.
    """
    if months is None:
        months = DistributionSettings.get_solo().probation_months
    if record is _LOOKUP:
        record = CorporationProbation.objects.filter(corporation=corporation).first()
    now = now or timezone.now()
    joined = record.joined_at if record else None
    exempt = bool(record and record.exempt)
    ends = add_months(joined, months) if joined and months else None
    return {
        "joined_at": joined,
        "ends_at": ends,
        "unknown": record is None or record.joined_at is None,
        "exempt": exempt,
        "reason": record.exempt_reason if record else "",
        "in_probation": bool(ends and ends > now),
        "blocked": bool(ends and ends > now and not exempt),
    }


def blocked_corporation_ids(corporations) -> set:
    """IDs of the given corps that are still in their probation (without exception)."""
    months = DistributionSettings.get_solo().probation_months
    if not months:
        return set()
    corps = list(corporations)
    records = {r.corporation_id: r for r in CorporationProbation.objects.filter(corporation__in=corps)}
    now = timezone.now()
    return {
        c.corporation_id for c in corps
        if probation_status(c, records.get(c.pk), months, now)["blocked"]
    }
