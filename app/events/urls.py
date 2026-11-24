"""Addresses of the events app's pages."""
from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.home, name='home'),
    path('events/', views.event_list, name='list'),
    path('events/new/', views.event_create,
         name='create'),
    path('events/manage/', views.event_manage,
         name='manage'),
    path('events/<int:event_id>/',
         views.EventDetailView.as_view(), name='detail'),
    path('events/<int:event_id>/edit/', views.event_edit,
         name='edit'),
    path('events/<int:event_id>/publish/',
         views.event_publish, name='publish'),
    path('events/<int:event_id>/cancel/',
         views.event_cancel, name='cancel'),
    path('events/<int:event_id>/delete/',
         views.event_delete, name='delete'),
    path('events/<int:event_id>/copy/', views.event_copy,
         name='copy'),
    path('events/organizers/', views.organizer_events,
         name='organizer_events'),
    path('events/<int:event_id>/organizers/',
         views.event_organizers, name='organizers'),
    path('events/<int:event_id>/organizers/remove/',
         views.remove_organizer, name='remove_organizer'),
]
