"""The accounts app's own views; allauth has the rest."""
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ProfileForm
from .models import Profile


@login_required
def profile(request):
    """Show the signed-in member's profile; no id is read."""
    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            form.save(user)
            messages.success(request, 'Profile saved.')
            return redirect('accounts:profile')
    else:
        profile = Profile.of(user)
        form = ProfileForm(initial={
            'display_name': user.display_name,
            'timezone': profile.timezone,
            'phone': profile.phone,
        })
    return render(request, 'accounts/profile.html', {
        'form': form,
        'two_factor': Authenticator.objects.filter(
            user=user, type=Authenticator.Type.TOTP,
        ).exists(),
        'unconfirmed': EmailAddress.objects.filter(
            user=user, verified=False,
        ).exists(),
    })
