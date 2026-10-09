from django.urls import path

from . import views

urlpatterns = [
    path('', views.hub, name='hub'),
    path('faq/', views.faq, name='faq'),
    path('terminos/', views.terminos, name='terminos'),
    path('privacidad/', views.privacidad, name='privacidad'),
    path('contacto/', views.contacto, name='contacto'),
    path('<slug:pais_slug>/', views.pais_home, name='pais_home'),
    path('<slug:pais_slug>/buscar/', views.buscador_pais, name='buscador_pais'),
    path('<slug:pais_slug>/psicologo/<slug:slug>/', views.perfil_psicologo, name='perfil_psicologo'),
    path('<slug:pais_slug>/psicologos-en-<slug:ciudad_slug>/', views.psicologos_en_ciudad, name='psicologos_en_ciudad'),
    path('<slug:pais_slug>/psicologos-para-<slug:especialidad_slug>/', views.psicologos_por_especialidad, name='psicologos_por_especialidad'),
    # URL vieja del perfil: se mantiene y redirige (301) a la de arriba.
    path('<slug:pais_slug>/p/<int:pk>/', views.detalle_psicologo, name='detalle_psicologo'),
]
