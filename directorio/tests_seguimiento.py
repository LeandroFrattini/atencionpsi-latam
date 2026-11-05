"""Seguimiento por mail a quien todavía no publicó su perfil: uno a los 2 días y después cada 3, hasta 6."""
import datetime
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.enviar_recordatorios import MAX_SEGUIMIENTOS
from .models import Orientacion, Pais, Psicologo


def _correr(*args):
    salida = StringIO()
    call_command('enviar_recordatorios', *args, stdout=salida)
    return salida.getvalue()


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion, _ = Orientacion.objects.get_or_create(nombre='Sistémica')
        self.n = 0

    def psi(self, dias=3, completo=False, activo=True, **extra):
        self.n += 1
        email = f'psi{self.n}@example.com'
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123', is_active=activo)
        datos = dict(usuario=usuario, pais=self.pais, nombre=f'Ana Número{self.n}', whatsapp='51999111222')
        if completo:
            datos.update(matricula='123', bio='Trabajo con adultos.', foto='psicologos/test.jpg')
        datos.update(extra)
        psi = Psicologo.objects.create(**datos)
        if completo:
            psi.orientaciones.add(self.orientacion)
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=dias))
        return psi

    def recibidos(self):
        return [m.to[0] for m in mail.outbox]


class CuandoSeEnviaTests(_Base):
    def test_a_los_2_dias_recibe_el_primero_y_queda_anotado(self):
        psi = self.psi(dias=3)
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Tu perfil en Atención Psi está casi listo')
        psi.refresh_from_db()
        self.assertEqual(psi.seguimientos_enviados, 1)
        self.assertIsNotNone(psi.ultimo_seguimiento)

    def test_antes_de_los_2_dias_no(self):
        self.psi(dias=1)
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_el_siguiente_recien_a_los_3_dias_del_anterior(self):
        psi = self.psi(dias=10, seguimientos_enviados=1)
        Psicologo.objects.filter(pk=psi.pk).update(ultimo_seguimiento=timezone.now() - datetime.timedelta(days=2))
        _correr('--apply')
        self.assertEqual(mail.outbox, [])
        Psicologo.objects.filter(pk=psi.pk).update(ultimo_seguimiento=timezone.now() - datetime.timedelta(days=3, minutes=1))
        _correr('--apply')
        self.assertEqual([m.subject for m in mail.outbox], ['Te falta muy poco para publicar tu perfil'])

    def test_una_misma_corrida_no_manda_dos_veces_a_la_misma_persona(self):
        self.psi(dias=20)
        _correr('--apply')
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)

    def test_se_frena_despues_de_los_6_avisos(self):
        psi = self.psi(dias=60, seguimientos_enviados=MAX_SEGUIMIENTOS - 1)
        Psicologo.objects.filter(pk=psi.pk).update(ultimo_seguimiento=timezone.now() - datetime.timedelta(days=4))
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Último aviso sobre tu perfil en Atención Psi')
        self.assertIn('último aviso automático', mail.outbox[0].body)
        Psicologo.objects.filter(pk=psi.pk).update(ultimo_seguimiento=timezone.now() - datetime.timedelta(days=30))
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)   # ya no insiste

    def test_dry_run_muestra_pero_no_manda_ni_anota(self):
        psi = self.psi(dias=3)
        salida = _correr()
        self.assertIn(psi.nombre, salida)
        self.assertIn('aviso 1 de 6', salida)
        self.assertEqual(mail.outbox, [])
        psi.refresh_from_db()
        self.assertEqual(psi.seguimientos_enviados, 0)


class AQuienSeLeEnviaTests(_Base):
    def test_incompleto_completo_sin_plan_y_completo_sin_publicar(self):
        incompleto = self.psi()
        sin_plan = self.psi(completo=True)
        sin_publicar = self.psi(completo=True, suscripcion_activa=True)
        _correr('--apply')
        self.assertEqual(sorted(self.recibidos()), sorted([incompleto.usuario.email, sin_plan.usuario.email, sin_publicar.usuario.email]))

    def test_no_a_los_publicados(self):
        self.psi(completo=True, suscripcion_activa=True, publicado_por_usuario=True)
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_a_quien_no_confirmo_el_email_no_le_llega_el_seguimiento_comun_sino_el_de_confirmacion(self):
        # No puede entrar a armar el perfil, así que "completá tu perfil" no le sirve: se le manda un link nuevo
        # para confirmar (ver tests_seguimiento_confirmacion.py).
        self.psi(activo=False)
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Confirmá tu email', mail.outbox[0].subject)
        self.assertNotIn('Te falta:', mail.outbox[0].body)

    def test_no_a_quien_se_le_vencio_el_periodo_gratis(self):
        self.psi(completo=True, gratis_hasta=timezone.now() - datetime.timedelta(days=1))
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_no_a_quien_se_pauso(self):
        self.psi(no_enviar_seguimiento=True)
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_un_fundador_en_su_periodo_con_el_perfil_incompleto_si_y_sin_hablarle_de_pagar(self):
        self.psi(gratis_hasta=timezone.now() + datetime.timedelta(days=30))
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('no pagás nada', mail.outbox[0].body)


