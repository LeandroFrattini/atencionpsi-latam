from django.contrib import admin

from .models import DiaNoAtiende, DisponibilidadSemanal, Paciente, TipoSesion, Turno


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'psicologo', 'telefono', 'email', 'creado_en')
    list_filter = ('psicologo__pais',)
    search_fields = ('nombres', 'apellidos', 'email', 'psicologo__nombre')


@admin.register(TipoSesion)
class TipoSesionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'psicologo', 'duracion_min', 'precio', 'orden')
    list_filter = ('psicologo__pais',)
    search_fields = ('nombre', 'psicologo__nombre')


@admin.register(DisponibilidadSemanal)
class DisponibilidadSemanalAdmin(admin.ModelAdmin):
    list_display = ('psicologo', 'dia_semana', 'hora_desde', 'hora_hasta')
    list_filter = ('psicologo__pais', 'dia_semana')


@admin.register(DiaNoAtiende)
class DiaNoAtiendeAdmin(admin.ModelAdmin):
    list_display = ('psicologo', 'fecha_desde', 'fecha_hasta', 'motivo')
    list_filter = ('psicologo__pais',)


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ('psicologo', 'nombres', 'apellidos', 'fecha_hora', 'modalidad', 'estado')
    list_filter = ('psicologo__pais', 'modalidad', 'estado')
    search_fields = ('nombres', 'apellidos', 'email', 'psicologo__nombre')
    date_hierarchy = 'fecha_hora'
    raw_id_fields = ('paciente',)
