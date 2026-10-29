"""Views of Moon Distribution."""

import logging
from datetime import timedelta

from django.apps import apps
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from allianceauth.eveonline.models import EveCorporationInfo

from . import __version__
from .decorators import check_access, officer_required
from .distribution import application_summary
from .forms import MoonForm, RoundBonusForm, RoundForm, SettingsForm, parse_wishlist
from .models import Allocation, Application, ApplicationWish, DistributionSettings, Moon, Round, RoundBonus
from .providers import alliance_corporations, eligible_corporations_for, sync_moons_from_corptools
from .rarity import apply_moon_data, fill_missing_regions, parse_paste, rarities_from_moonmining
from .tasks import distribute_round

logger = logging.getLogger(__name__)


def _ctx(request, **extra) -> dict:
    """Common template context (version, officer flag, length of the application phase)."""
    return {
        "app_version": __version__,
        "is_officer": request.user.has_perm("moondistribution.mining_officer"),
        "application_days": DistributionSettings.get_solo().application_days,
        **extra,
    }


def ids_from_csv(value: str) -> list:
    """'12,15,99' → [12, 15, 99] – large selections are sent as ONE field to stay below
    Django's DATA_UPLOAD_MAX_NUMBER_FIELDS (1000) even with thousands of moons."""
    return [int(v) for v in (value or "").split(",") if v.strip().isdigit()]


def round_form_data(post):
    """POST data for RoundForm with the moon selection taken from the single 'moon_ids' field."""
    data = post.copy()
    data.setlist("moons", [str(i) for i in ids_from_csv(post.get("moon_ids", ""))])
    return data


def wishlist_from_post(post) -> dict:
    """{'prio_<moon id>': '<priority>'} from the single 'wishlist' field ('12:1,15:2,…')."""
    result = {}
    for pair in (post.get("wishlist") or "").split(","):
        moon_id, _sep, prio = pair.partition(":")
        if moon_id.strip().isdigit():
            result[f"prio_{int(moon_id)}"] = prio.strip()
    return result


def group_by_region(items, moon_of=lambda item: item) -> list:
    """Group moons (or rows containing a moon) by region for the region tabs.

    Returns [{'region': 'Esoteria', 'slug': 'region-esoteria', 'items': [...]}, ...] sorted by region,
    moons without a known region last under 'Other'.
    """
    groups = {}
    for item in items:
        region = moon_of(item).region_name or ""
        groups.setdefault(region, []).append(item)
    ordered = sorted(groups, key=lambda r: (r == "", r))
    return [
        {"region": r or _("Other"), "slug": "region-" + (slugify(r) or "other"), "items": groups[r]}
        for r in ordered
    ]


def _visible_rounds(request):
    """Officers see all rounds, everyone else only published ones (not drafts)."""
    rounds = Round.objects.annotate(n_apps=Count("applications", distinct=True), n_moons=Count("moons", distinct=True))
    if request.user.has_perm("moondistribution.mining_officer"):
        return rounds
    return rounds.exclude(status=Round.Status.DRAFT)


# ---------------------------------------------------------------------------
# Member views
# ---------------------------------------------------------------------------

@check_access()
def index(request):
    """Overview: open rounds, past rounds and the corps the user may apply for."""
    rounds = _visible_rounds(request)
    eligible = list(eligible_corporations_for(request.user, include_officer=False))
    open_rounds = [r for r in rounds if r.status == Round.Status.OPEN]
    my_apps = {
        (a.round_id, a.corporation.corporation_id): a
        for a in Application.objects.filter(
            round__in=open_rounds, corporation__in=eligible,
        ).select_related("corporation")
    }
    open_info = [
        {
            "round": r,
            "corps": [{"corp": c, "application": my_apps.get((r.pk, c.corporation_id))} for c in eligible],
        }
        for r in open_rounds
    ]
    settings = DistributionSettings.get_solo()
    return render(request, "moondistribution/index.html", _ctx(
        request,
        open_info=open_info,
        past_rounds=[r for r in rounds if r.status != Round.Status.OPEN],
        eligible=eligible,
        alliance_corps=alliance_corporations() if request.user.has_perm("moondistribution.mining_officer") else [],
        no_alliance=settings.alliance_id is None,
    ))


