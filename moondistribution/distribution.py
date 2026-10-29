"""Scoring and automatic moon allocation.

The pure functions (normalize_scores, rank_corporations, allocate_moons) don't
touch the database and are unit tested. run_distribution() wires them together
with the data providers and stores the result.
"""


from django.db import transaction
from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger
from allianceauth.notifications import notify

from . import probation, providers, sigs
from .models import Allocation, Application, CorporationScore, DistributionSettings, Moon, Round

logger = get_extension_logger(__name__)

CRITERIA = ("pvp", "members", "fleet", "activity")
# criteria that are never divided by the members in per-member mode
_NOT_PER_MEMBER = ("members", "activity")


def normalize_scores(raw: dict, weights: dict, per_member: bool = False, skip: dict | None = None) -> dict:
    """Turn raw activity values into sub-scores (0–100) and a weighted total.

    raw:     {corp_id: {"pvp": x, "members": active, "fleet": x, "activity": rate in %}}
    weights: {"pvp": w, ...} – a weight of 0 removes the criterion.
    skip:    {corp_id: {"members", "activity"}} – criteria that are not rated for this corp
             (no Auth data); its total is the weighted average of its remaining criteria.
    Every criterion is scaled against the best applicant (best = 100).
    """
    skip = skip or {}
    values = {}
    for cid, data in raw.items():
        members = data.get("members") or 0
        row = {}
        for crit in CRITERIA:
            value = float(data.get(crit) or 0)
            if per_member and crit not in _NOT_PER_MEMBER:
                value = value / members if members > 0 else 0.0
            row[crit] = value
        values[cid] = row

    maxima = {
        crit: max((v[crit] for cid, v in values.items() if crit not in skip.get(cid, ())), default=0.0)
        for crit in CRITERIA
    }

    result = {}
    for cid, row in values.items():
        skipped = skip.get(cid, set())
        subs = {
            crit: (row[crit] / maxima[crit] * 100.0) if maxima[crit] > 0 and crit not in skipped else 0.0
            for crit in CRITERIA
        }
        rated = [crit for crit in CRITERIA if crit not in skipped]
        weight_sum = sum(weights.get(crit) or 0 for crit in rated)
        total = (
            sum(subs[crit] * (weights.get(crit) or 0) for crit in rated) / weight_sum
            if weight_sum > 0 else 0.0
        )
        result[cid] = {**{f"score_{c}": round(subs[c], 2) for c in CRITERIA}, "total": round(total, 2)}
    return result


def rank_corporations(scores: dict, submitted_order: list) -> list:
    """Corp IDs sorted by total score (desc); ties go to the earlier application."""
    position = {cid: i for i, cid in enumerate(submitted_order)}
    return sorted(scores, key=lambda cid: (-scores[cid]["total"], position.get(cid, len(position))))


def compensation_bonus(corp_ids: list, previous: dict | None, bonus_no_moon: int, bonus_no_r32: int) -> dict:
    """Automatic bonus for corps that did badly in the previous round.

    previous: {corp_id: [rarity of each moon received]} for every corp that APPLIED last round,
              or None if there is no previous round.
    - applied, got no moon at all      → bonus_no_moon
    - applied, got moons but no R32    → bonus_no_r32
    - got an R32 / did not apply       → 0
    """
    result = {cid: 0 for cid in corp_ids}
    if not previous:
        return result
    for cid in corp_ids:
        if cid not in previous:
            continue
        received = previous[cid]
        if not received:
            result[cid] = bonus_no_moon
        elif "R32" not in received:
            result[cid] = bonus_no_r32
    return result


def allocate_moons(ranking: list, wishes: dict, max_per_corp: int,
                   moon_rarity: dict | None = None, rarity_limits: dict | None = None,
                   moon_quality: dict | None = None) -> list:
    """Draft-style allocation.

    In every pass each corp (in ranking order) receives its highest-priority wish
    that is still free, until all corps hit max_per_corp or no wish can be served.
    rarity_limits ({"R32": 1, ...}) cap how many moons of a rarity one corp can get;
    a wish over the limit is skipped and the corp takes its next free wish instead.
    Wishes with the same priority (normally all of them) are served best moon first –
    moon_quality ({moon_id: rarity_sort}) decides: rarity class, then share of the valuable ore.

    wishes: {corp_id: [(priority, moon_id), ...]}
    returns [{"pick": n, "corp": id, "moon": id, "priority": p}, ...]
    """
    moon_rarity = moon_rarity or {}
    rarity_limits = rarity_limits or {}
    moon_quality = moon_quality or {}
    taken, picks = set(), []
    counts = {cid: 0 for cid in ranking}
    rarity_counts = {cid: {} for cid in ranking}
    while True:
        progress = False
        for cid in ranking:
            if counts[cid] >= max_per_corp:
                continue
            ordered = sorted(wishes.get(cid, []), key=lambda w: (w[0], -moon_quality.get(w[1], 0), w[1]))
            for priority, moon_id in ordered:
                if moon_id in taken:
                    continue
                rarity = moon_rarity.get(moon_id, "")
                limit = rarity_limits.get(rarity)
                if limit is not None and rarity_counts[cid].get(rarity, 0) >= limit:
                    continue
                taken.add(moon_id)
                counts[cid] += 1
                rarity_counts[cid][rarity] = rarity_counts[cid].get(rarity, 0) + 1
                picks.append({"pick": len(picks) + 1, "corp": cid, "moon": moon_id, "priority": priority})
                progress = True
                break
        if not progress:
            return picks


