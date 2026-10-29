"""Celery tasks: moon import and automatic round processing."""

import logging

from celery import shared_task

from django.utils import timezone

from .distribution import run_distribution
from .models import Round
from .providers import sync_moons_from_corptools

logger = logging.getLogger(__name__)


@shared_task
def sync_moons():
    """Daily: import/update the alliance refineries from Corptools as moons."""
    try:
        return sync_moons_from_corptools()
    except ValueError as exc:
        logger.warning("Moon sync skipped: %s", exc)
        return None


@shared_task
def distribute_round(round_id: int):
    """Evaluate and distribute one round; errors are stored on the round and retried by process_rounds."""
    round_obj = Round.objects.get(pk=round_id)
    try:
        run_distribution(round_obj)
    except Exception as exc:
        logger.exception("Distribution of round %s failed", round_id)
        Round.objects.filter(pk=round_id).update(status=Round.Status.CLOSED, last_error=str(exc)[:2000])


@shared_task
def process_rounds():
    """Hourly: close rounds whose application phase ended and distribute them automatically."""
    now = timezone.now()
    due = Round.objects.filter(
        status__in=[Round.Status.OPEN, Round.Status.CLOSED], application_end__lte=now,
    )
    for round_obj in due:
        Round.objects.filter(pk=round_obj.pk).update(status=Round.Status.CLOSED)
        distribute_round.delay(round_obj.pk)
