"""En qué punto está cada profesional, para ordenar y filtrar la lista del admin.

El estado se calcula en la base de datos con las mismas reglas que usa el sitio
(`Psicologo.publicado`, `puede_publicar`, `perfil_completo`), así lo que ves en el admin es
exactamente lo que está o no publicado. Hay un test que compara las dos cosas.
"""
from django.db.models import CharField, Case, Exists, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.utils import timezone

from .models import ClickWhatsApp, Psicologo

# (código, etiqueta corta, qué significa, color del cartelito)
ESTADOS = [
    ('publicado', 'Publicado', 'Visible en el buscador.', '#2e7d32'),
    ('listo', 'Listo, sin publicar', 'Tiene todo para publicar, pero no tocó "Publicar" (o dejó de mostrarse).', '#1565c0'),
    ('por_pagar', 'Pidió publicar, falta el plan', 'Completó el perfil y tocó "Publicar", pero no eligió o no terminó de pagar el plan: salió del paso a un solo pago. Es el contacto más caliente.', '#00838f'),
    ('perfil_listo', 'Perfil listo, sin pedir publicar', 'Completó todo el perfil pero todavía no tocó "Publicar" ni tiene plan: está por decidir.', '#26a69a'),
    ('incompleto', 'Perfil incompleto', 'Ya puede publicar (pagó, tiene gratis o está exento) pero le faltan datos del perfil.', '#ef6c00'),
    ('vencido', 'Gratis vencido', 'Se le terminó el período gratis y no activó la suscripción: su perfil no se muestra.', '#8e24aa'),
    ('sin_pago', 'Solo cuenta', 'Hizo la cuenta y confirmó su email, pero no completó el perfil ni pagó. Las cuentas nuevas no pueden armar el perfil hasta pagar; las anteriores sí.', '#757575'),
    ('sin_confirmar', 'Email sin confirmar', 'Se registró pero no confirmó su email: todavía no puede entrar.', '#c62828'),
]
CODIGOS = [c for c, *_ in ESTADOS]
ETIQUETAS = {c: e for c, e, *_ in ESTADOS}
EXPLICACIONES = {c: x for c, _, x, _ in ESTADOS}
COLORES = {c: col for c, _, _, col in ESTADOS}


def con_estado(queryset):
    """Agrega al queryset `estado_codigo`, `estado_orden`, `visitas_30` (visitas al perfil de
    los últimos 30 días) y `clicks_wa_30` (clicks en su botón de WhatsApp en ese período)."""
    import datetime
    ahora = timezone.now()
    hace_30 = timezone.localdate() - datetime.timedelta(days=29)

    acceso = Q(suscripcion_activa=True) | Q(exento_de_pago=True) | Q(gratis_hasta__gt=ahora)
    perfil_completo = (
        ~Q(nombre='') & ~Q(matricula='') & ~Q(whatsapp='')
        & Q(foto__isnull=False) & ~Q(foto='')
        & ~Q(bio='') & Q(con_orientacion=True)
    )

    tiene_orientacion = Exists(Psicologo.orientaciones.through.objects.filter(psicologo_id=OuterRef('pk')))
    estado = Case(
        When(usuario__is_active=False, then=Value('sin_confirmar')),
        When(acceso & perfil_completo & Q(publicado_por_usuario=True), then=Value('publicado')),
        When(acceso & perfil_completo, then=Value('listo')),
        When(acceso, then=Value('incompleto')),
        When(gratis_hasta__isnull=False, then=Value('vencido')),
        When(perfil_completo & Q(publicado_por_usuario=True), then=Value('por_pagar')),
        When(perfil_completo, then=Value('perfil_listo')),
        default=Value('sin_pago'),
        output_field=CharField(),
    )
    orden = Case(
        *[When(estado_codigo=codigo, then=Value(i)) for i, codigo in enumerate(CODIGOS)],
        default=Value(len(CODIGOS)),
        output_field=IntegerField(),
    )
    clicks_30 = (
        ClickWhatsApp.objects.filter(psicologo=OuterRef('pk'), fecha__gte=hace_30)
        .values('psicologo').annotate(t=Sum('cantidad')).values('t')
    )
    return (
        queryset
        .annotate(con_orientacion=tiene_orientacion)
        .annotate(estado_codigo=estado)
        .annotate(estado_orden=orden)
        .annotate(visitas_30=Sum('visitas_perfil__cantidad', filter=Q(visitas_perfil__fecha__gte=hace_30)))
        .annotate(clicks_wa_30=Subquery(clicks_30, output_field=IntegerField()))
    )


def resumen_por_pais():
    """[{'pais': Pais, 'total': n, 'estados': {codigo: n}}] solo de países con profesionales, más
    una fila final con los totales. Para el cuadro del inicio del admin."""
    from collections import Counter, defaultdict

    from .models import Pais

    cuentas = defaultdict(Counter)
    for pais_id, codigo in con_estado(Psicologo.objects.all()).values_list('pais_id', 'estado_codigo'):
        cuentas[pais_id][codigo] += 1
    filas = []
    total = Counter()
    for pais in Pais.objects.filter(es_externo=False).order_by('orden', 'nombre'):
        estados = cuentas.get(pais.pk)
        if not estados:
            continue
        filas.append({'pais': pais, 'total': sum(estados.values()), 'estados': {c: estados.get(c, 0) for c in CODIGOS}})
        total.update(estados)
    return filas, {'total': sum(total.values()), 'estados': {c: total.get(c, 0) for c in CODIGOS}}
