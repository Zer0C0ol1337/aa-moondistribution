"""Views of Moon Distribution."""

import logging
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from allianceauth.eveonline.models import EveCorporationInfo

from . import __version__
from .decorators import check_access, officer_required
from .distribution import application_summary
from .forms import MoonForm, RoundForm, SettingsForm, parse_wishlist
from .models import Allocation, Application, ApplicationWish, DistributionSettings, Moon, Round
from .providers import alliance_corporations, eligible_corporations_for, sync_moons_from_corptools
from .tasks import distribute_round

logger = logging.getLogger(__name__)


def _ctx(request, **extra) -> dict:
    """Common template context (version, officer flag)."""
    return {
        "app_version": __version__,
        "is_officer": request.user.has_perm("moondistribution.mining_officer"),
        **extra,
    }


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
    moons = [{"moon": m, "allocation": moon_owner.get(m.pk)} for m in round_obj.moons.select_related("owner_corporation")]

    if is_officer:
        applications = application_summary(round_obj)
    else:
        applications = [a for a in application_summary(round_obj) if a.corporation in eligible]

    return render(request, "moondistribution/round_detail.html", _ctx(
        request,
        round=round_obj,
        moons=moons,
        scores=list(round_obj.scores.select_related("corporation")) if round_obj.status == Round.Status.DONE else [],
        allocations=allocations,
        applications=applications,
        eligible=eligible,
        snapshot=round_obj.settings_snapshot or {},
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
    moons = list(round_obj.moons.select_related("owner_corporation"))
    application = Application.objects.filter(round=round_obj, corporation=corporation).first()
    current = {w.moon_id: w.priority for w in application.wishes.all()} if application else {}
    comment = application.comment if application else ""

    if request.method == "POST":
        wishes, errors = parse_wishlist(request.POST, moons, settings.max_wishes)
        comment = (request.POST.get("comment") or "").strip()[:2000]
        if errors:
            for err in errors:
                messages.error(request, err)
            current = {m.pk: request.POST.get(f"prio_{m.pk}", "") for m in moons}
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

@officer_required
def round_create(request):
    """Create a new round (status draft). Evaluation window defaults to the 6 months before the end."""
    if request.method == "POST":
        form = RoundForm(request.POST)
        if form.is_valid():
            round_obj = form.save(commit=False)
            round_obj.created_by = request.user
            round_obj.save()
            form.save_m2m()
            messages.success(request, _("Round created as draft. Open it when everything is set."))
            return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    else:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        end = now + timedelta(days=14)
        ev_start, ev_end = Round.default_evaluation_window(end)
        form = RoundForm(initial={
            "application_start": now, "application_end": end,
            "evaluation_start": ev_start, "evaluation_end": ev_end,
        })
    return render(request, "moondistribution/round_form.html", _ctx(request, form=form, round=None))


@officer_required
def round_edit(request, round_id: int):
    """Edit a round – only possible before it is distributed."""
    round_obj = get_object_or_404(Round, pk=round_id)
    if round_obj.status == Round.Status.DONE:
        messages.error(request, _("A distributed round can't be edited anymore."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    form = RoundForm(request.POST or None, instance=round_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Remove wishes for moons that are no longer in the pool
        ApplicationWish.objects.filter(application__round=round_obj).exclude(moon__in=round_obj.moons.all()).delete()
        messages.success(request, _("Round saved."))
        return redirect("moondistribution:round_detail", round_id=round_obj.pk)
    return render(request, "moondistribution/round_form.html", _ctx(request, form=form, round=round_obj))


@officer_required
@require_POST
def round_open(request, round_id: int):
    """Publish a draft: corps can apply between application start and end."""
    round_obj = get_object_or_404(Round, pk=round_id, status=Round.Status.DRAFT)
    if not round_obj.moons.exists():
        messages.error(request, _("Add at least one moon to the round first."))
    else:
        round_obj.status = Round.Status.OPEN
        round_obj.save(update_fields=["status"])
        messages.success(request, _("Round is open for applications."))
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
    """List of all moons with import status."""
    moon_list = Moon.objects.select_related("owner_corporation").prefetch_related(
        Prefetch(
            "allocations",
            queryset=Allocation.objects.select_related("corporation", "round").order_by("-round__application_end"),
        )
    )
    return render(request, "moondistribution/moons.html", _ctx(request, moons=moon_list))


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
        messages.success(request, _("Import done: %(created)s new, %(updated)s updated, %(skipped)s skipped.") % stats)
    except ValueError as exc:
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
