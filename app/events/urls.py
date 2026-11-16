from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.home, name='home'),
    path('events/', views.event_list, name='list'),
    path('events/new/', views.event_create,
         name='create'),
    path('events/<int:event_id>/', views.event_detail,
         name='detail'),
]
