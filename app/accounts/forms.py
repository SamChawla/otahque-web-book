"""The accounts app's forms."""
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal.auth import TOTP
from django import forms
from phonenumber_field.formfields import PhoneNumberField

from events.forms import ZONE_CHOICES

from .models import Profile

NAME_HELP = ('Shown to other members, and on the pages of '
             'events you organize.')
PHONE_HELP = ('Shown only to the organizers of events you '
              'register for. Without +, read as an Indian '
              'number.')


class SignupForm(forms.Form):
    """What Otahque asks at sign-up, beside the email."""

    display_name = forms.CharField(
        max_length=100, help_text=NAME_HELP,
    )
    timezone = forms.ChoiceField(
        choices=ZONE_CHOICES, required=False,
        label='Time zone (optional)',
    )

    def signup(self, request, user):
        """Save the extra answers once the account exists."""
        user.display_name = self.cleaned_data['display_name']
        user.save(update_fields=['display_name'])
        profile = Profile.of(user)
        profile.timezone = self.cleaned_data['timezone']
        profile.save()


class ProfileForm(forms.Form):
    """The signed-in member's name, zone, and phone."""

    display_name = forms.CharField(
        max_length=100, help_text=NAME_HELP,
    )
    timezone = forms.ChoiceField(
        choices=ZONE_CHOICES, required=False,
        label='Time zone (optional)',
    )
    phone = PhoneNumberField(
        required=False, label='Phone number (optional)',
        help_text=PHONE_HELP,
    )

    def save(self, user):
        """Save the name to the user, the rest to Profile."""
        user.display_name = self.cleaned_data['display_name']
        user.save(update_fields=['display_name'])
        profile = Profile.of(user)
        profile.timezone = self.cleaned_data['timezone']
        profile.phone = self.cleaned_data['phone']
        profile.full_clean()
        profile.save()


class PhoneForm(forms.Form):
    """The phone number an event asks for, once."""

    phone = PhoneNumberField(
        label='Phone number', help_text=PHONE_HELP,
    )

    def save(self, user):
        """Keep the number on the member's Profile."""
        profile = Profile.of(user)
        profile.phone = self.cleaned_data['phone']
        profile.full_clean()
        profile.save(update_fields=['phone'])


class OneUseActivateTOTPForm(ActivateTOTPForm):
    """allauth's form for turning on an authenticator app.

    The code is marked as used, so it cannot sign in again
    within its 30 seconds (NIST SP 800-63B-4).
    """

    def clean_code(self):
        """Mark the activation code as used."""
        code = super().clean_code()
        # A private allauth method: TwoFactorTests fails
        # if an upgrade changes it.
        unsaved = Authenticator(
            user=self.user, type=Authenticator.Type.TOTP,
        )
        TOTP(unsaved)._mark_code_used(code)
        return code
