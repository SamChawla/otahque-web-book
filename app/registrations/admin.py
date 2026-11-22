"""Admin pages for registrations."""
from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    """Registrations as history: view only."""

    list_display = ['event', 'member', 'status',
                    'registered_at', 'cancelled_at']
    list_filter = ['status', 'event']
    search_fields = ['member__email', 'event__title']
    list_select_related = ['event', 'member']

    def has_add_permission(self, request):
        """Members register on the site, not here."""
        return False

    def has_change_permission(self, request, obj=None):
        """Registrations are history: never edited."""
        return False

    def has_delete_permission(self, request, obj=None):
        """History is never deleted."""
        return False
