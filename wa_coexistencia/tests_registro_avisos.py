"""Registro de avisos del webhook de WhatsApp (diagnóstico) y el panel de estado del admin."""
import datetime
import os
from unittest import mock

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from .diagnostico import estado
from .models import ConfiguracionWhatsApp, ContactoWhatsApp, EventoWebhook
from .tests_webhook import ENTORNO, _aviso, _Base, _ok
from .webhook import MAX_EVENTOS
from .views import PHONE_NUMBER_ID


def _aviso_con_numero(numero_id, telefono='51999111222', wa_id='wamid.9'):
    datos = _aviso(telefono, wa_id)
    datos['entry'][0]['changes'][0]['value']['metadata'] = {'phone_number_id': numero_id}
    return datos


def _aviso_de_estado():
    return {'object': 'whatsapp_business_account', 'entry': [{'id': '1', 'changes': [{'field': 'messages', 'value': {
        'messaging_product': 'whatsapp', 'statuses': [{'id': 'wamid.x', 'status': 'delivered'}],
    }}]}]}


class RegistroDeAvisosTests(_Base):
    def _ultimo(self):
        return EventoWebhook.objects.order_by('-pk').first()

    def test_la_verificacion_correcta_queda_anotada(self):
        self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'frase-de-verificacion', 'hub.challenge': '1'})
        e = self._ultimo()
        self.assertEqual((e.metodo, e.resultado), ('GET', 'verificacion_ok'))

    def test_la_verificacion_con_frase_distinta_dice_por_que(self):
        self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'otra', 'hub.challenge': '1'})
        e = self._ultimo()
        self.assertEqual(e.resultado, 'verificacion_rechazada')
        self.assertIn('no coincide', e.detalle)

    def test_la_verificacion_sin_frase_en_el_servidor_lo_dice(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': ''}):
            self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'x', 'hub.challenge': '1'})
        self.assertIn('WHATSAPP_VERIFY_TOKEN no está configurado', self._ultimo().detalle)

    def test_firma_mala_queda_anotada_con_el_motivo_y_sigue_dando_403(self):
        resp = self.enviar_aviso(_aviso(), firma='sha256=' + '0' * 64)
        self.assertEqual(resp.status_code, 403)
        e = self._ultimo()
        self.assertEqual(e.resultado, 'firma_invalida')
        self.assertIn('META_APP_SECRET no es el secreto de la app', e.detalle)

    def test_sin_firma_y_sin_secreto_se_distinguen(self):
        self.enviar_aviso(_aviso(), firma='')
        self.assertIn('no trae la firma', self._ultimo().detalle)
        with mock.patch.dict(os.environ, {'META_APP_SECRET': ''}):
            self.enviar_aviso(_aviso())
        self.assertIn('META_APP_SECRET no está configurado', self._ultimo().detalle)

    def test_un_mensaje_valido_se_anota_con_cantidad_y_numero(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            pedidos.post.return_value = _ok()
            self.enviar_aviso(_aviso_con_numero(PHONE_NUMBER_ID))
        e = self._ultimo()
        self.assertEqual((e.resultado, e.mensajes, e.numero_id), ('recibido', 1, PHONE_NUMBER_ID))
        self.assertNotIn('NO es el configurado', e.detalle)

    def test_avisa_si_el_mensaje_llego_a_otro_numero(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            pedidos.post.return_value = _ok()
            self.enviar_aviso(_aviso_con_numero('999000111'))
        self.assertIn('NO es el configurado', self._ultimo().detalle)

    def test_los_avisos_de_estado_no_cuentan_como_mensajes(self):
        self.enviar_aviso(_aviso_de_estado())
        e = self._ultimo()
        self.assertEqual((e.resultado, e.mensajes), ('recibido', 0))
        self.assertIn('solo avisos de estado', e.detalle)

    def test_si_falla_la_respuesta_queda_marcado(self):
        with mock.patch('wa_coexistencia.webhook._atender', side_effect=RuntimeError('boom')):
            resp = self.enviar_aviso(_aviso())
        self.assertEqual(resp.status_code, 200)   # a Meta siempre 200 si la firma es válida
        self.assertEqual(self._ultimo().resultado, 'recibido_con_error')

    def test_no_guarda_telefonos_ni_texto_de_mensajes(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            pedidos.post.return_value = _ok()
            self.enviar_aviso(_aviso(telefono='51999111222'))
        for e in EventoWebhook.objects.all():
            texto = ' '.join([e.detalle, e.numero_id, e.agente])
            self.assertNotIn('51999111222', texto)
            self.assertNotIn('hola', texto)

    def test_si_el_registro_falla_el_webhook_responde_igual(self):
        with mock.patch('wa_coexistencia.webhook.EventoWebhook.objects') as manager:
            manager.create.side_effect = RuntimeError('base caída')
            resp = self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'frase-de-verificacion', 'hub.challenge': '77'})
        self.assertEqual((resp.status_code, resp.content), (200, b'77'))

    def test_guarda_solo_los_ultimos(self):
        EventoWebhook.objects.bulk_create([EventoWebhook(metodo='POST', resultado='recibido') for _ in range(MAX_EVENTOS + 150)])
        self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'x', 'hub.challenge': '1'})
        self.assertLessEqual(EventoWebhook.objects.count(), MAX_EVENTOS + 1)


