"""URL configuration for the Otahque project."""
from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Otahque administration'
admin.site.site_title = 'Otahque admin'
# Staff sign in through allauth's page, with its limits and
# two-factor sign-in; the admin's own form is never used.
admin.site.login = secure_admin_login(admin.site.login)

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),
    path('', include('events.urls')),
    path('', include('registrations.urls')),
]
