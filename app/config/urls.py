"""
URL configuration for the Otahque project.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Otahque administration'
admin.site.site_title = 'Otahque admin'

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('', include('events.urls')),
]
