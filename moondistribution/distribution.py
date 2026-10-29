"""Scoring and automatic moon allocation.

The pure functions (normalize_scores, rank_corporations, allocate_moons) don't
touch the database and are unit tested. run_distribution() wires them together
with the data providers and stores the result.
"""

import logging

from django.db import transaction
from django.utils import timezone

from allianceauth.notifications import notify

from . import providers
from .models import Allocation, Application, CorporationScore, DistributionSettings, Round

logger = logging.getLogger(__name__)

CRITERIA = ("mining", "pvp", "members", "fleet")


def normalize_scores(raw: dict, weights: dict, per_member: bool = False) -> dict:
    """Turn raw activity values into sub-scores (0–100) and a weighted total.

    raw:     {corp_id: {"mining": x, "pvp": x, "members": active, "fleet": x}}
    weights: {"mining": w, ...} – a weight of 0 removes the criterion.
    Every criterion is scaled against the best applicant (best = 100).
    """
    values = {}
    for cid, data in raw.items():
        members = data.get("members") or 0
        row = {}
        for crit in CRITERIA:
            value = float(data.get(crit) or 0)
            if per_member and crit != "members":
                value = value / members if members > 0 else 0.0
            row[crit] = value
        values[cid] = row

    maxima = {crit: max((v[crit] for v in values.values()), default=0.0) for crit in CRITERIA}
    weight_sum = sum(w for w in weights.values() if w is not None)

    result = {}
    for cid, row in values.items():
        subs = {
            crit: (row[crit] / maxima[crit] * 100.0) if maxima[crit] > 0 else 0.0
            for crit in CRITERIA
        }
        total = (
            sum(subs[crit] * (weights.get(crit) or 0) for crit in CRITERIA) / weight_sum
            if weight_sum > 0 else 0.0
        )
        result[cid] = {**{f"score_{c}": round(subs[c], 2) for c in CRITERIA}, "total": round(total, 2)}
    return result


def rank_corporations(scores: dict, submitted_order: list) -> list:
    """Corp IDs sorted by total score (desc); ties go to the earlier application."""
    position = {cid: i for i, cid in enumerate(submitted_order)}
    return sorted(scores, key=lambda cid: (-scores[cid]["total"], position.get(cid, len(position))))


def allocate_moons(ranking: list, wishes: dict, max_per_corp: int) -> list:
    """Draft-style allocation.

    In every pass each corp (in ranking order) receives its highest-priority wish
    that is still free, until all corps hit max_per_corp or no wish can be served.

    wishes: {corp_id: [(priority, moon_id), ...]}
    returns [{"pick": n, "corp": id, "moon": id, "priority": p}, ...]
    """
    taken, counts, picks = set(), {cid: 0 for cid in ranking}, []
    while True:
        progress = False
        for cid in ranking:
            if counts[cid] >= max_per_corp:
                continue
            for priority, moon_id in sorted(wishes.get(cid, [])):
                if moon_id not in taken:
                    taken.add(moon_id)
                    counts[cid] += 1
                    picks.append({"pick": len(picks) + 1, "corp": cid, "moon": moon_id, "priority": priority})
                    progress = True
                    break
        if not progress:
            return picks


def run_distribution(round_obj: Round) -> None:
    """Collect activity for all applicants, score them, allocate the moons and store everything.

    Raises on unexpected errors – the caller stores the message in round.last_error.
    """
    settings = DistributionSettings.get_solo()
    applications = list(
        round_obj.applications.select_related("corporation", "submitted_by").prefetch_related("wishes")
    )
    corp_ids = [a.corporation.corporation_id for a in applications]
    start, end = round_obj.evaluation_start, round_obj.evaluation_end

    # 1) collect raw activity (zKill first – slowest, done outside the transaction)
    members = providers.collect_members(corp_ids, settings.active_days)
    mining = providers.collect_mining(corp_ids, start, end)
    fleets = providers.collect_fleets(corp_ids, start, end)
    pvp, pvp_errors = providers.collect_pvp(corp_ids, start, end) if settings.weight_pvp else ({}, set())

    raw = {
        cid: {
            "mining": mining.get(cid, 0),
            "pvp": pvp.get(cid, 0),
            "members": members[cid]["active"],
            "fleet": fleets.get(cid, 0),
        }
        for cid in corp_ids
    }

    # 2) score + rank + allocate
    scores = normalize_scores(raw, settings.weights, settings.per_member)
    ranking = rank_corporations(scores, corp_ids)  # applications are ordered by submitted_at
    pool = set(round_obj.moons.values_list("id", flat=True))
    wishes = {
        a.corporation.corporation_id: [(w.priority, w.moon_id) for w in a.wishes.all() if w.moon_id in pool]
        for a in applications
    }
    picks = allocate_moons(ranking, wishes, settings.max_moons_per_corp)

    # 3) store result atomically
    corp_by_id = {a.corporation.corporation_id: a.corporation for a in applications}
    with transaction.atomic():
        round_obj.scores.all().delete()
        round_obj.allocations.all().delete()
        CorporationScore.objects.bulk_create([
            CorporationScore(
                round=round_obj,
                corporation=corp_by_id[cid],
                mining_volume=raw[cid]["mining"],
                pvp_kills=raw[cid]["pvp"],
                members_total=members[cid]["total"],
                members_active=members[cid]["active"],
                fleet_participations=raw[cid]["fleet"],
                score_mining=scores[cid]["score_mining"],
                score_pvp=scores[cid]["score_pvp"],
                score_members=scores[cid]["score_members"],
                score_fleet=scores[cid]["score_fleet"],
                total_score=scores[cid]["total"],
                rank=rank,
                pvp_error=cid in pvp_errors,
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
        }
        round_obj.save()

    _notify_applicants(round_obj, applications, picks)
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


def application_summary(round_obj: Round) -> list:
    """Applications of a round with their wishes – used by the officer view."""
    return list(
        Application.objects.filter(round=round_obj)
        .select_related("corporation", "submitted_by__profile__main_character")
        .prefetch_related("wishes__moon")
    )
