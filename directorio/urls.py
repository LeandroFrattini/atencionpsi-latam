from django.urls import path

from . import views

urlpatterns = [
    path('', views.hub, name='hub'),
    path('faq/', views.faq, name='faq'),
    path('<slug:pais_slug>/', views.buscador_pais, name='buscador_pais'),
    path('<slug:pais_slug>/p/<int:pk>/', views.detalle_psicologo, name='detalle_psicologo'),
]