class PanelDeEstadoTests(_Base):
    def _pendientes(self):
        return ' '.join(estado()['pendientes'])

    def test_sin_ningun_aviso_dice_que_meta_no_llamo_y_da_la_direccion(self):
        texto = self._pendientes()
        self.assertIn('Meta NO llamó nunca', texto)
        self.assertIn('/wa-coexistencia/webhook/', texto)
        self.assertIn('«messages»', texto)

    def test_faltan_variables(self):
        with mock.patch.dict(os.environ, {'META_APP_SECRET': '', 'WHATSAPP_TOKEN': ''}):
            self.assertIn('Falta cargar en Render', self._pendientes())
            self.assertIn('META_APP_SECRET, WHATSAPP_TOKEN', self._pendientes())

    def test_firma_mala_apunta_al_secreto_de_otra_app(self):
        self.enviar_aviso(_aviso(), firma='sha256=' + '0' * 64)
        texto = self._pendientes()
        self.assertIn('firma mala', texto)
        self.assertIn('MISMA app', texto)

    def test_mensajes_que_llegan_con_las_respuestas_apagadas(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            pedidos.post.return_value = _ok()
            self.enviar_aviso(_aviso())
        ConfiguracionWhatsApp.objects.filter(pk=1).update(activa=False)
        self.assertIn('las respuestas automáticas están apagadas', self._pendientes())

    def test_solo_avisos_de_estado(self):
        self.enviar_aviso(_aviso_de_estado())
        self.assertIn('solo con avisos de estado', self._pendientes())

    def test_error_de_meta_al_responder_se_muestra(self):
        ContactoWhatsApp.objects.create(telefono='51999000111', ultimo_mensaje=timezone.now(), ultimo_error='190: token vencido')
        self.enviar_aviso(_aviso_de_estado())
        self.assertIn('190: token vencido', self._pendientes())

    def test_todo_bien(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            pedidos.post.return_value = _ok()
            self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'frase-de-verificacion', 'hub.challenge': '1'})
            self.enviar_aviso(_aviso_con_numero(PHONE_NUMBER_ID))
        self.assertEqual(estado()['pendientes'], ['Todo en orden: llegan los avisos y no hay nada por corregir.'])

    def test_verificada_pero_sin_mensajes_no_dice_todo_en_orden(self):
        self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'frase-de-verificacion', 'hub.challenge': '1'})
        texto = self._pendientes()
        self.assertNotIn('Todo en orden', texto)
        self.assertIn('todavía no entró ningún mensaje', texto)
        self.assertIn('OTRO celular', texto)

    def test_nunca_muestra_los_valores_de_las_variables(self):
        texto = str(estado())
        for valor in ENTORNO.values():
            self.assertNotIn(valor, texto)


class AdminDelRegistroTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('duena', 'd@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin)

    def test_la_pantalla_muestra_el_panel_y_el_registro(self):
        self.enviar_aviso(_aviso(), firma='sha256=' + '0' * 64)
        resp = self.client.get(reverse('admin:wa_coexistencia_eventowebhook_changelist'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Qué revisar primero')
        self.assertContains(resp, 'RECHAZADO: firma inválida')
        self.assertContains(resp, '/wa-coexistencia/webhook/')

    def test_es_de_solo_lectura(self):
        self.assertEqual(self.client.get(reverse('admin:wa_coexistencia_eventowebhook_add')).status_code, 403)

    def test_un_usuario_comun_no_entra(self):
        self.client.logout()
        resp = self.client.get(reverse('admin:wa_coexistencia_eventowebhook_changelist'))
        self.assertEqual(resp.status_code, 302)
