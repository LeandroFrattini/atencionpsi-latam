from django.contrib import admin

from .models import ConfiguracionWhatsApp, ContactoWhatsApp, RespuestaPais


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


@admin.register(ContactoWhatsApp)
class ContactoWhatsAppAdmin(admin.ModelAdmin):
    """Para ver si los mensajes llegan y si se responden. Solo lectura (se puede borrar a pedido de la persona)."""
    list_display = ('telefono', 'ultimo_mensaje', 'ultima_respuesta', 'ultimo_error')
    ordering = ('-ultimo_mensaje',)
    search_fields = ('telefono',)
    readonly_fields = ('telefono', 'ultimo_mensaje', 'ultima_respuesta', 'ultimo_error', 'creado')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
