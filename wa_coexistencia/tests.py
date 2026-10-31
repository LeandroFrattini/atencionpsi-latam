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

    def test_espera_los_ids_de_meta_en_vez_de_un_tiempo_fijo(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('wa_coexistencia')).content.decode()
        self.assertIn('function enviar(code)', html)
        self.assertIn('sessionInfo.waba_id || Date.now() - t0 > 8000', html)
        self.assertIn("typeof data === 'string'", html)   # acepta el mensaje de Meta como texto o como objeto
        self.assertNotIn('}, 1500)', html)

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

    def test_falta_el_code(self):
        self.assertEqual(self._post({'waba_id': '123'}).status_code, 400)

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
        self.assertEqual(datos['ok'], True)
        self.assertEqual(datos['origen_waba'], 'navegador')
        self.assertEqual(datos['phone_number_id'], '777')
        self.assertEqual([c['waba_id'] for c in datos['cuentas']], ['555'])
        self.assertEqual(datos['cuentas'][0]['suscripcion'], {'success': True})
        self.assertNotIn('TOKEN-SECRETO', resp.content.decode())
        self.assertNotIn('secreto-de-prueba', resp.content.decode())
        # El canje usa el secreto del entorno y la suscripción va con el token en el encabezado.
        self.assertEqual(pedidos.get.call_args_list[0].kwargs['params']['client_secret'], 'secreto-de-prueba')
        self.assertEqual(pedidos.get.call_args_list[0].kwargs['params']['redirect_uri'], '')   # code del SDK de JS
        self.assertEqual(pedidos.post.call_args.kwargs['headers'], {'Authorization': 'Bearer TOKEN-SECRETO'})
        pedidos.get.assert_any_call(mock.ANY, headers={'Authorization': 'Bearer TOKEN-SECRETO'},
                                    params={'fields': 'id,verified_name,status'}, timeout=20)
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

    @mock.patch('wa_coexistencia.views.requests')
    def test_si_el_navegador_no_mando_el_waba_se_busca_en_el_token(self, pedidos):
        pedidos.RequestException = Exception

        def get(url, **kwargs):
            if url.endswith('/oauth/access_token'):
                return _respuesta({'access_token': 'TOKEN-SECRETO'})
            if url.endswith('/debug_token'):
                return _respuesta({'data': {'granular_scopes': [
                    {'scope': 'whatsapp_business_management', 'target_ids': ['900', '901']},
                    {'scope': 'whatsapp_business_messaging', 'target_ids': ['900']},
                    {'scope': 'business_management', 'target_ids': ['999']},
                ]}})
            return _respuesta({'data': [{'id': '111', 'verified_name': 'Atencion Psi', 'status': 'CONNECTED'}]})
        pedidos.get.side_effect = get
        pedidos.post.return_value = _respuesta({'success': True})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'secreto-de-prueba'}):
            resp = self._post({'code': 'abc'})
        datos = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(datos['ok'])
        self.assertEqual(datos['origen_waba'], 'token')
        self.assertEqual([c['waba_id'] for c in datos['cuentas']], ['900', '901'])   # sin repetidos y sin otros permisos
        self.assertEqual(datos['cuentas'][0]['numeros'], [{'id': '111', 'verified_name': 'Atencion Psi', 'status': 'CONNECTED'}])
        self.assertNotIn('TOKEN-SECRETO', resp.content.decode())
        self.assertNotIn('secreto-de-prueba', resp.content.decode())
        # debug_token se consulta con el token de la app (id|secreto), no con el del usuario.
        llamada = [c for c in pedidos.get.call_args_list if c.args[0].endswith('/debug_token')][0]
        self.assertEqual(llamada.kwargs['params']['access_token'], '895833073525544|secreto-de-prueba')

    @mock.patch('wa_coexistencia.views.requests')
    def test_si_el_token_no_trae_cuentas_lo_dice(self, pedidos):
        pedidos.RequestException = Exception
        pedidos.get.side_effect = lambda url, **kw: _respuesta(
            {'access_token': 'T'} if url.endswith('/oauth/access_token') else {'data': {'granular_scopes': []}})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['paso'], 'cuentas')
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.views.requests')
    def test_si_meta_pide_otro_redirect_uri_se_prueban_las_alternativas(self, pedidos):
        pedidos.RequestException = Exception
        intentos = []

        def get(url, **kwargs):
            if url.endswith('/oauth/access_token'):
                intentos.append(kwargs['params']['redirect_uri'])
                if kwargs['params']['redirect_uri'] == '':
                    return _respuesta({'error': {'code': 100, 'error_subcode': 36008, 'message': 'redirect_uri'}})
                return _respuesta({'access_token': 'TOKEN-SECRETO'})
            return _respuesta({'data': []})
        pedidos.get.side_effect = get
        pedidos.post.return_value = _respuesta({'success': True})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc', 'waba_id': '555'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(intentos[0], '')
        self.assertEqual(len(intentos), 2)
        self.assertTrue(resp.json()['redirect_uri'].endswith('/wa-coexistencia/'))

    @mock.patch('wa_coexistencia.views.requests')
    def test_otro_error_del_canje_no_reintenta(self, pedidos):
        pedidos.RequestException = Exception
        pedidos.get.return_value = _respuesta({'error': {'code': 100, 'error_subcode': 36007, 'message': 'code vencido'}})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc', 'waba_id': '555'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(pedidos.get.call_count, 1)

    def test_la_pagina_oculta_el_code_en_los_mensajes_de_diagnostico(self):
        self.client.get(reverse('wa_coexistencia'))
        html = self.client.get(reverse('wa_coexistencia')).content.decode()
        self.assertIn('code=(oculto)', html)

    @mock.patch('wa_coexistencia.views.requests')
    def test_un_error_de_dominio_191_tambien_prueba_la_siguiente_y_se_informa_cada_intento(self, pedidos):
        pedidos.RequestException = Exception
        pedidos.get.return_value = _respuesta({'error': {'code': 191, 'message': 'dominio no incluido'}})
        with mock.patch.dict(os.environ, {'META_APP_SECRET': 'x'}):
            resp = self._post({'code': 'abc', 'waba_id': '555'})
        datos = resp.json()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(datos['paso'], 'canje')
        self.assertEqual(len(datos['intentos']), 5)
        self.assertEqual(datos['intentos'][0]['redirect_uri'], '(vacío)')
        self.assertEqual(datos['intentos'][0]['codigo'], 191)
        self.assertIn('version', datos)
        self.assertNotIn('abc', json.dumps(datos['intentos']))   # el code no se devuelve

    def test_la_pagina_muestra_la_version_desplegada(self):
        html = self.client.get(reverse('wa_coexistencia')).content.decode()
        self.assertIn('versión 4', html)
