from django.contrib import admin
from django.contrib.admin.models import LogEntry

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'display_name', 'is_staff',
                    'is_active']
    list_filter = ['is_staff', 'is_active']
    search_fields = ['email', 'display_name']
    ordering = ['email']
    fields = ['email', 'display_name', 'is_active',
              'is_staff', 'groups', 'user_permissions',
              'last_login', 'date_joined']
    readonly_fields = ['last_login', 'date_joined']
    filter_horizontal = ['groups', 'user_permissions']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ['action_time', 'user', 'content_type',
                    'object_repr', 'action_flag', 'message']
    list_filter = ['action_flag', 'content_type', 'user']
    search_fields = ['object_repr', 'change_message']
    list_select_related = ['user', 'content_type']

    @admin.display(description='Message')
    def message(self, entry):
        return entry.get_change_message()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