@check_access()
def round_detail(request, round_id: int):
    """Details of a round: moon pool, results (when distributed), own/all applications."""
    round_obj = get_object_or_404(_visible_rounds(request), pk=round_id)
    is_officer = request.user.has_perm("moondistribution.mining_officer")
    eligible = list(eligible_corporations_for(request.user))

    allocations = list(round_obj.allocations.select_related("moon", "corporation"))
    moon_owner = {a.moon_id: a for a in allocations}
    # Officers: how many corps have each moon on their wishlist (live during the application week)
    wish_counts = {}
    if is_officer:
        wish_counts = dict(
            ApplicationWish.objects.filter(application__round=round_obj)
            .values_list("moon_id").annotate(n=Count("id"))
        )
    moons = [
        {"moon": m, "allocation": moon_owner.get(m.pk), "wishes": wish_counts.get(m.pk, 0)}
        for m in round_obj.moons.select_related("owner_corporation")
    ]
    if is_officer:
        moons.sort(key=lambda row: (-row["wishes"], row["moon"].name))

    if is_officer:
        applications = application_summary(round_obj)
    else:
        applications = [a for a in application_summary(round_obj) if a.corporation in eligible]

    return render(request, "moondistribution/round_detail.html", _ctx(
        request,
        round=round_obj,
        moons=moons,
        moon_regions=group_by_region(moons, lambda row: row["moon"]),
        scores=list(round_obj.scores.select_related("corporation")) if round_obj.status == Round.Status.DONE else [],
        allocations=allocations,
        applications=applications,
        eligible=eligible,
        snapshot=round_obj.settings_snapshot or {},
        bonuses=list(round_obj.bonuses.select_related("corporation", "created_by__profile__main_character")),
        bonus_form=RoundBonusForm(corporations=alliance_corporations()) if is_officer else None,
    ))


