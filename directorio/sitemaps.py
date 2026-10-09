from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Pais, Psicologo


class PaisesSitemap(Sitemap):
    """El hub y el buscador de cada país activo (no externo -- Argentina
    vive en atencionpsi.com.ar y no se lista acá)."""
    changefreq = 'daily'
    priority = 1.0

    def items(self):
        return ['hub'] + list(Pais.objects.filter(activo=True, es_externo=False).values_list('slug', flat=True))

    def location(self, item):
        if item == 'hub':
            return reverse('hub')
        return reverse('pais_home', args=[item])


class PsicologosSitemap(Sitemap):
    """Solo perfiles publicados -- los mismos que ya son visibles (no tiene
    sentido indexar un perfil que da 404)."""
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        # publicado es una property (combina pago + perfil completo), no un
        # campo de la base -- se resuelve en Python sobre el queryset ya
        # filtrado por país activo, igual que en directorio/views.py.
        qs = Psicologo.objects.filter(pais__activo=True, pais__es_externo=False).select_related('pais')
        return [p for p in qs if p.publicado]

    def location(self, obj):
        return obj.url_publica

    def lastmod(self, obj):
        return obj.fecha_pago_confirmado


class CiudadesSitemap(Sitemap):
    """Páginas /psicologos-en-<ciudad>/ -- solo las que tienen al menos un
    profesional publicado (las vacías van en noindex y no se anuncian)."""
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        from .views import _ciudades_con_psicologos, _publicados
        resultado = []
        for pais in Pais.objects.filter(activo=True, es_externo=False):
            resultado += [(pais, ciudad) for ciudad, _ in _ciudades_con_psicologos(pais, _publicados(pais))]
        return resultado

    def location(self, item):
        pais, ciudad = item
        return reverse('psicologos_en_ciudad', args=[pais.slug, ciudad.slug])


class EspecialidadesSitemap(Sitemap):
    """Páginas /psicologos-para-<especialidad>/, con la misma regla."""
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        from .views import _especialidades_con_psicologos, _publicados
        resultado = []
        for pais in Pais.objects.filter(activo=True, es_externo=False):
            resultado += [(pais, e) for e, _ in _especialidades_con_psicologos(_publicados(pais))]
        return resultado

    def location(self, item):
        pais, especialidad = item
        return reverse('psicologos_por_especialidad', args=[pais.slug, especialidad.slug])