def previous_round_results(round_obj: Round) -> dict | None:
    """Result of the last distributed round before this one: {corp_id: [rarities received]} per applicant."""
    previous = (
        Round.objects.filter(status=Round.Status.DONE, created_at__lt=round_obj.created_at)
        .exclude(pk=round_obj.pk)
        .order_by("-created_at")
        .first()
    )
    if previous is None:
        return None
    result = {
        cid: [] for cid in previous.applications.values_list("corporation__corporation_id", flat=True)
    }
    for cid, rarity in previous.allocations.values_list("corporation__corporation_id", "moon__rarity"):
        result.setdefault(cid, []).append(rarity)
    return result


def run_distribution(round_obj: Round) -> None:
    """Collect activity for all applicants, score them, allocate the moons and store everything.

    Raises on unexpected errors – the caller stores the message in round.last_error.
    """
    settings = DistributionSettings.get_solo()
    all_applications = list(
        round_obj.applications.select_related("corporation", "submitted_by").prefetch_related("wishes")
    )
    # 0) probation: refresh the join dates of the applicants from ESI, drop corps that are still in probation
    if settings.probation_months:
        probation.update_join_dates([a.corporation for a in all_applications])
    blocked = probation.blocked_corporation_ids([a.corporation for a in all_applications])
    applications = [a for a in all_applications if a.corporation.corporation_id not in blocked]
    excluded = [a for a in all_applications if a.corporation.corporation_id in blocked]
    corp_ids = [a.corporation.corporation_id for a in applications]
    start, end = round_obj.evaluation_start, round_obj.evaluation_end

    # 1) collect raw activity (zKill first – slowest, done outside the transaction)
    members = providers.collect_members(corp_ids, settings.active_days)
    fleets = providers.collect_fleets(corp_ids, start, end)
    pvp, pvp_errors = providers.collect_pvp(corp_ids, start, end) if settings.weight_pvp else ({}, set())

    raw = {
        cid: {
            "pvp": pvp.get(cid, 0),
            "members": members[cid]["active"],
            "fleet": fleets.get(cid, 0),
            "activity": members[cid]["rate"],
        }
        for cid in corp_ids
    }

    # 2) score + bonuses
    # Corps without Auth access (no registered player, application entered by an officer, e.g. via the
    # Excel template) have no Auth data – members and activity rate are not rated for them instead of 0
    no_auth = {
        a.corporation.corporation_id for a in applications
        if a.entered_by_officer and not members[a.corporation.corporation_id]["total"]
    }
    scores = normalize_scores(
        raw, settings.weights, settings.per_member, skip={cid: _NOT_PER_MEMBER for cid in no_auth},
    )
    auto_bonus = compensation_bonus(
        corp_ids, previous_round_results(round_obj), settings.bonus_no_moon, settings.bonus_no_r32,
    )
    manual = {b.corporation.corporation_id: b for b in round_obj.bonuses.select_related("corporation")}
    for cid in corp_ids:
        base = scores[cid]["total"]
        manual_points = manual[cid].points if cid in manual else 0
        scores[cid]["base"] = base
        scores[cid]["auto"] = auto_bonus[cid]
        scores[cid]["manual"] = manual_points
        scores[cid]["note"] = manual[cid].reason if cid in manual else ""
        scores[cid]["total"] = round(max(0.0, base + auto_bonus[cid] + manual_points), 2)

    # 3) rank + allocate
    ranking = rank_corporations(scores, corp_ids)  # applications are ordered by submitted_at
    pool_qs = round_obj.moons.all()
    if settings.exclude_r64:
        pool_qs = pool_qs.exclude(rarity=Moon.Rarity.R64)
    # moons reserved for a SIG (approved claim) are not distributed
    reserved = sigs.reserved_moon_ids(round_obj)
    pool_qs = pool_qs.exclude(pk__in=reserved)
    pool_moons = list(pool_qs)
    moon_rarity = {m.pk: m.rarity for m in pool_moons}
    moon_quality = {m.pk: m.rarity_sort for m in pool_moons}
    wishes = {
        a.corporation.corporation_id: [(w.priority, w.moon_id) for w in a.wishes.all() if w.moon_id in moon_rarity]
        for a in applications
    }
    picks = allocate_moons(
        ranking, wishes, settings.max_moons_per_corp, moon_rarity, settings.rarity_limits, moon_quality,
    )

    # 4) store result atomically
    corp_by_id = {a.corporation.corporation_id: a.corporation for a in applications}
    with transaction.atomic():
        round_obj.scores.all().delete()
        round_obj.allocations.all().delete()
        CorporationScore.objects.bulk_create([
            CorporationScore(
                round=round_obj,
                corporation=corp_by_id[cid],
                pvp_kills=raw[cid]["pvp"],
                members_total=members[cid]["total"],
                members_active=members[cid]["active"],
                members_ingame=members[cid]["ingame"],
                chars_active=members[cid]["chars_active"],
                activity_rate=members[cid]["rate"],
                fleet_participations=raw[cid]["fleet"],
                score_pvp=scores[cid]["score_pvp"],
                score_members=scores[cid]["score_members"],
                score_fleet=scores[cid]["score_fleet"],
                score_activity=scores[cid]["score_activity"],
                base_score=scores[cid]["base"],
                bonus_auto=scores[cid]["auto"],
                bonus_manual=scores[cid]["manual"],
                bonus_note=scores[cid]["note"][:500],
                total_score=scores[cid]["total"],
                rank=rank,
                pvp_error=cid in pvp_errors,
                no_auth_data=cid in no_auth,
            )
            for rank, cid in enumerate(ranking, start=1)
        ])
        Allocation.objects.bulk_create([
            Allocation(
                round=round_obj,
                moon_id=p["moon"],
                corporation=corp_by_id[p["corp"]],
                wish_priority=p["priority"],
                pick_number=p["pick"],
            )
            for p in picks
        ])
        round_obj.status = Round.Status.DONE
        round_obj.distributed_at = timezone.now()
        round_obj.last_error = (
            f"zKillboard not reachable for {len(pvp_errors)} corp(s) – PvP counted as 0." if pvp_errors else ""
        )
        round_obj.settings_snapshot = {
            "weights": settings.weights,
            "per_member": settings.per_member,
            "max_moons_per_corp": settings.max_moons_per_corp,
            "active_days": settings.active_days,
            "exclude_r64": settings.exclude_r64,
            "rarity_limits": settings.rarity_limits,
            "bonus_no_moon": settings.bonus_no_moon,
            "bonus_no_r32": settings.bonus_no_r32,
            "probation_months": settings.probation_months,
            "probation_excluded": sorted(a.corporation.corporation_name for a in excluded),
            "sig_reserved": len(reserved),
        }
        round_obj.save()

    _notify_applicants(round_obj, applications, picks)
    _notify_excluded(round_obj, excluded, settings.probation_months)
    logger.info("Round %s distributed: %s applicants, %s moons assigned", round_obj.pk, len(applications), len(picks))