class ContenidoTests(_Base):
    def test_incompleto_dice_cuanto_hizo_que_le_falta_y_a_donde_ir(self):
        self.psi(whatsapp='')
        _correr('--apply')
        cuerpo = mail.outbox[0].body
        self.assertIn('Todavía no completaste tu perfil, ¡pero estás muy cerca!', cuerpo)
        self.assertIn('de 6 pasos hechos', cuerpo)
        self.assertIn('tu foto', cuerpo)
        self.assertIn('hasta ese momento no pagás nada', cuerpo)
        self.assertIn('/portal/perfil/', cuerpo)
        self.assertIn('Hola Ana', cuerpo)

    def test_completo_sin_plan_pide_elegir_el_plan(self):
        self.psi(completo=True)
        _correr('--apply')
        self.assertIn('Guardar y publicar', mail.outbox[0].body)   # todavía no tocó Publicar: ese es su siguiente paso
        self.assertIn('elegir tu plan', mail.outbox[0].body)
        self.assertNotIn('te falta', mail.outbox[0].body.lower())

    def test_completo_con_acceso_pide_tocar_publicar(self):
        self.psi(completo=True, suscripcion_activa=True)
        _correr('--apply')
        self.assertIn('tocá "Publicar mi perfil"', mail.outbox[0].body)

    def test_todos_traen_como_pausar_los_avisos(self):
        self.psi()
        _correr('--apply')
        self.assertIn('respondé este mail y los pausamos', mail.outbox[0].body)


class RobustezTests(_Base):
    def test_si_un_mail_falla_los_demas_salen_y_el_que_fallo_se_reintenta(self):
        primero, segundo = self.psi(), self.psi()
        reales = mail.send_mail

        def falla_el_primero(*args, **kwargs):
            if kwargs['recipient_list'] == [primero.usuario.email]:
                raise OSError('casilla inexistente')
            return reales(*args, **kwargs)

        with mock.patch('directorio.management.commands.enviar_recordatorios.send_mail', side_effect=falla_el_primero):
            with self.assertLogs('directorio.management.commands.enviar_recordatorios', level='ERROR'):
                _correr('--apply')
        self.assertEqual(self.recibidos(), [segundo.usuario.email])
        primero.refresh_from_db()
        self.assertEqual(primero.seguimientos_enviados, 0)   # no se contó: se reintenta en la próxima corrida
        _correr('--apply')
        self.assertEqual(self.recibidos(), [segundo.usuario.email, primero.usuario.email])


class AdminTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser('admin@example.com', 'admin@example.com', 'ClaveSegura123'))
        self.lista = reverse('admin:directorio_psicologo_changelist')

    def test_la_lista_muestra_cuantos_avisos_se_mandaron(self):
        self.psi(dias=3)
        _correr('--apply')
        resp = self.client.get(self.lista)
        self.assertContains(resp, 'Seguimiento')
        self.assertContains(resp, '1 aviso(s)')

    def test_pausar_y_reanudar_desde_el_admin(self):
        psi = self.psi(dias=3, seguimientos_enviados=2)
        self.client.post(self.lista, {'action': 'pausar_seguimiento_action', '_selected_action': [psi.pk]})
        psi.refresh_from_db()
        self.assertTrue(psi.no_enviar_seguimiento)
        self.assertContains(self.client.get(self.lista), 'Pausado')
        self.client.post(self.lista, {'action': 'reanudar_seguimiento_action', '_selected_action': [psi.pk]})
        psi.refresh_from_db()
        self.assertFalse(psi.no_enviar_seguimiento)
        self.assertEqual(psi.seguimientos_enviados, 0)

    def test_la_ficha_muestra_el_seguimiento(self):
        psi = self.psi()
        resp = self.client.get(reverse('admin:directorio_psicologo_change', args=[psi.pk]))
        self.assertContains(resp, 'No enviar avisos de seguimiento')
