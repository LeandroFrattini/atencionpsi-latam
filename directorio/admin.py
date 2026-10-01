import zipfile
from io import BytesIO

from django.contrib import admin
from django.contrib.admin import helpers
from django.http import HttpResponse
from django.template.response import TemplateResponse

from .models import Formacion, Orientacion, Pais, Psicologo, Publico


@admin.register(Pais)
class PaisAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_iso', 'slug', 'moneda', 'codigo_telefono', 'precio_basico', 'precio_premium', 'etiqueta_matricula', 'muestra_precio_sesion', 'es_externo', 'activo', 'orden')
    list_editable = ('activo', 'orden', 'codigo_telefono', 'precio_basico', 'precio_premium')
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
    list_display = ('nombre', 'pais', 'ciudad', 'modalidad', 'plan', 'suscripcion_activa', 'exento_de_pago', 'publicado', 'destacado')
    list_filter = ('pais', 'modalidad', 'plan', 'suscripcion_activa', 'exento_de_pago', 'destacado', 'orientaciones', 'publicos')
    search_fields = ('nombre', 'matricula', 'whatsapp')
    filter_horizontal = ('orientaciones', 'publicos')
    inlines = [FormacionInline]
    fieldsets = (
        (None, {'fields': ('usuario', 'pais', 'nombre', 'matricula', 'whatsapp', 'ciudad', 'modalidad')}),
        ('Perfil público', {'fields': ('foto', 'bio', 'docencia', 'precio_sesion', 'sesiones_atendidas', 'orientaciones', 'publicos')}),
        ('Pago y publicación', {'fields': ('plan', 'suscripcion_activa', 'dlocal_subscription_id', 'exento_de_pago', 'destacado', 'terminos_aceptados_en')}),
    )
    readonly_fields = ('terminos_aceptados_en',)
    actions = ['generar_imagenes_action', 'generar_imagen_feed_action']

    @admin.display(boolean=True)
    def publicado(self, obj):
        return obj.publicado

    def generar_imagenes_action(self, request, queryset):
        """Genera la historia de Instagram (1080x1920) de cada psicólogo
        seleccionado y las devuelve en un zip. Portado de atencionpsi.com.ar."""
        from .generador_imagenes import generar_imagen_story

        if 'apply' in request.POST:
            telefono_manual = request.POST.get('telefono_manual', '').strip()
            buf = BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for p in queryset:
                    nombre_slug = p.nombre.lower().replace(' ', '-')
                    story_img = generar_imagen_story(p, telefono_manual=telefono_manual or None)
                    story_buf = BytesIO()
                    story_img.save(story_buf, 'JPEG', quality=92)
                    zf.writestr(f'{nombre_slug}_historia.jpg', story_buf.getvalue())

            buf.seek(0)
            response = HttpResponse(buf.read(), content_type='application/zip')
            response['Content-Disposition'] = 'attachment; filename="historias_psicologos.zip"'
            return response

        context = {
            **self.admin_site.each_context(request),
            'title': 'Generar historias de Instagram',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'media': self.media,
        }
        return TemplateResponse(request, 'admin/generar_imagenes.html', context)

    generar_imagenes_action.short_description = 'Generar historia de Instagram'

    def generar_imagen_feed_action(self, request, queryset):
        """Genera el post de feed (1080x1350) de cada psicólogo seleccionado
        y los devuelve en un zip. Portado de atencionpsi.com.ar."""
        from .generador_imagenes import generar_imagen_feed

        if 'apply' in request.POST:
            buf = BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for p in queryset:
                    nombre_slug = p.nombre.lower().replace(' ', '-')
                    feed_img = generar_imagen_feed(p)
                    feed_buf = BytesIO()
                    feed_img.save(feed_buf, 'JPEG', quality=92)
                    zf.writestr(f'{nombre_slug}_feed.jpg', feed_buf.getvalue())

            buf.seek(0)
            response = HttpResponse(buf.read(), content_type='application/zip')
            response['Content-Disposition'] = 'attachment; filename="posts_feed_psicologos.zip"'
            return response

        context = {
            **self.admin_site.each_context(request),
            'title': 'Generar posts de feed de Instagram',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'media': self.media,
        }
        return TemplateResponse(request, 'admin/generar_imagen_feed.html', context)

    generar_imagen_feed_action.short_description = 'Generar post de feed de Instagram'
