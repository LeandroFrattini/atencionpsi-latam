"""México sale al aire (migración 0023_activar_mexico): país activo con sus
precios y su lista de ciudades, páginas públicas y registro andando, y el
teléfono bien formateado en las imágenes de Instagram."""
from django.test import TestCase
from django.urls import reverse

from .generador_imagenes import _formatear_telefono
from .models import Ciudad, Pais


class MexicoActivoTests(TestCase):
    """Estos tests NO borran los países: verifican lo que dejó la migración."""

    def setUp(self):
        self.mx = Pais.objects.get(slug='mexico')

    def test_el_pais_esta_activo_con_sus_datos(self):
        self.assertTrue(self.mx.activo)
        self.assertFalse(self.mx.es_externo)
        self.assertEqual(self.mx.moneda, 'MXN')
        self.assertEqual(self.mx.codigo_telefono, '52')
        self.assertEqual(self.mx.etiqueta_matricula, 'N° de Cédula Profesional')
        self.assertEqual(self.mx.ciudad_ejemplo, 'Ciudad de México')

    def test_precios_de_los_planes(self):
        self.assertEqual((self.mx.precio_basico, self.mx.precio_premium), (249, 429))
        self.assertLess(self.mx.precio_basico, self.mx.precio_premium)

    def test_ciudades_cargadas_aprobadas_y_con_slug_unico(self):
        ciudades = Ciudad.objects.filter(pais=self.mx)
        self.assertGreater(ciudades.count(), 90)
        self.assertFalse(ciudades.filter(aprobado=False).exists())
        slugs = list(ciudades.values_list('slug', flat=True))
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertNotIn('', slugs)
        nombres = set(ciudades.values_list('nombre', flat=True))
        for esperado in ('Ciudad de México', 'Guadalajara', 'Monterrey', 'Puebla', 'Querétaro', 'Mérida', 'Cancún', 'Tijuana'):
            self.assertIn(esperado, nombres)

    def test_la_migracion_se_puede_correr_de_nuevo_sin_duplicar_ciudades(self):
        from importlib import import_module
        from django.apps import apps
        antes = Ciudad.objects.filter(pais=self.mx).count()
        import_module('directorio.migrations.0023_activar_mexico').activar(apps, None)
        self.assertEqual(Ciudad.objects.filter(pais=self.mx).count(), antes)

    def test_aparece_en_el_hub_y_tiene_su_pagina(self):
        self.assertContains(self.client.get(reverse('hub')), 'México')
        self.assertEqual(self.client.get(reverse('pais_home', args=['mexico'])).status_code, 200)

    def test_se_puede_registrar_desde_la_pagina_de_mexico(self):
        resp = self.client.get(reverse('portal_registro', args=['mexico']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+52')  # el WhatsApp pide el código de México

    def test_los_textos_publicos_ya_nombran_a_mexico(self):
        for nombre in ('sobre_nosotros', 'terminos'):
            self.assertContains(self.client.get(reverse(nombre)), 'México', msg_prefix=nombre)


class TelefonoMexicoTests(TestCase):
    def test_lada_de_dos_digitos_cdmx_guadalajara_monterrey(self):
        for digitos in ('5512345678', '525512345678', '5215512345678'):
            self.assertEqual(_formatear_telefono(digitos, '52'), '+52 55 1234 5678', digitos)
        self.assertEqual(_formatear_telefono('3312345678', '52'), '+52 33 1234 5678')
        self.assertEqual(_formatear_telefono('8112345678', '52'), '+52 81 1234 5678')

    def test_lada_de_tres_digitos_resto_del_pais(self):
        self.assertEqual(_formatear_telefono('4421234567', '52'), '+52 442 123 4567')
        self.assertEqual(_formatear_telefono('524421234567', '52'), '+52 442 123 4567')

    def test_no_agrega_el_nueve_argentino(self):
        self.assertNotIn(' 9 ', _formatear_telefono('5512345678', '52'))

    def test_numero_raro_no_rompe(self):
        self.assertEqual(_formatear_telefono('12345', '52'), '+52 12345')

    def test_los_otros_paises_siguen_igual(self):
        self.assertEqual(_formatear_telefono('987654321', '51'), '+51 9 98765-4321')
