"""Botones del admin para sincronizar con dLocal Go y mandar recordatorios (sin consola ni cron)."""
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import dlocal_go
from .models import Pais, Psicologo

CLAVES = dict(DLOCAL_GO_API_KEY='api-key-de-prueba', DLOCAL_GO_SECRET_KEY='secret-de-prueba')


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.admin_user = User.objects.create_superuser('admin_tareas', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)
        self.url_sync = reverse('admin:directorio_psicologo_sincronizar')
        self.url_rec = reverse('admin:directorio_psicologo_recordatorios')


class BotonesEnElInicioTests(_Base):
    def test_el_inicio_del_admin_tiene_los_tres_botones(self):
        resp = self.client.get(reverse('admin:index'))
        self.assertContains(resp, 'Sincronizar con dLocal Go')
        self.assertContains(resp, 'Ver recordatorios pendientes')
        self.assertContains(resp, 'Enviar recordatorios')
        self.assertContains(resp, self.url_sync)
        self.assertContains(resp, self.url_rec)

    def test_quien_no_es_admin_no_puede_usarlos(self):
        self.client.logout()
        for url in (self.url_sync, self.url_rec):
            resp = self.client.post(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn('/admin/login/', resp['Location'])

    def test_solo_aceptan_post(self):
        for url in (self.url_sync, self.url_rec):
            self.assertEqual(self.client.get(url).status_code, 405)


@override_settings(**CLAVES)
class SincronizarTests(_Base):
    def test_muestra_el_resumen_en_castellano(self):
        with mock.patch('directorio.suscripciones.sincronizar_todos', return_value={'activa': 2, 'baja': 1}):
            resp = self.client.post(self.url_sync)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Con la suscripción al día')
        self.assertContains(resp, 'Dados de baja')
        self.assertNotContains(resp, 'activa: ')

    def test_sin_suscripciones_lo_dice(self):
        with mock.patch('directorio.suscripciones.sincronizar_todos', return_value={}):
            resp = self.client.post(self.url_sync)
        self.assertContains(resp, 'Todavía no hay suscripciones')

    def test_si_dlocal_falla_avisa_sin_romper(self):
        with mock.patch('directorio.suscripciones.sincronizar_todos', side_effect=dlocal_go.DLocalError('sin red')):
            resp = self.client.post(self.url_sync)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No se pudo hablar con dLocal Go')

    @override_settings(DLOCAL_GO_API_KEY='', DLOCAL_GO_SECRET_KEY='')
    def test_sin_claves_explica_que_faltan(self):
        resp = self.client.post(self.url_sync)
        self.assertContains(resp, 'Faltan las claves de dLocal Go')


class RecordatoriosTests(_Base):
    def _psi_sin_pagar(self):
        usuario = User.objects.create_user('p@example.com', email='p@example.com', password='ClaveSegura123')
        psi = Psicologo.objects.create(usuario=usuario, pais=self.pais, nombre='Psi Pendiente', matricula='1', whatsapp='1')
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=3))
        return psi

    def test_simular_muestra_a_quien_se_le_mandaria_y_no_manda_nada(self):
        self._psi_sin_pagar()
        resp = self.client.post(self.url_rec, {'modo': 'simular'})
        self.assertContains(resp, 'Psi Pendiente')
        self.assertContains(resp, 'todavía no se mandó nada')
        self.assertContains(resp, 'Enviar estos recordatorios ahora')   # botón para confirmar desde ahí
        self.assertEqual(mail.outbox, [])

    def test_enviar_manda_los_mails_y_no_los_repite(self):
        self._psi_sin_pagar()
        resp = self.client.post(self.url_rec, {'modo': 'enviar'})
        self.assertContains(resp, 'Recordatorios enviados')
        self.assertNotContains(resp, 'Enviar estos recordatorios ahora')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['p@example.com'])
        self.client.post(self.url_rec, {'modo': 'enviar'})
        self.assertEqual(len(mail.outbox), 1)   # cada aviso sale una sola vez por persona

    def test_sin_modo_se_comporta_como_simulacion(self):
        self._psi_sin_pagar()
        self.client.post(self.url_rec)
        self.assertEqual(mail.outbox, [])
