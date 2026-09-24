from django.conf import settings

from .models import Pais, Psicologo


def paises_activos(request):
    return {'paises_activos': Pais.objects.filter(activo=True)}


def stats_globales(request):
    """Total de sesiones atendidas entre todos los profesionales publicados
    de LatAm, sumando el rango que cada uno declaró al registrarse (ver
    Psicologo.sesiones_atendidas) -- se usa como cartel de confianza cerca
    del buscador ("Más de X sesiones atendidas en Latinoamérica"). Se
    resuelve en Python porque `publicado` es una property (pago + perfil
    completo), no un campo de la base, así que no se puede sumar con
    aggregate() directo sobre el queryset filtrado."""
    qs = Psicologo.objects.filter(
        pais__activo=True, pais__es_externo=False, sesiones_atendidas__isnull=False,
    )
    total = sum(p.sesiones_atendidas for p in qs if p.publicado)
    return {'total_sesiones_atendidas_latam': total}


def footer_contexto(request):
    """Datos de contacto/redes para el footer, disponibles en todas las
    páginas (dLocal Go pidió que estén visibles en todo el sitio)."""
    return {
        'footer_contacto_email': settings.CONTACTO_EMAIL,
        'footer_contacto_whatsapp': settings.CONTACTO_WHATSAPP,
        'footer_instagram_url': settings.INSTAGRAM_URL,
        'footer_facebook_url': settings.FACEBOOK_URL,
    }


def analytics_contexto(request):
    """Si no hay GA4_MEASUREMENT_ID seteado, ni el banner de cookies ni el
    script de analítica aparecen (ver templates/base.html)."""
    return {'ga4_measurement_id': settings.GA4_MEASUREMENT_ID}