@check_access()
def apply(request, round_id: int, corporation_id: int):
    """Create or change the application (moon wishlist) of a corp for an open round."""
    round_obj = get_object_or_404(Round, pk=round_id)
    corporation = get_object_or_404(eligible_corporations_for(request.user), corporation_id=corporation_id)
    if not round_obj.is_open:
        messages.error(request, _("Applications for this round are not open."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)

    settings = DistributionSettings.get_solo()
    moons_qs = round_obj.moons.select_related("owner_corporation")
    if settings.exclude_r64:
        moons_qs = moons_qs.exclude(rarity=Moon.Rarity.R64)
    moons = list(moons_qs)
    application = Application.objects.filter(round=round_obj, corporation=corporation).first()
    current = {w.moon_id: w.priority for w in application.wishes.all()} if application else {}
    comment = application.comment if application else ""

    if request.method == "POST":
        posted = wishlist_from_post(request.POST)
        wishes, errors = parse_wishlist(posted, moons, settings.max_wishes)
        comment = (request.POST.get("comment") or "").strip()[:2000]
        if errors:
            for err in errors:
                messages.error(request, err)
            current = {m.pk: posted.get(f"prio_{m.pk}", "") for m in moons}
        else:
            with transaction.atomic():
                if application is None:
                    application = Application.objects.create(
                        round=round_obj, corporation=corporation, submitted_by=request.user, comment=comment,
                    )
                else:
                    application.comment = comment
                    application.submitted_by = request.user
                    application.save()
                    application.wishes.all().delete()
                ApplicationWish.objects.bulk_create([
                    ApplicationWish(application=application, moon=moon, priority=prio) for prio, moon in wishes
                ])
            messages.success(request, _("Application for %(corp)s saved.") % {"corp": corporation.corporation_name})
            return redirect("moondistribution:round_detail", round_id=round_obj.pk)

    rows = [{"moon": m, "priority": current.get(m.pk, "")} for m in moons]
    rows.sort(key=lambda r: (r["priority"] == "" or r["priority"] is None, str(r["priority"]).zfill(3), r["moon"].name))
    return render(request, "moondistribution/apply.html", _ctx(
        request, round=round_obj, corporation=corporation, rows=rows, comment=comment,
        application=application, max_wishes=settings.max_wishes,
        row_regions=group_by_region(rows, lambda row: row["moon"]),
    ))


@check_access()
@require_POST
def withdraw(request, round_id: int, corporation_id: int):
    """Withdraw the application of a corp while the round is still open."""
    round_obj = get_object_or_404(Round, pk=round_id)
    corporation = get_object_or_404(eligible_corporations_for(request.user), corporation_id=corporation_id)
    if not round_obj.is_open:
        messages.error(request, _("The round is no longer open."))
    else:
        Application.objects.filter(round=round_obj, corporation=corporation).delete()
        messages.info(request, _("Application withdrawn."))
    return redirect("moondistribution:round_detail", round_id=round_obj.pk)


# ---------------------------------------------------------------------------
# Officer views – rounds
# ---------------------------------------------------------------------------

def _moon_checkbox_regions(form) -> list:
    """The moon checkboxes of the round form grouped by region (one tab per region)."""
    moons = {str(m.pk): m for m in form.fields["moons"].queryset}
    boxes = [box for box in form["moons"] if str(box.data["value"]) in moons]
    return group_by_region(boxes, lambda box: moons[str(box.data["value"])])


@officer_required
def round_create(request):
    """Create a new round (draft). The application week starts only when the round is opened."""
    settings = DistributionSettings.get_solo()
    if request.method == "POST":
        form = RoundForm(round_form_data(request.POST))
        if form.is_valid():
            round_obj = form.save(commit=False)
            round_obj.created_by = request.user
            round_obj.save()
            form.save_m2m()
            messages.success(request, _("Round created as draft. Open it when everything is set."))
            return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    else:
        # Activity window default: the 6 months before the (expected) end of the application phase
        expected_end = timezone.now() + timedelta(days=settings.application_days)
        ev_start, ev_end = Round.default_evaluation_window(expected_end)
        form = RoundForm(initial={"evaluation_start": ev_start, "evaluation_end": ev_end})
    return render(request, "moondistribution/round_form.html", _ctx(
        request, form=form, round=None, moon_regions=_moon_checkbox_regions(form),
    ))


@officer_required
def round_edit(request, round_id: int):
    """Edit a round – only possible before it is distributed."""
    round_obj = get_object_or_404(Round, pk=round_id)
    if round_obj.status == Round.Status.DONE:
        messages.error(request, _("A distributed round can't be edited anymore."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    form = RoundForm(round_form_data(request.POST) if request.method == "POST" else None, instance=round_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Remove wishes for moons that are no longer in the pool
        ApplicationWish.objects.filter(application__round=round_obj).exclude(moon__in=round_obj.moons.all()).delete()
        messages.success(request, _("Round saved."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    return render(request, "moondistribution/round_form.html", _ctx(
        request, form=form, round=round_obj, moon_regions=_moon_checkbox_regions(form),
    ))


@officer_required
@require_POST
def round_open(request, round_id: int):
    """Open a draft: applications run for the configured days (default 1 week), then it is distributed once."""
    round_obj = get_object_or_404(Round, pk=round_id, status=Round.Status.DRAFT)
    if not round_obj.moons.exists():
        messages.error(request, _("Add at least one moon to the round first."))
    else:
        now = timezone.now()
        round_obj.application_start = now
        round_obj.application_end = now + timedelta(days=DistributionSettings.get_solo().application_days)
        round_obj.status = Round.Status.OPEN
        round_obj.save(update_fields=["application_start", "application_end", "status"])
        messages.success(request, _("Round is open for applications until %(end)s EVE time – then it is distributed automatically.") % {
            "end": round_obj.application_end.strftime("%d.%m.%Y %H:%M"),
        })
    return redirect("moondistribution:round_detail", round_id=round_obj.pk)


@officer_required
@require_POST
def round_close_now(request, round_id: int):
    """End the application phase immediately and start the automatic distribution."""
    round_obj = get_object_or_404(Round, pk=round_id, status=Round.Status.OPEN)
    round_obj.application_end = timezone.now()
    round_obj.status = Round.Status.CLOSED
    round_obj.save(update_fields=["application_end", "status"])
    distribute_round.delay(round_obj.pk)
    messages.success(request, _("Applications closed – distribution is running, reload in a moment."))
    return redirect("moondistribution:round_detail", round_id=round_obj.pk)


@officer_required
@require_POST
def round_redistribute(request, round_id: int):
    """Re-run evaluation and distribution (e.g. after zKillboard was down)."""
    round_obj = get_object_or_404(Round, pk=round_id, status__in=[Round.Status.CLOSED, Round.Status.DONE])
    Round.objects.filter(pk=round_obj.pk).update(status=Round.Status.CLOSED, last_error="")
    distribute_round.delay(round_obj.pk)
    messages.success(request, _("Distribution restarted – reload in a moment."))
    return redirect("moondistribution:round_detail", round_id=round_obj.pk)


@officer_required
@require_POST
def round_delete(request, round_id: int):
    """Delete a round that is still a draft."""
    round_obj = get_object_or_404(Round, pk=round_id, status=Round.Status.DRAFT)
    round_obj.delete()
    messages.info(request, _("Draft deleted."))
    return redirect("moondistribution:index")


@officer_required
@require_POST
def bonus_save(request, round_id: int):
    """Add or replace the manual bonus of a corp (only before the round is distributed)."""
    round_obj = get_object_or_404(Round, pk=round_id)
    if round_obj.status == Round.Status.DONE:
        messages.error(request, _("The round is already distributed – bonuses can't be changed anymore."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    existing = RoundBonus.objects.filter(round=round_obj, corporation_id=request.POST.get("corporation")).first()
    form = RoundBonusForm(request.POST, instance=existing, corporations=alliance_corporations())
    if form.is_valid():
        bonus = form.save(commit=False)
        bonus.round = round_obj
        bonus.created_by = request.user
        bonus.save()
        messages.success(request, _("Bonus saved."))
    else:
        for errors in form.errors.values():
            for err in errors:
                messages.error(request, err)
    return redirect("moondistribution:round_detail", round_id=round_obj.pk)


@officer_required
@require_POST
def bonus_delete(request, round_id: int, bonus_id: int):
    """Remove a manual bonus (only before the round is distributed)."""
    bonus = get_object_or_404(RoundBonus, pk=bonus_id, round_id=round_id)
    if bonus.round.status == Round.Status.DONE:
        messages.error(request, _("The round is already distributed – bonuses can't be changed anymore."))
    else:
        bonus.delete()
        messages.info(request, _("Bonus removed."))
    return redirect("moondistribution:round_detail", round_id=round_id)


@officer_required
def officer_apply(request, round_id: int):
    """Officer shortcut: pick any alliance corp to apply for it."""
    corp_id = request.GET.get("corporation_id")
    if corp_id and alliance_corporations().filter(corporation_id=corp_id).exists():
        return redirect("moondistribution:apply", round_id=round_id, corporation_id=corp_id)
    raise Http404


# ---------------------------------------------------------------------------
# Officer views – moons & settings
# ---------------------------------------------------------------------------

@officer_required
def moons(request):
    """List of all moons with filter (rarity / missing rarity / search), bulk edit and rarity import."""
    rarity_filter = request.GET.get("rarity", "")
    region_filter = request.GET.get("region", "")
    search = (request.GET.get("q") or "").strip()
    moon_list = Moon.objects.select_related("owner_corporation").prefetch_related(
        Prefetch(
            "allocations",
            queryset=Allocation.objects.select_related("corporation", "round").order_by("-round__created_at"),
        )
    )
    if rarity_filter == "missing":
        moon_list = moon_list.filter(rarity="")
    elif rarity_filter:
        moon_list = moon_list.filter(rarity=rarity_filter)
    if region_filter == "other":
        moon_list = moon_list.filter(region_name="")
    elif region_filter:
        moon_list = moon_list.filter(region_name=region_filter)
    if search:
        moon_list = moon_list.filter(Q(name__icontains=search) | Q(system_name__icontains=search))
    counts = {r or "missing": n for r, n in Moon.objects.values_list("rarity").annotate(n=Count("id"))}
    regions = list(Moon.objects.values_list("region_name").annotate(n=Count("id")).order_by("region_name"))
    return render(request, "moondistribution/moons.html", _ctx(
        request, moons=moon_list, rarity_filter=rarity_filter, search=search, counts=counts,
        region_filter=region_filter, regions=regions,
        rarity_choices=[c for c in Moon.Rarity.choices if c[0]],
        moonmining_installed=apps.is_installed("moonmining"),
    ))


@officer_required
@require_POST
def moon_bulk(request):
    """Set rarity / active flag for all ticked moons at once."""
    ids = ids_from_csv(request.POST.get("moon_ids_csv", "")) or [
        int(i) for i in request.POST.getlist("moon_ids") if i.isdigit()
    ]
    action = request.POST.get("action", "")
    qs = Moon.objects.filter(pk__in=ids)
    if not ids:
        messages.error(request, _("No moons selected."))
    elif action in {c[0] for c in Moon.Rarity.choices}:
        n = qs.update(rarity=action)
        messages.success(request, _("Rarity set for %(n)s moons.") % {"n": n})
    elif action in ("activate", "deactivate"):
        n = qs.update(is_active=action == "activate")
        messages.success(request, _("%(n)s moons updated.") % {"n": n})
    else:
        messages.error(request, _("Unknown action."))
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("moondistribution:moons")


@officer_required
@require_POST
def moon_rarity_import(request):
    """Add / update moons from pasted sheet rows, moon scans or a 'moon; R32' list, or from aa-moonmining.

    Sets rarity, ore composition and note. With 'create' ticked, missing moons are created.
    """
    overwrite = request.POST.get("overwrite") == "on"
    create_missing = request.POST.get("create") == "on"
    if request.POST.get("source") == "moonmining":
        entries = rarities_from_moonmining()
        if not entries:
            messages.error(request, _("aa-moonmining is not installed or has no scanned moons."))
            return redirect("moondistribution:moons")
    else:
        entries = parse_paste(request.POST.get("paste", ""))
        if not entries:
            messages.error(request, _("No moons recognised in the pasted text."))
            return redirect("moondistribution:moons")
    stats = apply_moon_data(entries, overwrite=overwrite, create_missing=create_missing)
    messages.success(request, _(
        "%(found)s moons recognised: %(created)s created, %(updated)s updated, %(unchanged)s unchanged, "
        "%(unknown)s not in the moon list (tick 'Create missing moons' to add them)."
    ) % {"found": len(entries), **stats})
    return redirect("moondistribution:moons")


@officer_required
def moon_edit(request, moon_id: int | None = None):
    """Add a moon manually or edit rarity/notes/active of an existing one."""
    moon = get_object_or_404(Moon, pk=moon_id) if moon_id else None
    form = MoonForm(request.POST or None, instance=moon)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Moon saved."))
        return redirect("moondistribution:moons")
    return render(request, "moondistribution/moon_form.html", _ctx(request, form=form, moon=moon))


@officer_required
@require_POST
def moon_sync(request):
    """Import refineries from Corptools right now (instead of waiting for the daily task)."""
    try:
        stats = sync_moons_from_corptools()
        messages.success(request, _(
            "Import done: %(created)s new, %(updated)s updated, %(skipped)s skipped, "
            "%(rarity_from_moonmining)s rarities taken from aa-moonmining, %(regions)s regions set."
        ) % stats)
    except ValueError as exc:
        fill_missing_regions()
        messages.error(request, str(exc))
    return redirect("moondistribution:moons")


@officer_required
def settings_view(request):
    """Settings: alliance, weights and limits."""
    settings = DistributionSettings.get_solo()
    form = SettingsForm(request.POST or None, instance=settings)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Settings saved."))
        return redirect("moondistribution:settings")
    alliance_corp_count = alliance_corporations().count()
    alliance = None
    if settings.alliance_id:
        corp = EveCorporationInfo.objects.filter(alliance__alliance_id=settings.alliance_id).select_related("alliance").first()
        alliance = corp.alliance if corp else None
    return render(request, "moondistribution/settings.html", _ctx(
        request, form=form, alliance=alliance, alliance_corp_count=alliance_corp_count,
    ))
