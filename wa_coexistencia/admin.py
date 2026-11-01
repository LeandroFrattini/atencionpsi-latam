from django.contrib import admin

from .models import ConfiguracionWhatsApp, RespuestaPais


class RespuestaPaisInline(admin.TabularInline):
    model = RespuestaPais
    extra = 1
    fields = ('pais', 'texto', 'archivo')


@admin.register(ConfiguracionWhatsApp)
class ConfiguracionWhatsAppAdmin(admin.ModelAdmin):
    """Una sola configuración: no se agrega ni se borra, se edita."""
    inlines = [RespuestaPaisInline]
    fieldsets = (
        (None, {'fields': ('activa', 'horas_entre_respuestas')}),
        ('Primer mensaje', {'fields': ('texto_bienvenida',)}),
        ('Segundo mensaje', {
            'fields': ('texto_otro_pais',),
            'description': 'El segundo mensaje depende del país de quien escribe (se detecta por el código del '
                           'teléfono de cada país). Cargá uno por país en la tabla de abajo.',
        }),
    )

    def has_add_permission(self, request):
        return not ConfiguracionWhatsApp.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
