
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import AnonymousUser
from .models import Tenant

class TenantAttachMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.tenant = None
        user = getattr(request, 'user', None)
        if user and not isinstance(user, AnonymousUser) and user.is_authenticated:
            tenant, created = Tenant.objects.get_or_create(user=user, defaults={'name': f'Tenant for {user.username}'})
            request.tenant = tenant
