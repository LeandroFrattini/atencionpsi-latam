"""Contador de visitas: por página y por profesional, sin contar robots ni a quien administra."""
import logging
import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .bot_detector import es_bot

logger = logging.getLogger(__name__)

# Lo que nunca se cuenta: panel de administración, portal del profesional, archivos, la API y
# los archivos para buscadores.
IGNORAR = ('/admin/', '/portal/', '/static/', '/media/', '/api/', '/favicon', '/robots.txt', '/sitemap.xml')


def _sumar(modelo, **claves):
    """Suma 1 a la fila del día (la crea si no existe), sin perder cuentas si dos personas
    entran a la vez."""
    with transaction.atomic():
        if modelo.objects.filter(**claves).update(cantidad=F('cantidad') + 1):
            return
        try:
            with transaction.atomic():
                modelo.objects.create(cantidad=1, **claves)
        except IntegrityError:
            modelo.objects.filter(**claves).update(cantidad=F('cantidad') + 1)


class VisitaMiddleware:
    """Cuenta solo visitas REALES: páginas que cargaron bien (200), pedidas por una persona
    (no un bot), que no sean del panel ni de quien administra el sitio, ni la visita de un
    profesional a su propio perfil. Nunca rompe el sitio: si algo falla, lo registra y sigue."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._contar(request, response)
        except Exception:
            logger.warning('No se pudo contar la visita de %s', request.path, exc_info=True)
        return response

    def _contar(self, request, response):
        from .models import Visita, VisitaPerfil

        if request.method != 'GET' or response.status_code != 200:
            return
        if any(request.path.startswith(p) for p in IGNORAR):
            return
        # Las actualizaciones en vivo del buscador no son páginas nuevas.
        if request.GET.get('fragmento') or request.headers.get('X-Requested-With') == 'fetch':
            return
        if es_bot(request):
            return
        usuario = getattr(request, 'user', None)
        if usuario is not None and usuario.is_authenticated and usuario.is_staff:
            return

        hoy = timezone.localdate()
        _sumar(Visita, fecha=hoy, pagina=request.path[:200])

        coincidencia = request.resolver_match
        if coincidencia and coincidencia.url_name == 'perfil_psicologo':
            m = re.search(r'-(\d+)$', coincidencia.kwargs.get('slug', ''))
            if not m:
                return
            pk = int(m.group(1))
            propio = (
                usuario is not None and usuario.is_authenticated
                and getattr(getattr(usuario, 'psicologo', None), 'pk', None) == pk
            )
            if not propio:
                _sumar(VisitaPerfil, fecha=hoy, psicologo_id=pk)
