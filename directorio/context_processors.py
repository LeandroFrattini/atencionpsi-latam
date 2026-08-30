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
