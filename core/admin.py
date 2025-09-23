
from django.contrib import admin
from .models import Tenant, Person, Indemnitor, Reference

admin.site.register(Tenant)
admin.site.register(Person)
admin.site.register(Indemnitor)
admin.site.register(Reference)
