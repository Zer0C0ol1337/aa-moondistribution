"""Celery tasks: moon import and the one-time automatic distribution of a round."""


from celery import shared_task

from django.contrib.auth.models import User
from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger
from allianceauth.notifications import notify
from allianceauth.services.tasks import QueueOnce

from .distribution import run_distribution
from .models import Round
from .providers import sync_moons_from_corptools
from .rarity import apply_moon_data, fill_missing_regions, parse_paste, rarities_from_moonmining
from .utils import reset_open_rounds_count

logger = get_extension_logger(__name__)


def _notify_user(user_id, title: str, message: str, level: str = "info") -> None:
    """Send an AA notification to the officer who started a task (if any)."""
    if not user_id:
        return
    user = User.objects.filter(pk=user_id).first()
    if user:
        notify(user, title, message, level)


@shared_task(base=QueueOnce, once={"graceful": True})
def sync_moons(user_id: int | None = None):
    """Daily (and on button click): import/update the alliance refineries from Corptools as moons."""
    try:
        stats = sync_moons_from_corptools()
    except ValueError as exc:
        logger.warning("Moon sync skipped: %s", exc)
        fill_missing_regions()  # manually added moons still get their region
        _notify_user(user_id, "Moon Distribution: import from Corptools", str(exc), "warning")
        return None
    _notify_user(
        user_id, "Moon Distribution: import from Corptools",
        "{created} new, {updated} updated, {skipped} skipped, {rarity_from_moonmining} rarities from "
        "aa-moonmining, {regions} regions set.".format(**stats),
        "success",
    )
    return stats


@shared_task(base=QueueOnce, once={"graceful": True, "keys": ["user_id"]})
def import_moon_data(paste: str, overwrite: bool, create_missing: bool, user_id: int | None = None,
                     source: str = "paste"):
    """Import pasted sheet rows / moon scans (or aa-moonmining data) and notify the officer with the result."""
    entries = rarities_from_moonmining() if source == "moonmining" else parse_paste(paste)
    if not entries:
        _notify_user(user_id, "Moon Distribution: moon import", "No moons recognised.", "warning")
        return None
    stats = apply_moon_data(entries, overwrite=overwrite, create_missing=create_missing)
    _notify_user(
        user_id, "Moon Distribution: moon import",
        "{found} moons recognised: {created} created, {updated} updated, {unchanged} unchanged, "
        "{unknown} not in the moon list, {owners_not_in_aa} owner corps not known in AA (kept as text).".format(
            found=len(entries), **stats,
        ),
        "success",
    )
    return stats


@shared_task(base=QueueOnce, once={"keys": ["round_id"], "graceful": True})
def distribute_round(round_id: int):
    """Evaluate and distribute one round.

    QueueOnce makes sure the same round is never processed twice at the same time.
    Only rounds in status 'closed' are processed. Errors are stored on the round
    and are NOT retried automatically – the officer can use 'Re-run distribution'.
    """
    round_obj = Round.objects.filter(pk=round_id, status=Round.Status.CLOSED).first()
    if round_obj is None:
        logger.info("Round %s is not waiting for distribution – skipped", round_id)
        return
    try:
        run_distribution(round_obj)
    except Exception as exc:
        logger.exception("Distribution of round %s failed", round_id)
        Round.objects.filter(pk=round_id).update(last_error=str(exc)[:2000])


@shared_task(base=QueueOnce, once={"graceful": True})
def process_rounds():
    """Every few minutes: close open rounds whose week is over and distribute them – once."""
    due = Round.objects.filter(status=Round.Status.OPEN, application_end__lte=timezone.now())
    for round_obj in due:
        # Atomic status switch: only the call that actually closes the round queues the distribution
        if Round.objects.filter(pk=round_obj.pk, status=Round.Status.OPEN).update(status=Round.Status.CLOSED):
            reset_open_rounds_count()
            distribute_round.delay(round_obj.pk)
