"""Access decorators (same approach as aa-miningtax: PermissionDenied instead of redirect loops)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def check_access(perm: str = "moondistribution.basic_access"):
    """Require login and the given permission, otherwise raise 403."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not request.user.has_perm(perm):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


# Shortcut for officer-only views
officer_required = check_access("moondistribution.mining_officer")
