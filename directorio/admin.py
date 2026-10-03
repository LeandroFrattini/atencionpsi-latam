import zipfile
from io import BytesIO

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.http import HttpResponse
from django.template.response import TemplateResponse

from . import dlocal_go
from .models import Ciudad, Formacion, Orientacion, Pais, PlanDLocal, Psicologo, Publico


@admin.register(Pais)
class PaisAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_iso', 'slug', 'moneda', 'codigo_telefono', 'precio_basico', 'precio_premium', 'etiqueta_matricula', 'muestra_precio_sesion', 'es_externo', 'activo', 'orden')
    list_editable = ('activo', 'orden', 'codigo_telefono', 'precio_basico', 'precio_premium')
    prepopulated_fields = {'slug': ('nombre',)}


class ModeracionAdminMixin:
    """Orientaciones, públicos y ciudades que un profesional propuso a mano
    nacen con aprobado=False y solo los ve él (ver directorio/taxonomia.py).
    Acá se revisan: "Aprobar" los pasa a la lista de todos; si no querés
    alguno, borralo (se le saca al profesional que lo había propuesto)."""
    list_filter = ('aprobado',)
    actions = ['aprobar_seleccionados']

    @admin.display(description='Profesionales que lo usan')
    def usos(self, obj):
        return obj.psicologos.count() if hasattr(obj, 'psicologos') else Psicologo.objects.filter(
            pais=obj.pais, ciudad__iexact=obj.nombre).count()

    @admin.action(description='Aprobar seleccionados (pasan a estar disponibles para todos)')
    def aprobar_seleccionados(self, request, queryset):
        cantidad = queryset.filter(aprobado=False).update(aprobado=True)
        self.message_user(request, f'{cantidad} aprobado(s).', level=messages.SUCCESS)


@admin.register(Orientacion)
class OrientacionAdmin(ModeracionAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'aprobado', 'propuesto_por', 'usos', 'orden')
    list_editable = ('orden',)
    search_fields = ('nombre',)


@admin.register(Publico)
class PublicoAdmin(ModeracionAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'aprobado', 'propuesto_por', 'usos', 'orden')
    list_editable = ('orden',)
    search_fields = ('nombre',)


@admin.register(Ciudad)
class CiudadAdmin(ModeracionAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'pais', 'aprobado', 'propuesto_por', 'usos', 'orden')
    list_filter = ('aprobado', 'pais')
    list_editable = ('orden',)
    search_fields = ('nombre',)


@admin.register(PlanDLocal)
class PlanDLocalAdmin(admin.ModelAdmin):
    """Los planes se crean con `manage.py crear_planes_dlocal --apply`, no a mano:
    acá se ven (con su link de pago) pero no se editan."""
    list_display = ('pais', 'plan', 'moneda', 'monto', 'dlocal_plan_id', 'activo')
    readonly_fields = [f.name for f in PlanDLocal._meta.fields]

    def has_add_permission(self, request):
        return False


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
        ('Pago y publicación', {'fields': ('plan', 'suscripcion_activa', 'dlocal_subscription_id', 'pago_declinado_desde', 'exento_de_pago', 'destacado', 'terminos_aceptados_en')}),
    )
    readonly_fields = ('terminos_aceptados_en', 'pago_declinado_desde')
    actions = ['generar_imagenes_action', 'generar_imagen_feed_action', 'dar_de_baja_dlocal_action']

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

    def dar_de_baja_dlocal_action(self, request, queryset):
        """Cancela en dLocal Go la suscripción mensual (deja de cobrarse) y
        despublica al profesional. Los Términos dicen que la baja se pide por
        mail/WhatsApp, así que esto es lo que hace la dueña cuando se lo piden.
        Pide confirmación porque cancela un cobro real y no se puede deshacer
        desde acá (el profesional tendría que volver a suscribirse)."""
        if 'apply' in request.POST:
            for p in queryset:
                plan = PlanDLocal.objects.filter(pais=p.pais, plan=p.plan).first()
                if not (plan and p.dlocal_subscription_id.isdigit()):
                    self.message_user(
                        request, f'{p.nombre}: no tiene una suscripción real en dLocal Go (¿es de prueba o fundadora?).',
                        level=messages.WARNING,
                    )
                    continue
                try:
                    dlocal_go.desactivar_suscripcion(plan.dlocal_plan_id, int(p.dlocal_subscription_id))
                except dlocal_go.DLocalError as e:
                    self.message_user(request, f'{p.nombre}: no se pudo dar de baja en dLocal Go ({e}).', level=messages.ERROR)
                    continue
                p.suscripcion_activa = False
                p.save(update_fields=['suscripcion_activa'])
                self.message_user(request, f'{p.nombre}: suscripción dada de baja y perfil despublicado.', level=messages.SUCCESS)
            return None

        context = {
            **self.admin_site.each_context(request),
            'title': 'Dar de baja suscripciones en dLocal Go',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'media': self.media,
        }
        return TemplateResponse(request, 'admin/confirmar_baja_dlocal.html', context)

    dar_de_baja_dlocal_action.short_description = 'Dar de baja la suscripción en dLocal Go (deja de cobrarse)'
