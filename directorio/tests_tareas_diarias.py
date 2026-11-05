"""Tareas diarias (pagos + recordatorios) disparables desde afuera con una clave secreta, y el mail de
seguimiento que lleva a cada persona a su siguiente paso."""
import datetime
import os
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands import enviar_recordatorios as recordatorios
from .models import Orientacion, Pais, Psicologo

CLAVE = 'clave-secreta-de-prueba'


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
            precio_basico=49, precio_premium=85, activo=True,
        )

    def _psi(self, email='ana@example.com', hace_dias=5, completo=False, pidio_publicar=False, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(usuario=usuario, pais=self.peru, nombre='Ana Pérez', matricula='', whatsapp='51999', **extra)
        if completo:
            Psicologo.objects.filter(pk=psi.pk).update(matricula='123', bio='Mi bio', foto='psicologos/x.jpg',
                                                       publicado_por_usuario=pidio_publicar)
            psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0])
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=hace_dias))
        return Psicologo.objects.get(pk=psi.pk)


class DireccionSecretaTests(_Base):
    def url(self, token=CLAVE):
        return reverse('tareas_diarias', args=[token])

    def test_sin_clave_configurada_no_existe(self):
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': ''}):
            self.assertEqual(self.client.get(self.url('cualquiera')).status_code, 404)

    def test_con_otra_clave_no_existe_y_no_corre_nada(self):
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), mock.patch('directorio.views.call_command') as comando:
            self.assertEqual(self.client.get(self.url('otra-clave')).status_code, 404)
            comando.assert_not_called()

    def test_con_la_clave_correcta_corre_pagos_y_recordatorios(self):
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), mock.patch('directorio.views.call_command') as comando:
            resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        nombres = [c.args[0] for c in comando.call_args_list]
        self.assertEqual(nombres, ['sincronizar_suscripciones', 'enviar_recordatorios'])
        self.assertIn('--apply', comando.call_args_list[1].args)   # los recordatorios se mandan de verdad
        self.assertContains(resp, 'Recordatorios por mail')

    def test_solo_acepta_get_y_post(self):
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), mock.patch('directorio.views.call_command') as comando:
            self.assertEqual(self.client.head(self.url()).status_code, 405)
            self.assertEqual(self.client.put(self.url()).status_code, 405)
            comando.assert_not_called()
            self.assertEqual(self.client.post(self.url()).status_code, 200)

    def test_si_los_pagos_fallan_igual_se_mandan_los_recordatorios_y_avisa_con_500(self):
        self._psi(hace_dias=5)
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), \
                mock.patch('directorio.dlocal_go.conectado', return_value=False):
            resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 500)               # un monitor se entera de que algo falló
        self.assertContains(resp, 'FALLÓ', status_code=500)
        self.assertEqual(len(mail.outbox), 1)                 # pero el mail de seguimiento salió igual
        self.assertEqual(mail.outbox[0].to, ['ana@example.com'])

    def test_dos_corridas_a_la_vez_no_se_pisan(self):
        cache.set('tareas_diarias_en_curso', 1, 60)
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), mock.patch('directorio.views.call_command') as comando:
            resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 409)
        comando.assert_not_called()

    def test_libera_el_candado_al_terminar(self):
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), mock.patch('directorio.views.call_command'):
            self.client.get(self.url())
            self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_repetir_la_visita_no_repite_el_mail(self):
        self._psi(hace_dias=5)
        with mock.patch.dict(os.environ, {'TAREAS_DIARIAS_TOKEN': CLAVE}), \
                mock.patch('directorio.dlocal_go.conectado', return_value=False):
            self.client.get(self.url())
            self.client.get(self.url())
        self.assertEqual(len(mail.outbox), 1)


class MensajeDeSeguimientoTests(_Base):
    def _mensaje(self, **kwargs):
        return recordatorios._mensaje(self._psi(**kwargs))

    def test_quien_ya_pidio_publicar_va_directo_a_elegir_el_plan(self):
        texto = self._mensaje(completo=True, pidio_publicar=True)
        self.assertIn('https://atencionpsi.lat/portal/checkout/', texto)
        self.assertIn('desde S/ 49 por mes', texto)

    def test_quien_tiene_el_perfil_listo_pero_no_pidio_publicar_va_a_publicar(self):
        texto = self._mensaje(completo=True, pidio_publicar=False)
        self.assertIn('Guardar y publicar', texto)
        self.assertIn('https://atencionpsi.lat/portal/perfil/', texto)
        self.assertIn('no pagás nada', texto)
        self.assertNotIn('/checkout/', texto)

    def test_el_perfil_incompleto_sigue_diciendo_que_falta(self):
        texto = self._mensaje(completo=False)
        self.assertIn('Te falta:', texto)
        self.assertIn('https://atencionpsi.lat/portal/perfil/', texto)

    def test_sin_precio_cargado_no_dice_desde_cero(self):
        Pais.objects.filter(pk=self.peru.pk).update(precio_basico=0)
        texto = recordatorios._mensaje(Psicologo.objects.get(pk=self._psi(completo=True, pidio_publicar=True).pk))
        self.assertNotIn('desde S/', texto)
        self.assertNotIn('por mes', texto)
