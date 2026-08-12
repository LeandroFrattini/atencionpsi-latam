import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from directorio.models import Orientacion, Pais, Psicologo


class RegistroTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def test_registro_crea_cuenta_y_manda_a_checkout(self):
        resp = self.client.post(reverse('portal_registro', args=['peru']), {
            'nombre': 'Nueva Psicóloga',
            'email': 'nueva@example.com',
            'whatsapp': '51988888888',
            'password': 'ClaveSegura123',
        })
        self.assertRedirects(resp, reverse('portal_checkout'))
        self.assertTrue(User.objects.filter(username='nueva@example.com').exists())
        psicologo = Psicologo.objects.get(usuario__username='nueva@example.com')
        self.assertEqual(psicologo.pais, self.pais)
        self.assertFalse(psicologo.suscripcion_activa)

    def test_no_deja_registrar_email_repetido(self):
        User.objects.create_user('repetido@example.com', password='ClaveSegura123')
        resp = self.client.post(reverse('portal_registro', args=['peru']), {
            'nombre': 'Otra', 'email': 'repetido@example.com', 'whatsapp': '51988888888', 'password': 'ClaveSegura123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Psicologo.objects.filter(nombre='Otra').exists())


class SimularPagoTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.client.force_login(self.usuario)

    @override_settings(DEBUG=True)
    def test_simular_pago_activa_suscripcion_en_debug(self):
        resp = self.client.post(reverse('portal_simular_pago'))
        self.assertRedirects(resp, reverse('portal_dashboard'))
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.suscripcion_activa)
        self.assertIsNotNone(self.psicologo.fecha_pago_confirmado)

    @override_settings(DEBUG=False)
    def test_simular_pago_no_existe_fuera_de_debug(self):
        resp = self.client.post(reverse('portal_simular_pago'))
        self.assertEqual(resp.status_code, 404)


class PublicarDespublicarTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion = Orientacion.objects.create(nombre='Sistémica')
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519',
            bio='bio', foto='psicologos/test.jpg', suscripcion_activa=True,
        )
        self.psicologo.orientaciones.add(self.orientacion)
        self.client.force_login(self.usuario)

    def test_publicar_con_requisitos_completos_funciona(self):
        self.client.post(reverse('portal_publicar'))
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.publicado_por_usuario)
        self.assertTrue(self.psicologo.publicado)

    def test_publicar_sin_requisitos_no_publica(self):
        self.psicologo.suscripcion_activa = False
        self.psicologo.save()
        self.client.post(reverse('portal_publicar'))
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.publicado_por_usuario)

    def test_despublicar_apaga_el_perfil(self):
        self.psicologo.publicado_por_usuario = True
        self.psicologo.save()
        self.client.post(reverse('portal_despublicar'))
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.publicado_por_usuario)


class RecordatoriosCommandTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def _psicologo(self, email, **overrides):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        datos = dict(usuario=usuario, pais=self.pais, nombre='Test', matricula='1', whatsapp='519')
        datos.update(overrides)
        return Psicologo.objects.create(**datos)

    def test_recordatorio_de_pago_solo_a_los_que_pasaron_24hs_sin_pagar(self):
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        p_viejo = self._psicologo('viejo@example.com')
        Psicologo.objects.filter(pk=p_viejo.pk).update(fecha_alta=hace_2_dias)

        self._psicologo('reciente@example.com')  # se registró ahora, no le toca todavía

        from django.core.management import call_command
        call_command('enviar_recordatorios', '--apply')

        p_viejo.refresh_from_db()
        self.assertTrue(p_viejo.recordatorio_pago_enviado)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('viejo@example.com', mail.outbox[0].to)

    def test_dry_run_no_manda_nada(self):
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        p = self._psicologo('viejo@example.com')
        Psicologo.objects.filter(pk=p.pk).update(fecha_alta=hace_2_dias)

        from django.core.management import call_command
        call_command('enviar_recordatorios')

        p.refresh_from_db()
        self.assertFalse(p.recordatorio_pago_enviado)
        self.assertEqual(len(mail.outbox), 0)

    def test_recordatorio_de_perfil_a_pagos_sin_publicar(self):
        p = self._psicologo('pagado@example.com', suscripcion_activa=True)
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        Psicologo.objects.filter(pk=p.pk).update(fecha_pago_confirmado=hace_2_dias)

        from django.core.management import call_command
        call_command('enviar_recordatorios', '--apply')

        p.refresh_from_db()
        self.assertTrue(p.recordatorio_perfil_enviado)
        self.assertEqual(len(mail.outbox), 1)
