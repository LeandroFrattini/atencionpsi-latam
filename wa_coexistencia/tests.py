import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


def _respuesta(datos, ok=True):
    r = mock.Mock()
    r.json.return_value = datos
    r.ok = ok
    return r


class AccesoTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff@example.com', password='ClaveSegura123', is_staff=True)
        self.comun = User.objects.create_user('comun@example.com', password='ClaveSegura123')

    def test_sin_login_manda_al_login_del_admin(self):
        resp = self.client.get(reverse('wa_coexistencia'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp['Location'])

    def test_un_profesional_comun_no_entra(self):
        self.client.force_login(self.comun)
        self.assertEqual(self.client.get(reverse('wa_coexistencia')).status_code, 302)
        resp = self.client.post(reverse('wa_coexistencia_callback'), '{}', content_type='application/json')
        self.assertEqual(resp.status_code, 302)

    def test_el_staff_ve_la_pagina_con_los_ids_de_la_app_y_recibe_la_cookie_csrf(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('wa_coexistencia'))
        self.assertContains(resp, "appId: '895833073525544'")
        self.assertContains(resp, "config_id: '2165478444074323'")
        self.assertIn('csrftoken', resp.cookies)
        self.assertNotContains(resp, 'META_APP_SECRET')

    def test_la_pagina_deja_abrir_la_ventana_de_meta(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('wa_coexistencia'))
        self.assertEqual(resp['Cross-Origin-Opener-Policy'], 'same-origin-allow-popups')


class CallbackTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff@example.com', password='ClaveSegura123', is_staff=True))
        self.url = reverse('wa_coexistencia_callback')

    def _post(self, datos):
        return self.client.post(self.url, json.dumps(datos), content_type='application/json')

    def test_solo_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_json_invalido(self):
        resp = self.client.post(self.url, 'no es json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_falta_el_code_o_el_waba(self):
        self.assertEqual(self._post({'waba_id': '123'}).status_code, 400)
        self.assertEqual(self._post({'code': 'abc'}).status_code, 400)

    def test_waba_id_con_caracteres_raros_se_rechaza(self):
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc', 'waba_id': '123/../me'})
        self.assertEqual(resp.status_code, 400)

    def test_sin_el_secreto_configurado_avisa_sin_llamar_a_meta(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop('META_APP_SECRET', None)
            with mock.patch('wa_coexistencia.views.requests') as pedidos:
                resp = self._post({'code': 'abc', 'waba_id': '123'})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('META_APP_SECRET', resp.json()['error'])
        pedidos.get.assert_not_called()

    @mock.patch('wa_coexistencia.views.requests')
    def test_camino_feliz_canjea_el_code_suscribe_y_no_devuelve_el_token(self, pedidos):
        pedidos.RequestException = Exception
        pedidos.get.return_value = _respuesta({'access_token': 'TOKEN-SECRETO'})
        pedidos.post.return_value = _respuesta({'success': True})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'secreto-de-prueba'}):
            resp = self._post({'code': 'abc', 'waba_id': '555', 'phone_number_id': '777'})
        datos = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(datos, {'ok': True, 'waba_id': '555', 'phone_number_id': '777', 'suscripcion': {'success': True}})
        self.assertNotIn('TOKEN-SECRETO', resp.content.decode())
        self.assertNotIn('secreto-de-prueba', resp.content.decode())
        # El canje usa el secreto del entorno y la suscripción va con el token en el encabezado.
        self.assertEqual(pedidos.get.call_args.kwargs['params']['client_secret'], 'secreto-de-prueba')
        self.assertEqual(pedidos.post.call_args.kwargs['headers'], {'Authorization': 'Bearer TOKEN-SECRETO'})
        self.assertTrue(pedidos.post.call_args.args[0].endswith('/555/subscribed_apps'))

    @mock.patch('wa_coexistencia.views.requests')
    def test_si_meta_rechaza_el_code_se_muestra_su_respuesta_y_no_se_suscribe(self, pedidos):
        pedidos.RequestException = Exception
        pedidos.get.return_value = _respuesta({'error': {'message': 'code vencido'}})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc', 'waba_id': '555'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['paso'], 'canje')
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.views.requests')
    def test_si_meta_no_responde_da_502_con_mensaje(self, pedidos):
        class Caido(Exception):
            pass
        pedidos.RequestException = Caido
        pedidos.get.side_effect = Caido('timeout')
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            with self.assertLogs('wa_coexistencia.views', level='ERROR'):
                resp = self._post({'code': 'abc', 'waba_id': '555'})
        self.assertEqual(resp.status_code, 502)
