from django.urls import path

from . import views

urlpatterns = [
    path('', views.hub, name='hub'),
    path('<slug:pais_slug>/', views.buscador_pais, name='buscador_pais'),
]
