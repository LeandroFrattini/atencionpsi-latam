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
