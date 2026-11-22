"""Addresses of the accounts app's own pages."""
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('accounts/profile/', views.profile, name='profile'),
]
