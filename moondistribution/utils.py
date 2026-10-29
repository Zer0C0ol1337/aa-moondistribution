"""Small shared helpers (kept separate to avoid import cycles between hooks, views and tasks)."""

from django.core.cache import cache

OPEN_ROUNDS_CACHE_KEY = "moondistribution_open_rounds"


def open_rounds_count() -> int:
    """Number of open rounds for the menu badge – cached 5 minutes, reset whenever a round status changes."""
    from .models import Round

    return cache.get_or_set(
        OPEN_ROUNDS_CACHE_KEY, lambda: Round.objects.filter(status=Round.Status.OPEN).count(), 300,
    )


def reset_open_rounds_count() -> None:
    """Drop the cached badge count (called when a round is opened, closed or deleted)."""
    cache.delete(OPEN_ROUNDS_CACHE_KEY)
