"""Seguimiento a quien se registró y NUNCA confirmó el email: un mail con un link nuevo para confirmar."""
import datetime
import re
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.enviar_recordatorios import MAX_CONFIRMACIONES, pendientes_de_seguimiento
from .models import Pais, Psicologo


def _correr(*args):
    salida = StringIO()
    call_command('enviar_recordatorios', *args, stdout=salida)
    return salida.getvalue()


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True)

    def psi(self, email='fergie@example.com', activo=False, hace_dias=5, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123', is_active=activo)
        psi = Psicologo.objects.create(usuario=usuario, pais=self.chile, nombre='Fergie Hurtado', matricula='', whatsapp='56986766209', **extra)
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=hace_dias))
        return Psicologo.objects.get(pk=psi.pk)

    def pasar_dias(self, psi, dias):
        """Como si el último aviso hubiera salido hace `dias` días."""
        Psicologo.objects.filter(pk=psi.pk).update(ultimo_seguimiento=timezone.now() - datetime.timedelta(days=dias))


class MailParaQuienNoConfirmoTests(_Base):
    def test_recibe_un_mail_de_confirmacion_con_asunto_propio(self):
        self.psi()
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        self.assertEqual(enviado.to, ['fergie@example.com'])
        self.assertIn('Confirmá tu email', enviado.subject)
        self.assertIn('todavía no confirmaste tu email', enviado.body)
        self.assertIn('no pagás nada', enviado.body)
        self.assertIn('spam', enviado.body)

    def test_el_link_del_mail_confirma_la_cuenta_y_deja_entrar(self):
        psi = self.psi()
        _correr('--apply')
        link = re.search(r'https://atencionpsi\.lat(/portal/verificar/\S+/\S+/)', mail.outbox[0].body).group(1)
        resp = self.client.get(link)
        self.assertRedirects(resp, reverse('portal_editar_perfil'))
        psi.usuario.refresh_from_db()
        self.assertTrue(psi.usuario.is_active)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_el_mail_dice_el_pais_y_saluda_por_el_nombre(self):
        self.psi()
        _correr('--apply')
        self.assertIn('Hola Fergie', mail.outbox[0].body)
        self.assertIn('Atención Psi Chile', mail.outbox[0].body)

    def test_no_se_manda_antes_de_las_36_horas(self):
        self.psi(hace_dias=1)
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_es_un_aviso_cada_36_horas_y_se_frena_a_los_tres(self):
        psi = self.psi()
        for numero in range(1, MAX_CONFIRMACIONES + 1):
            _correr('--apply')
            self.assertEqual(len(mail.outbox), numero)
            self.pasar_dias(psi, 1)
            _correr('--apply')                                  # al día siguiente no repite
            self.assertEqual(len(mail.outbox), numero)
            self.pasar_dias(psi, 4)
        _correr('--apply')                                      # ya mandó los tres: no hay un cuarto
        self.assertEqual(len(mail.outbox), MAX_CONFIRMACIONES)
        self.assertIn('último aviso', mail.outbox[-1].body)
        self.assertIn('Último aviso', mail.outbox[-1].subject)

    def test_el_pausado_a_mano_no_recibe(self):
        self.psi(no_enviar_seguimiento=True)
        _correr('--apply')
        self.assertEqual(mail.outbox, [])

    def test_la_simulacion_los_lista_pero_no_manda_nada(self):
        psi = self.psi()
        texto = _correr()
        self.assertIn('fergie@example.com', texto)
        self.assertIn('Email sin confirmar', texto)
        self.assertEqual(mail.outbox, [])
        psi.refresh_from_db()
        self.assertEqual(psi.seguimientos_enviados, 0)

    def test_cada_aviso_trae_un_link_nuevo(self):
        psi = self.psi()
        _correr('--apply')
        self.pasar_dias(psi, 4)
        # Si el último mail se abrió (un login cambia el token), el link anterior ya no sirve: por eso se genera uno nuevo.
        _correr('--apply')
        links = [re.search(r'/portal/verificar/\S+/\S+/', m.body).group(0) for m in mail.outbox]
        self.assertEqual(len(links), 2)
        for link in links:
            self.assertRegex(link, r'^/portal/verificar/[\w-]+/[\w-]+/$')


class LosDemasSiguenIgualTests(_Base):
    def test_quien_ya_confirmo_y_no_armo_el_perfil_recibe_el_mail_de_siempre(self):
        self.psi(activo=True)
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('Confirmá tu email', mail.outbox[0].subject)
        self.assertNotIn('/portal/verificar/', mail.outbox[0].body)
        self.assertIn('Te falta:', mail.outbox[0].body)

    def test_el_no_confirmado_no_cuenta_para_el_tope_de_seis_de_los_demas(self):
        """Los que no confirmaron tienen su propio tope (3); los demás siguen con 6."""
        psi = self.psi(activo=True)
        Psicologo.objects.filter(pk=psi.pk).update(
            seguimientos_enviados=4, ultimo_seguimiento=timezone.now() - datetime.timedelta(days=10))
        self.assertEqual(list(pendientes_de_seguimiento()), [Psicologo.objects.get(pk=psi.pk)])
        sin_confirmar = self.psi(email='otro@example.com', activo=False)
        Psicologo.objects.filter(pk=sin_confirmar.pk).update(
            seguimientos_enviados=MAX_CONFIRMACIONES, ultimo_seguimiento=timezone.now() - datetime.timedelta(days=10))
        self.assertNotIn(sin_confirmar.pk, [p.pk for p in pendientes_de_seguimiento()])

    def test_al_confirmar_sigue_con_el_seguimiento_normal_sin_repetir_de_golpe(self):
        psi = self.psi()
        _correr('--apply')                                      # mail de confirmación
        User.objects.filter(pk=psi.usuario_id).update(is_active=True)
        _correr('--apply')                                      # no le toca todavía: el último aviso fue hoy
        self.assertEqual(len(mail.outbox), 1)
        self.pasar_dias(psi, 4)
        _correr('--apply')
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn('Confirmá tu email', mail.outbox[1].subject)
        self.assertIn('Te falta:', mail.outbox[1].body)
