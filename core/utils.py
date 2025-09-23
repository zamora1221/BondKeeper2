# core/utils.py
from django.http import Http404
from .models import Tenant

def get_current_tenant(request, required=True):
    """
    Tries a few ways to find a tenant for the current request.
    Falls back to the first Tenant row if present.
    """
    u = getattr(request, "user", None)

    # 1) direct attr (works if you *do* have a custom user with .tenant someday)
    if u is not None:
        t = getattr(u, "tenant", None)
        if t:
            return t

    # 2) simple fallback: first tenant in DB (common single-tenant setup)
    t = Tenant.objects.first()
    if t:
        return t

    if required:
        # No tenant exists at all — guide the admin to create one
        raise Http404("No Tenant configured yet. Create one in the admin (core.Tenant).")
    return None
