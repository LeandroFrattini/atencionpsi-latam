from django.contrib import admin

from . import diagnostico
from .models import ConfiguracionWhatsApp, ContactoWhatsApp, EventoWebhook, RespuestaPais


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


@admin.register(EventoWebhook)
class EventoWebhookAdmin(admin.ModelAdmin):
    """Cada llamada que recibió el webhook de WhatsApp y qué pasó. Arriba, un resumen de qué revisar primero.
    Solo lectura (se pueden borrar para limpiar). No guarda contenido de mensajes ni teléfonos."""
    change_list_template = 'admin/wa_coexistencia/eventowebhook/change_list.html'
    list_display = ('creado', 'metodo', 'resultado', 'detalle', 'mensajes', 'numero_id')
    list_filter = ('resultado', 'metodo')
    ordering = ('-creado',)
    readonly_fields = ('creado', 'metodo', 'resultado', 'detalle', 'mensajes', 'numero_id', 'agente')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = dict(extra_context or {}, estado=diagnostico.estado())
        return super().changelist_view(request, extra_context=extra_context)
