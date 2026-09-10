from django.urls import path

from . import views

urlpatterns = [
    path('', views.hub, name='hub'),
    path('faq/', views.faq, name='faq'),
    path('terminos/', views.terminos, name='terminos'),
    path('contacto/', views.contacto, name='contacto'),
    path('<slug:pais_slug>/', views.pais_home, name='pais_home'),
    path('<slug:pais_slug>/buscar/', views.buscador_pais, name='buscador_pais'),
    path('<slug:pais_slug>/p/<int:pk>/', views.detalle_psicologo, name='detalle_psicologo'),
]
