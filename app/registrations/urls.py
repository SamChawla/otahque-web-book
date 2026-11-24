"""Addresses of the registrations app's pages."""
from django.urls import path

from . import views

app_name = 'registrations'

urlpatterns = [
    path('events/<int:event_id>/register/',
         views.register, name='register'),
    path('events/<int:event_id>/register/phone/',
         views.RegistrationDetailsView.as_view(),
         name='phone'),
    path('registrations/', views.my_registrations,
         name='mine'),
    path('registrations/<int:registration_id>/cancel/',
         views.cancel_registration, name='cancel'),
    path('events/<int:event_id>/registrations/',
         views.attendees, name='attendees'),
]
