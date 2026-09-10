from django.contrib import admin

from .models import Formacion, Orientacion, Pais, Psicologo, Publico


@admin.register(Pais)
class PaisAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_iso', 'slug', 'moneda', 'precio_basico', 'precio_premium', 'etiqueta_matricula', 'muestra_precio_sesion', 'es_externo', 'activo', 'orden')
    list_editable = ('activo', 'orden', 'precio_basico', 'precio_premium')
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(Orientacion)
class OrientacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden')
    list_editable = ('orden',)


@admin.register(Publico)
class PublicoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden')
    list_editable = ('orden',)


class FormacionInline(admin.TabularInline):
    model = Formacion
    extra = 1


@admin.register(Psicologo)
class PsicologoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'pais', 'ciudad', 'modalidad', 'suscripcion_activa', 'exento_de_pago', 'publicado', 'destacado')
    list_filter = ('pais', 'modalidad', 'suscripcion_activa', 'exento_de_pago', 'destacado', 'orientaciones', 'publicos')
    search_fields = ('nombre', 'matricula', 'whatsapp')
    filter_horizontal = ('orientaciones', 'publicos')
    inlines = [FormacionInline]
    fieldsets = (
        (None, {'fields': ('usuario', 'pais', 'nombre', 'matricula', 'whatsapp', 'ciudad', 'modalidad')}),
        ('Perfil público', {'fields': ('foto', 'bio', 'docencia', 'precio_sesion', 'sesiones_atendidas', 'orientaciones', 'publicos')}),
        ('Pago y publicación', {'fields': ('suscripcion_activa', 'dlocal_subscription_id', 'exento_de_pago', 'destacado')}),
    )

    @admin.display(boolean=True)
    def publicado(self, obj):
        return obj.publicado
