from django.urls import path

from . import views

urlpatterns = [
    path('<slug:pais_slug>/p/<int:pk>/reservar/tipo/', views.paso_tipo, name='reserva_tipo'),
    path('<slug:pais_slug>/p/<int:pk>/reservar/modalidad/', views.paso_modalidad, name='reserva_modalidad'),
    path('<slug:pais_slug>/p/<int:pk>/reservar/horario/', views.paso_horario, name='reserva_horario'),
    path('<slug:pais_slug>/p/<int:pk>/reservar/datos/', views.paso_datos, name='reserva_datos'),
    path('<slug:pais_slug>/p/<int:pk>/reservar/confirmar/', views.paso_confirmar, name='reserva_confirmar'),
]
