"""Celery tasks: moon import and the one-time automatic distribution of a round."""

import logging

from celery import shared_task

from django.utils import timezone

from allianceauth.services.tasks import QueueOnce

from .distribution import run_distribution
from .models import Round
from .providers import sync_moons_from_corptools

logger = logging.getLogger(__name__)


@shared_task(base=QueueOnce, once={"graceful": True})
def sync_moons():
    """Daily: import/update the alliance refineries from Corptools as moons."""
    try:
        return sync_moons_from_corptools()
    except ValueError as exc:
        logger.warning("Moon sync skipped: %s", exc)
        return None


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
            distribute_round.delay(round_obj.pk)
