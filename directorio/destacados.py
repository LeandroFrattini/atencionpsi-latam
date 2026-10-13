"""Mezcla aleatoria de profesionales de todos los países para el inicio.

Los de Perú, Uruguay, Chile (y los países que se sumen) salen de esta base. Los de
Argentina viven en atencionpsi.com.ar, así que se piden a un listado público de ese
sitio (ARGENTINA_FEED_URL) y solo se incluyen si Argentina está activa acá. Si el
listado no responde, no existe todavía o viene mal, se muestran los demás sin
romper nada.
"""
import logging
import random

import requests
from django.conf import settings
from django.core.cache import cache
from django.templatetags.static import static

from .models import Pais, Psicologo

logger = logging.getLogger(__name__)

CACHE_KEY = 'destacados_feed_argentina'
CACHE_SEGUNDOS = 600


def _item_latam(p):
    return {
        'nombre': p.nombre,
        'ciudad': p.ciudad_publica,
        'enfoque': ', '.join(o.nombre for o in p.orientaciones_publicas[:2]),
        'foto_url': p.foto.url if p.foto else '',
        'url': p.url_publica,
        'externo': False,
        'pais_nombre': p.pais.nombre,
        'bandera_url': static(p.pais.bandera_svg),
    }


def _feed_argentina(pais):
    """Profesionales de Argentina (lista de dicts ya normalizados). Cacheado unos
    minutos; ante cualquier problema devuelve [] y lo recuerda un rato corto para no
    insistir en cada visita."""
    cacheado = cache.get(CACHE_KEY)
    if cacheado is not None:
        return cacheado
    url = getattr(settings, 'ARGENTINA_FEED_URL', '')
    if not url:
        return []
    try:
        resp = requests.get(url, timeout=3, headers={'User-Agent': 'AtencionPsiLatam/1.0 (+https://atencionpsi.lat)'})
        resp.raise_for_status()
        datos = resp.json().get('profesionales', [])
        items = []
        for d in datos:
            if not (d.get('nombre') and d.get('url')):
                continue
            items.append({
                'nombre': str(d['nombre'])[:100],
                'ciudad': str(d.get('ciudad') or '')[:100],
                'enfoque': str(d.get('orientacion') or '')[:100],
                'foto_url': str(d.get('foto') or ''),
                'url': str(d['url']),
                'externo': True,
                'pais_nombre': pais.nombre,
                'bandera_url': static(pais.bandera_svg),
            })
        cache.set(CACHE_KEY, items, CACHE_SEGUNDOS)
        return items
    except Exception:
        logger.warning('No se pudo leer el listado de profesionales de Argentina', exc_info=True)
        cache.set(CACHE_KEY, [], 60)
        return []


def mezcla_de_psicologos(cantidad=8):
    """Hasta `cantidad` profesionales de todos los países activos, en orden aleatorio
    y repartidos entre países (para que no domine el que más tiene)."""
    grupos = []
    paises = Pais.objects.filter(activo=True)
    for pais in paises:
        if pais.es_externo:
            if pais.slug == 'argentina':
                items = list(_feed_argentina(pais))
            else:
                items = []
        else:
            qs = pais.psicologos.select_related('pais').prefetch_related('orientaciones')
            items = [_item_latam(p) for p in qs if p.publicado and p.foto]
        random.shuffle(items)
        if items:
            grupos.append(items)

    elegidos = []
    while grupos and len(elegidos) < cantidad:
        for grupo in list(grupos):
            if len(elegidos) >= cantidad:
                break
            elegidos.append(grupo.pop())
            if not grupo:
                grupos.remove(grupo)
    random.shuffle(elegidos)
    return elegidos
