from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('<slug:pais_slug>/registro/', views.registro, name='portal_registro'),
    path('login/', auth_views.LoginView.as_view(template_name='portal/login.html'), name='portal_login'),
    path('logout/', auth_views.LogoutView.as_view(), name='portal_logout'),
    path('checkout/', views.checkout, name='portal_checkout'),
    path('checkout/simular-pago/', views.simular_pago, name='portal_simular_pago'),
    path('', views.dashboard, name='portal_dashboard'),
    path('perfil/', views.editar_perfil, name='portal_editar_perfil'),
    path('publicar/', views.publicar, name='portal_publicar'),
    path('despublicar/', views.despublicar, name='portal_despublicar'),
]
