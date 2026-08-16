import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Formacion, Orientacion, Pais, Psicologo


class PsicologoPublicacionTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion = Orientacion.objects.create(nombre='Cognitivo Conductual (TCC)')
        self.usuario = User.objects.create_user('ana@example.com', password='ClaveSegura123')

    def _psicologo_completo(self, **overrides):
        datos = dict(
            usuario=self.usuario, pais=self.pais, nombre='Ana Test',
            matricula='12345', whatsapp='51999999999', bio='Trabajo con adultos.',
            foto='psicologos/test.jpg',
        )
        datos.update(overrides)
        p = Psicologo.objects.create(**datos)
        p.orientaciones.add(self.orientacion)
        return p

    def test_perfil_incompleto_sin_bio_no_puede_publicar(self):
        p = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Ana', matricula='1', whatsapp='51999999999')
        self.assertFalse(p.perfil_completo)
        self.assertFalse(p.puede_publicar)

    def test_perfil_completo_sin_pago_no_puede_publicar(self):
        p = self._psicologo_completo()
        self.assertTrue(p.perfil_completo)
        self.assertFalse(p.puede_publicar)

    def test_completo_y_pago_pero_sin_click_publicar_no_esta_publicado(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        self.assertTrue(p.puede_publicar)
        self.assertFalse(p.publicado)

    def test_publicado_por_usuario_mas_requisitos_publica(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        p.publicado_por_usuario = True
        p.save()
        self.assertTrue(p.publicado)

    def test_si_se_corta_la_suscripcion_se_despublica_solo(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        p.publicado_por_usuario = True
        p.save()
        self.assertTrue(p.publicado)

        p.suscripcion_activa = False
        p.save()
        self.assertFalse(p.publicado)

    def test_exenta_de_pago_no_necesita_suscripcion(self):
        p = self._psicologo_completo(exento_de_pago=True)
        self.assertTrue(p.puede_publicar)
        self.assertIsNotNone(p.fecha_pago_confirmado)


class BuscadorYDetalleTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN',
            activo=True, etiqueta_matricula='N° de Colegiatura (CPsP)',
        )
        self.orientacion = Orientacion.objects.create(nombre='Sistémica')
        self.usuario_publicado = User.objects.create_user('pub@example.com', password='ClaveSegura123')
        self.usuario_sin_publicar = User.objects.create_user('nopub@example.com', password='ClaveSegura123')

        self.publicado = Psicologo.objects.create(
            usuario=self.usuario_publicado, pais=self.pais, nombre='Publicada Test',
            matricula='999', whatsapp='51999999999', bio='Bio', foto='psicologos/test.jpg',
            suscripcion_activa=True, publicado_por_usuario=True,
        )
        self.publicado.orientaciones.add(self.orientacion)
        Formacion.objects.create(psicologo=self.publicado, descripcion='Licenciada en Psicología. UNC', orden=0)

        self.sin_publicar = Psicologo.objects.create(
            usuario=self.usuario_sin_publicar, pais=self.pais, nombre='Sin Publicar Test',
            matricula='888', whatsapp='51999999998',
        )

    def test_buscador_solo_muestra_publicados(self):
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, 'Publicada Test')
        self.assertNotContains(resp, 'Sin Publicar Test')

    def test_pais_inactivo_da_404(self):
        Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=False)
        resp = self.client.get(reverse('buscador_pais', args=['chile']))
        self.assertEqual(resp.status_code, 404)

    def test_detalle_de_publicado_muestra_formacion_y_etiqueta_correcta(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.publicado.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Licenciada en Psicología. UNC')
        self.assertContains(resp, 'N° de Colegiatura (CPsP)')

    def test_detalle_de_no_publicado_da_404(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.sin_publicar.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_pais_externo_redirige_afuera_en_vez_de_mostrar_buscador_vacio(self):
        Pais.objects.create(
            nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS',
            activo=True, es_externo=True, url_externa='https://atencionpsi.com.ar',
        )
        resp = self.client.get(reverse('buscador_pais', args=['argentina']))
        self.assertRedirects(resp, 'https://atencionpsi.com.ar', fetch_redirect_response=False)