def _notify_applicants(round_obj: Round, applications: list, picks: list) -> None:
    """Send an AA notification with the result to everyone who submitted an application."""
    won = {}
    for p in picks:
        won.setdefault(p["corp"], []).append(p["moon"])
    moon_names = dict(round_obj.moons.values_list("id", "name"))
    for app in applications:
        if not app.submitted_by:
            continue
        got = won.get(app.corporation.corporation_id, [])
        if got:
            msg = f"{app.corporation.corporation_name} received: " + ", ".join(moon_names.get(m, "?") for m in got)
            level = "success"
        else:
            msg = f"{app.corporation.corporation_name} did not receive a moon this round."
            level = "info"
        try:
            notify(app.submitted_by, f"Moon Distribution: {round_obj.name}", msg, level)
        except Exception:  # notifications must never break the distribution
            logger.exception("Could not notify user %s", app.submitted_by_id)


def _notify_excluded(round_obj: Round, excluded: list, months: int) -> None:
    """Tell applicants whose corp was not considered because it is still in its probation."""
    for app in excluded:
        if not app.submitted_by:
            continue
        msg = (
            f"{app.corporation.corporation_name} was not considered: corps can take part after "
            f"{months} months in the alliance."
        )
        try:
            notify(app.submitted_by, f"Moon Distribution: {round_obj.name}", msg, "warning")
        except Exception:  # notifications must never break the distribution
            logger.exception("Could not notify user %s", app.submitted_by_id)


def application_summary(round_obj: Round) -> list:
    """Applications of a round with their wishes – used by the officer view."""
    return list(
        Application.objects.filter(round=round_obj)
        .select_related("corporation", "submitted_by__profile__main_character")
        .prefetch_related("wishes__moon")
    )
