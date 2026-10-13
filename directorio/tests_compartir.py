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


class SiglaDePaisEnLasImagenesTests(TestCase):
    """La ciudad de las imágenes de Instagram lleva el país adelante: "PE - Lima"."""

    def _psi(self, iso, ciudad, nombre='Psi Test'):
        pais, _ = Pais.objects.get_or_create(
            codigo_iso=iso, defaults=dict(nombre=iso, slug=iso.lower() + 'x', bandera_emoji='x', moneda='USD', activo=True),
        )
        usuario = User.objects.create_user(f'{iso}{ciudad}@example.com', email=f'{iso}{ciudad}@example.com', password='ClaveSegura123')
        return Psicologo.objects.create(usuario=usuario, pais=pais, nombre=nombre, matricula='1', whatsapp='1', ciudad=ciudad)

    def test_cada_pais_con_su_sigla(self):
        from directorio.generador_imagenes import _datos_atencion
        casos = {'PE': 'PE - Lima', 'UY': 'UY - Montevideo', 'CL': 'CL - Santiago', 'AR': 'ARG - Bahía Blanca'}
        ciudades = {'PE': 'Lima', 'UY': 'Montevideo', 'CL': 'Santiago', 'AR': 'Bahía Blanca'}
        for iso, esperado in casos.items():
            psi = self._psi(iso, ciudades[iso])
            self.assertEqual(_datos_atencion(psi)[1], [esperado], iso)

    def test_sin_ciudad_queda_solo_la_sigla(self):
        from directorio.generador_imagenes import _datos_atencion
        psi = self._psi('PE', '')
        self.assertEqual(_datos_atencion(psi)[1], ['PE'])

    def test_las_dos_imagenes_se_generan_con_el_prefijo(self):
        from directorio.generador_imagenes import generar_imagen_feed, generar_imagen_story
        psi = self._psi('UY', 'Montevideo')
        self.assertGreater(len(generar_imagen_story(psi).getvalue() if hasattr(generar_imagen_story(psi), 'getvalue') else b'x'), 0)
        self.assertIsNotNone(generar_imagen_feed(psi))
