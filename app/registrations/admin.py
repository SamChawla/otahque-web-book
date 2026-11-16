from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ['event', 'member', 'status',
                    'registered_at', 'cancelled_at']
    list_filter = ['status', 'event']
    search_fields = ['member__email', 'event__title']
    list_select_related = ['event', 'member']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
