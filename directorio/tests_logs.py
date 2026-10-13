"""Los errores 500 tienen que dejar el detalle en los logs (Render no lo hacía solo)."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse


class ErroresEnLosLogsTests(TestCase):
    def test_un_error_del_servidor_queda_registrado_con_su_detalle(self):
        self.client.raise_request_exception = False
        with mock.patch('directorio.views.mezcla_de_psicologos', side_effect=RuntimeError('falla de prueba')):
            with self.assertLogs('django.request', level='ERROR') as capturado:
                resp = self.client.get(reverse('hub'))
        self.assertEqual(resp.status_code, 500)
        self.assertTrue(any('falla de prueba' in linea for linea in capturado.output))

    def test_la_configuracion_manda_los_errores_a_la_consola(self):
        from django.conf import settings
        self.assertIn('consola', settings.LOGGING['loggers']['django.request']['handlers'])
