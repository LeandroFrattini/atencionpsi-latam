"""Recorrido nuevo: registro, confirmar el email, ELEGIR PLAN Y PAGAR y recién después armar el perfil.
Rige solo para las cuentas creadas desde ahora (`plan_primero`): las que ya existían siguen como antes."""
import datetime
import re
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from directorio.models import Orientacion, Pais, Psicologo
from directorio.management.commands import enviar_recordatorios as recordatorios


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
            precio_basico=49, precio_premium=85, activo=True, codigo_telefono='51',
        )

    def psi(self, email='ana@example.com', plan_primero=True, activo=True, acceso=False, completo=False, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123', is_active=activo)
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre='Ana Pérez', matricula='', whatsapp='51999111222',
            plan_primero=plan_primero, exento_de_pago=acceso, **extra,
        )
        if completo:
            Psicologo.objects.filter(pk=psi.pk).update(matricula='123', bio='Mi bio', foto='psicologos/x.jpg')
            psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0])
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=5))
        return Psicologo.objects.get(pk=psi.pk)

    def link_de_confirmacion(self, usuario):
        return reverse('portal_verificar_email', args=[
            urlsafe_base64_encode(force_bytes(usuario.pk)), default_token_generator.make_token(usuario)])


class RegistroTests(_Base):
    def test_la_cuenta_nueva_nace_con_el_plan_primero(self):
        datos = dict(nombre='Nueva Psicóloga', email='nueva@example.com', whatsapp='51988888888',
                     password='ClaveSegura123', acepto_terminos='on')
        self.client.post(reverse('portal_registro', args=['peru']), datos)
        self.assertTrue(Psicologo.objects.get(usuario__username='nueva@example.com').plan_primero)

    def test_las_cuentas_que_ya_existian_siguen_sin_esa_regla(self):
        self.assertFalse(Psicologo._meta.get_field('plan_primero').default)

    def test_la_pagina_de_registro_cuenta_los_tres_pasos(self):
        resp = self.client.get(reverse('portal_registro', args=['peru']))
        self.assertContains(resp, 'elegís tu plan y activás la suscripción')
        self.assertContains(resp, 'armás tu perfil')


class ConfirmarEmailTests(_Base):
    def test_cuenta_nueva_confirma_y_va_a_elegir_el_plan(self):
        psi = self.psi(activo=False)
        resp = self.client.get(self.link_de_confirmacion(psi.usuario))
        self.assertRedirects(resp, reverse('portal_checkout'))
        psi.usuario.refresh_from_db()
        self.assertTrue(psi.usuario.is_active)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_cuenta_anterior_confirma_y_sigue_yendo_al_perfil(self):
        psi = self.psi(plan_primero=False, activo=False)
        resp = self.client.get(self.link_de_confirmacion(psi.usuario))
        self.assertRedirects(resp, reverse('portal_editar_perfil'))


