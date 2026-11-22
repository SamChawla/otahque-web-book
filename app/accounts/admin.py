"""Admin pages for members and the admin's log."""
from django import forms
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError

from audit.models import AuditEvent, record
from events.models import ORGANIZERS

from .models import User


class UserForm(forms.ModelForm):
    """The admin's member form, with its group rule.

    Only a superuser may change groups other than
    Organizers, so no administrator can promote anyone.
    """

    def clean_groups(self):
        """Keep every group but Organizers as it was."""
        groups = self.cleaned_data['groups']
        if self.request.user.is_superuser:
            return groups
        kept = self.instance.groups.exclude(name=ORGANIZERS)
        asked = groups.exclude(name=ORGANIZERS)
        if set(kept) != set(asked):
            raise ValidationError(
                'Only the Organizers group can be changed '
                'here.'
            )
        return groups


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Members' details and access; never passwords."""

    form = UserForm
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

    def get_readonly_fields(self, request, obj=None):
        """Staff flag and permissions: superusers only."""
        if request.user.is_superuser:
            return self.readonly_fields
        return [*self.readonly_fields, 'is_staff',
                'user_permissions']

    def get_form(self, request, obj=None, **kwargs):
        """Give the form the request, for its group rule."""
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form

    def has_add_permission(self, request):
        """Members sign up on the site, not here."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Deactivate members instead of deleting them."""
        return False

    def save_related(self, request, form, formsets, change):
        """Record joining or leaving Organizers."""
        member = form.instance
        organizers = member.groups.filter(name=ORGANIZERS)
        before = organizers.exists()
        super().save_related(request, form, formsets, change)
        after = organizers.exists()
        if before != after:
            action = (AuditEvent.Action.JOIN_ORGANIZERS
                      if after else
                      AuditEvent.Action.LEAVE_ORGANIZERS)
            record(request.user, action, member)


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    """The admin's change log, read-only."""

    list_display = ['action_time', 'user', 'content_type',
                    'object_repr', 'action_flag', 'message']
    list_filter = ['action_flag', 'content_type', 'user']
    search_fields = ['object_repr', 'change_message']
    list_select_related = ['user', 'content_type']

    @admin.display(description='Message')
    def message(self, entry):
        """Return the change message in plain words."""
        return entry.get_change_message()

    def has_add_permission(self, request):
        """Only the admin itself writes the log."""
        return False

    def has_change_permission(self, request, obj=None):
        """Log entries are never edited."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Log entries are never deleted."""
        return False
