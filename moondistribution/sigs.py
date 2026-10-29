"""SIGs (AA groups) that reserve moons for a round before the distribution."""

from django.contrib.auth.models import User
from django.db.models import Q

from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from .models import Sig, SigClaim

logger = get_extension_logger(__name__)


def sigs_led_by(user):
    """Active SIGs whose AA group the user leads (as group leader or via a leader group)."""
    if not user.is_authenticated:
        return Sig.objects.none()
    # compare by primary key – AA's group_leaders points to its own User proxy model
    return Sig.objects.filter(is_active=True).filter(
        Q(group__authgroup__group_leaders__pk=user.pk)
        | Q(group__authgroup__group_leader_groups__pk__in=list(user.groups.values_list("pk", flat=True)))
    ).distinct()


def reserved_moon_ids(round_obj) -> set:
    """Moons of the round reserved for a SIG (approved claims) – they are not distributed."""
    return set(
        SigClaim.objects.filter(round=round_obj, status=SigClaim.Status.APPROVED).values_list("moon_id", flat=True)
    )


def claimed_moon_ids(round_obj, exclude_sig=None) -> dict:
    """{moon_id: claim} of all pending/approved claims of the round (optionally without one SIG's own claims)."""
    qs = SigClaim.objects.filter(round=round_obj).exclude(status=SigClaim.Status.REJECTED).select_related("sig")
    if exclude_sig is not None:
        qs = qs.exclude(sig=exclude_sig)
    return {c.moon_id: c for c in qs}


def notify_officers(title: str, message: str) -> None:
    """AA notification to every Mining Officer (permission mining_officer, superusers excluded)."""
    officers = User.objects.filter(
        Q(user_permissions__codename="mining_officer", user_permissions__content_type__app_label="moondistribution")
        | Q(groups__permissions__codename="mining_officer",
            groups__permissions__content_type__app_label="moondistribution")
    ).distinct()
    for officer in officers:
        try:
            notify(officer, title, message, "info")
        except Exception:  # notifications must never break the request
            logger.exception("Could not notify officer %s", officer.pk)


def notify_user(user, title: str, message: str, level: str = "info") -> None:
    """AA notification to one user, errors are only logged."""
    if user is None:
        return
    try:
        notify(user, title, message, level)
    except Exception:
        logger.exception("Could not notify user %s", user.pk)
