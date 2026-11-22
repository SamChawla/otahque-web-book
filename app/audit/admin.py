"""Admin pages for the audit trail."""
from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """The audit trail, read-only."""

    list_display = ['created_at', 'actor', 'action',
                    'outcome', 'target_type', 'target_id']
    list_filter = ['outcome', 'action']
    list_select_related = ['actor']
    search_fields = ['actor__email']

    def has_add_permission(self, request):
        """Only Otahque's own code adds audit rows."""
        return False

    def has_change_permission(self, request, obj=None):
        """Audit rows are never edited."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Audit rows are never deleted."""
        return False
