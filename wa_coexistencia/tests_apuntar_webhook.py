"""Al conectar la cuenta de LATAM se le indica a Meta a qué dirección mandar sus avisos (override_callback_uri)."""
import os
from unittest import mock

from django.test import TestCase, override_settings

from .tests import _respuesta
from .views import _apuntar_avisos_a_esta_web, _conectar_cuenta

DIRECCION = 'https://atencionpsi.lat/wa-coexistencia/webhook/'


@override_settings(SITE_URL='https://atencionpsi.lat')
class ApuntarAvisosTests(TestCase):
    def test_los_datos_llevan_la_direccion_y_la_frase(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': 'frase-de-verificacion'}):
            self.assertEqual(_apuntar_avisos_a_esta_web(), {
                'override_callback_uri': DIRECCION, 'verify_token': 'frase-de-verificacion',
            })

    @override_settings(SITE_URL='https://atencionpsi.lat/')
    def test_no_duplica_la_barra_final(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': 'x'}):
            self.assertEqual(_apuntar_avisos_a_esta_web()['override_callback_uri'], DIRECCION)

    def test_sin_frase_no_se_apunta_nada(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': ''}):
            self.assertIsNone(_apuntar_avisos_a_esta_web())

    @mock.patch('wa_coexistencia.views.requests')
    def test_la_suscripcion_a_la_cuenta_incluye_la_direccion(self, pedidos):
        pedidos.post.return_value = _respuesta({'success': True})
        pedidos.get.return_value = _respuesta({'data': []})
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': 'frase-de-verificacion'}):
            cuenta = _conectar_cuenta('555', 'TOKEN-SECRETO')
        llamada = pedidos.post.call_args
        self.assertTrue(llamada.args[0].endswith('/555/subscribed_apps'))
        self.assertEqual(llamada.kwargs['data'], {'override_callback_uri': DIRECCION, 'verify_token': 'frase-de-verificacion'})
        self.assertEqual(llamada.kwargs['headers'], {'Authorization': 'Bearer TOKEN-SECRETO'})
        self.assertEqual(cuenta['avisos_a'], DIRECCION)

    @mock.patch('wa_coexistencia.views.requests')
    def test_sin_frase_se_suscribe_igual_pero_avisa_que_no_se_apunto(self, pedidos):
        pedidos.post.return_value = _respuesta({'success': True})
        pedidos.get.return_value = _respuesta({'data': []})
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': ''}):
            cuenta = _conectar_cuenta('555', 'TOKEN')
        self.assertIsNone(pedidos.post.call_args.kwargs['data'])
        self.assertIn('NO SE APUNTARON', cuenta['avisos_a'])

    @mock.patch('wa_coexistencia.views.requests')
    def test_la_respuesta_nunca_incluye_la_frase_ni_el_token(self, pedidos):
        pedidos.post.return_value = _respuesta({'success': True})
        pedidos.get.return_value = _respuesta({'data': []})
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': 'frase-secreta-123'}):
            cuenta = _conectar_cuenta('555', 'TOKEN-SECRETO')
        self.assertNotIn('frase-secreta-123', str(cuenta))
        self.assertNotIn('TOKEN-SECRETO', str(cuenta))
