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
        return reverse('detalle_psicologo', args=[obj.pais.slug, obj.pk])

    def lastmod(self, obj):
        return obj.fecha_pago_confirmado