class PortalBloqueadoHastaPagarTests(_Base):
    URLS = ('portal_dashboard', 'portal_editar_perfil', 'portal_vista_previa', 'portal_agenda', 'portal_turnos',
            'portal_pacientes', 'portal_paciente_nuevo')

    def test_sin_plan_todo_el_portal_lleva_a_elegirlo(self):
        self.client.force_login(self.psi().usuario)
        for nombre in self.URLS:
            resp = self.client.get(reverse(nombre))
            self.assertRedirects(resp, reverse('portal_checkout'), msg_prefix=nombre)

    def test_publicar_y_despublicar_tambien(self):
        self.client.force_login(self.psi(completo=True).usuario)
        for nombre in ('portal_publicar', 'portal_despublicar'):
            self.assertRedirects(self.client.post(reverse(nombre)), reverse('portal_checkout'), msg_prefix=nombre)

    def test_el_checkout_si_se_puede_ver_y_explica_el_paso(self):
        self.client.force_login(self.psi().usuario)
        resp = self.client.get(reverse('portal_checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Elegí tu plan para empezar')

    def test_al_entrar_se_le_explica_por_que(self):
        self.client.force_login(self.psi().usuario)
        resp = self.client.get(reverse('portal_editar_perfil'), follow=True)
        self.assertContains(resp, 'Para seguir, elegí tu plan')

    def test_con_plan_activo_entra_a_todo(self):
        psi = self.psi()
        psi.activar_suscripcion(dlocal_subscription_id='SUB-1', plan='basico')
        self.client.force_login(psi.usuario)
        for nombre in self.URLS:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

    def test_exenta_o_en_periodo_gratis_tambien_entran(self):
        exenta = self.psi('exenta@example.com', acceso=True)
        gratis = self.psi('gratis@example.com', gratis_hasta=timezone.now() + datetime.timedelta(days=30))
        for psi in (exenta, gratis):
            self.client.force_login(psi.usuario)
            self.assertEqual(self.client.get(reverse('portal_editar_perfil')).status_code, 200, psi.usuario.email)

    def test_las_cuentas_anteriores_arman_el_perfil_sin_pagar(self):
        self.client.force_login(self.psi(plan_primero=False).usuario)
        for nombre in self.URLS:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

    def test_destildar_la_regla_desde_el_admin_deja_entrar(self):
        psi = self.psi()
        Psicologo.objects.filter(pk=psi.pk).update(plan_primero=False)
        self.client.force_login(psi.usuario)
        self.assertEqual(self.client.get(reverse('portal_editar_perfil')).status_code, 200)

    def test_cambiar_la_contrasena_y_salir_siguen_funcionando(self):
        self.client.force_login(self.psi().usuario)
        self.assertEqual(self.client.get(reverse('portal_cambiar_contrasena')).status_code, 200)


class VolverDelPagoTests(_Base):
    def volver(self, psi):
        self.client.force_login(psi.usuario)
        with mock.patch('portal.views._dlocal_go_conectado', return_value=False):
            return self.client.get(reverse('portal_checkout_retorno'))

    def test_pago_confirmado_con_el_perfil_vacio_lleva_a_armarlo(self):
        psi = self.psi()
        psi.activar_suscripcion(dlocal_subscription_id='SUB-1', plan='basico')
        resp = self.volver(psi)
        self.assertRedirects(resp, reverse('portal_editar_perfil'))
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertEqual(resp.status_code, 200)

    def test_el_mensaje_celebra_el_pago_y_manda_a_armar_el_perfil(self):
        psi = self.psi()
        psi.activar_suscripcion(dlocal_subscription_id='SUB-1', plan='basico')
        self.client.force_login(psi.usuario)
        with mock.patch('portal.views._dlocal_go_conectado', return_value=False):
            resp = self.client.get(reverse('portal_checkout_retorno'), follow=True)
        self.assertContains(resp, 'Pago confirmado')
        self.assertContains(resp, 'armá tu perfil')

    def test_sin_pago_confirmado_sigue_esperando(self):
        psi = self.psi()
        resp = self.volver(psi)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estamos confirmando tu pago')


class MailsDeSeguimientoTests(_Base):
    def mensaje(self, **kwargs):
        return recordatorios._mensaje(self.psi(**kwargs))

    def test_cuenta_nueva_sin_plan_recibe_el_pedido_de_elegir_el_plan(self):
        texto = self.mensaje()
        self.assertIn('https://atencionpsi.lat/portal/checkout/', texto)
        self.assertIn('desde S/ 49 por mes', texto)
        self.assertNotIn('no pagás nada', texto)

    def test_con_el_perfil_a_medias_dice_que_lo_cargado_quedo_guardado(self):
        psi = self.psi()
        Psicologo.objects.filter(pk=psi.pk).update(bio='Mi bio')
        texto = recordatorios._mensaje(Psicologo.objects.get(pk=psi.pk))
        self.assertIn('quedó guardado', texto)
        self.assertIn('/portal/checkout/', texto)

    def test_el_asunto_habla_del_plan(self):
        asunto = recordatorios._asunto(self.psi())
        self.assertIn('plan', asunto.lower())

    def test_con_plan_activo_recibe_el_mail_de_siempre(self):
        texto = self.mensaje(acceso=True)
        self.assertIn('Te falta:', texto)
        self.assertNotIn('/portal/checkout/', texto)

    def test_la_cuenta_anterior_sigue_con_el_mail_de_antes(self):
        texto = self.mensaje(plan_primero=False)
        self.assertIn('Te falta:', texto)
        self.assertIn('no pagás nada', texto)

    def test_quien_nunca_confirmo_recibe_el_aviso_segun_su_regla(self):
        nueva = recordatorios._mensaje_confirmacion(self.psi(activo=False))
        vieja = recordatorios._mensaje_confirmacion(self.psi('vieja@example.com', plan_primero=False, activo=False))
        self.assertIn('elegís tu plan y activás tu suscripción', nueva)
        self.assertNotIn('no pagás nada', nueva)
        self.assertIn('no pagás nada', vieja)

    def test_el_comando_manda_el_mail_de_plan_a_la_cuenta_nueva(self):
        self.psi()
        call_command('enviar_recordatorios', '--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/portal/checkout/', mail.outbox[0].body)
        self.assertTrue(re.search(r'plan', mail.outbox[0].subject, re.I))
