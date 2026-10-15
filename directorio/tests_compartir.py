"""Botón "Compartir perfil" en el perfil público."""
from django.contrib.auth.models import User
from django.test import TestCase

from .models import Orientacion, Pais, Psicologo


class CompartirPerfilTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        usuario = User.objects.create_user('p@example.com', email='p@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(
            usuario=usuario, pais=pais, nombre='Lic. María Gonzales', matricula='1', whatsapp='51999999999', bio='bio',
            foto='psicologos/test.jpg', ciudad='Lima', suscripcion_activa=True, publicado_por_usuario=True,
        )
        self.psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0])

    def _perfil(self):
        return self.client.get(self.psi.url_publica)

    def test_el_perfil_tiene_el_boton_de_compartir_con_sus_opciones(self):
        resp = self._perfil()
        self.assertContains(resp, 'Compartir perfil')
        self.assertContains(resp, 'id="btn-compartir"')
        self.assertContains(resp, 'Copiar link')
        self.assertContains(resp, 'Enviar por WhatsApp')
        self.assertContains(resp, 'Enviar por email')

    def test_comparte_la_direccion_canonica_del_perfil(self):
        resp = self._perfil()
        self.assertContains(resp, f'data-url="http://testserver{self.psi.url_publica}"')
        self.assertContains(resp, 'https://wa.me/?text=')
        self.assertContains(resp, 'mailto:?subject=')

    def test_el_mensaje_de_whatsapp_lleva_el_nombre_y_el_link_codificados(self):
        html = self._perfil().content.decode()
        enlace = html[html.index('https://wa.me/?text='):]
        enlace = enlace[:enlace.index('"')]
        self.assertIn('Mir%C3%A1%20el%20perfil%20de%20Lic.%20Mar%C3%ADa%20Gonzales', enlace)
        self.assertIn('http%3A//testserver/peru/psicologo/maria-gonzales-', enlace)

    def test_el_script_esta_en_el_cuerpo_y_no_dentro_del_titulo(self):
        html = self._perfil().content.decode()
        titulo = html[html.index('<title>'):html.index('</title>')]
        self.assertNotIn('<script', titulo)
        self.assertGreater(html.index('Compartir perfil: en el celular'), html.index('<main>'))

    def test_la_tarjeta_de_sesiones_sigue_mostrando_el_precio_y_los_botones(self):
        Pais.objects.filter(slug='peru').update(muestra_precio_sesion=True, simbolo_moneda='S/')
        Psicologo.objects.filter(pk=self.psi.pk).update(precio_sesion=80)
        resp = self._perfil()
        self.assertContains(resp, 'Sesión: S/ 80')
        self.assertContains(resp, 'Escribir por WhatsApp')


class BanderaEnLasImagenesTests(TestCase):
    """En las imágenes de Instagram la ciudad lleva la bandera del país adelante
    (la bandera + "Lima"); ya no se escribe la sigla ("PE - Lima")."""

    def _psi(self, iso, ciudad, nombre='Psi Test'):
        pais, _ = Pais.objects.get_or_create(
            codigo_iso=iso, defaults=dict(nombre=iso, slug=iso.lower() + 'x', bandera_emoji='x', moneda='USD', activo=True),
        )
        usuario = User.objects.create_user(f'{iso}{ciudad}@example.com', email=f'{iso}{ciudad}@example.com', password='ClaveSegura123')
        return Psicologo.objects.create(usuario=usuario, pais=pais, nombre=nombre, matricula='1', whatsapp='1', ciudad=ciudad)

    def test_la_ciudad_va_sola_porque_el_pais_lo_dice_la_bandera(self):
        from directorio.generador_imagenes import _datos_atencion
        for iso, ciudad in {'PE': 'Lima', 'UY': 'Montevideo', 'CL': 'Santiago', 'AR': 'Bahía Blanca'}.items():
            psi = self._psi(iso, ciudad)
            self.assertEqual(_datos_atencion(psi)[1], [ciudad], iso)

    def test_sin_ciudad_queda_el_nombre_del_pais(self):
        from directorio.generador_imagenes import _datos_atencion
        psi = self._psi('PE', '')
        self.assertEqual(_datos_atencion(psi)[1], [psi.pais.nombre])

    # Países con sección armada: los activos y los que todavía están inactivos
    # (Colombia, Ecuador y México), para que al activarlos no falte ninguna bandera.
    PAISES_CON_BANDERA = ('PE', 'UY', 'CL', 'AR', 'CO', 'EC', 'MX')

    def test_hay_bandera_para_cada_pais_del_sitio_activo_o_no(self):
        from directorio.generador_imagenes import _bandera
        for iso in self.PAISES_CON_BANDERA:
            bandera = _bandera(self._psi(iso, 'X' + iso), 27)
            self.assertIsNotNone(bandera, iso)
            self.assertEqual(bandera.size[1], 27)
            self.assertGreater(bandera.size[0], 27)  # más ancha que alta

    def test_cada_pais_tiene_tambien_el_svg_que_usa_el_sitio(self):
        """La web (selector de país, registro) usa static/img/flags/<iso>.svg
        (Pais.bandera_svg); las imágenes de Instagram, el PNG de directorio/flags."""
        import os
        from django.conf import settings
        for iso in self.PAISES_CON_BANDERA:
            svg = os.path.join(settings.BASE_DIR, 'static', 'img', 'flags', iso.lower() + '.svg')
            self.assertTrue(os.path.exists(svg), svg)
            self.assertEqual(Pais(codigo_iso=iso).bandera_svg, f'img/flags/{iso.lower()}.svg')

    def test_un_pais_sin_png_no_rompe_y_solo_muestra_el_texto(self):
        from directorio.generador_imagenes import _bandera, generar_imagen_feed
        psi = self._psi('ZZ', 'Ciudad Rara')
        self.assertIsNone(_bandera(psi, 27))
        self.assertEqual(generar_imagen_feed(psi).size, (1080, 1350))

    def test_las_dos_imagenes_se_generan_con_el_prefijo(self):
        from directorio.generador_imagenes import generar_imagen_feed, generar_imagen_story
        psi = self._psi('UY', 'Montevideo')
        self.assertGreater(len(generar_imagen_story(psi).getvalue() if hasattr(generar_imagen_story(psi), 'getvalue') else b'x'), 0)
        self.assertIsNotNone(generar_imagen_feed(psi))
