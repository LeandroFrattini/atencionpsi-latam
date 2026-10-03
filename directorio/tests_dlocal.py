"""Integración de cobro con dLocal Go. Ningún test llama a la API real: todo
lo que sale a la red se simula (mock) con respuestas con la misma forma que
documenta dLocal Go."""
import hashlib
import hmac
import io
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import dlocal_go, suscripciones
from .models import Pais, PlanDLocal, Psicologo

CLAVES = dict(DLOCAL_GO_API_KEY='api-key-de-prueba', DLOCAL_GO_SECRET_KEY='secret-de-prueba')


def _firmar(cuerpo: bytes) -> str:
    firma = hmac.new(b'secret-de-prueba', b'api-key-de-prueba' + cuerpo, hashlib.sha256).hexdigest()
    return f'V2-HMAC-SHA256, Signature: {firma}'


class BaseDLocalTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN',
            simbolo_moneda='S/', activo=True, precio_basico=49, precio_premium=85,
        )
        self.usuario = User.objects.create_user('ana@example.com', email='ana@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Ana Test', matricula='1', whatsapp='51999999999',
        )
        self.plan_basico = PlanDLocal.objects.create(
            pais=self.pais, plan='basico', dlocal_plan_id=11, plan_token='tok-b',
            subscribe_url='https://checkout.dlocalgo.com/validate/subscription/tok-b', monto=49, moneda='PEN',
        )
        self.plan_premium = PlanDLocal.objects.create(
            pais=self.pais, plan='premium', dlocal_plan_id=12, plan_token='tok-p',
            subscribe_url='https://checkout.dlocalgo.com/validate/subscription/tok-p', monto=85, moneda='PEN',
        )

    @staticmethod
    def sub(id=900, email='ana@example.com', status='CONFIRMED', active=True, **extra):
        return dict(id=id, client_email=email, status=status, active=active, created_at='2026-10-03T10:00:00', **extra)

    @staticmethod
    def ejec(status, creado='2026-10-03T10:00:00'):
        return dict(id=1, status=status, created_at=creado, order_id='DP-1')


@override_settings(**CLAVES)
class FirmaYClienteTests(TestCase):
    def test_firma_valida(self):
        cuerpo = b'{"payment_id":"DP-283"}'
        self.assertTrue(dlocal_go.firma_valida(cuerpo, _firmar(cuerpo)))

    def test_firma_de_otro_cuerpo_no_sirve(self):
        self.assertFalse(dlocal_go.firma_valida(b'{"payment_id":"DP-999"}', _firmar(b'{"payment_id":"DP-283"}')))

    def test_sin_header_o_mal_formado_no_sirve(self):
        cuerpo = b'{"payment_id":"DP-283"}'
        self.assertFalse(dlocal_go.firma_valida(cuerpo, ''))
        self.assertFalse(dlocal_go.firma_valida(cuerpo, 'Bearer algo'))

    def test_firma_hecha_con_otra_clave_no_sirve(self):
        cuerpo = b'{"payment_id":"DP-283"}'
        falsa = hmac.new(b'otra', b'api-key-de-prueba' + cuerpo, hashlib.sha256).hexdigest()
        self.assertFalse(dlocal_go.firma_valida(cuerpo, f'V2-HMAC-SHA256, Signature: {falsa}'))

    @override_settings(DLOCAL_GO_API_KEY='', DLOCAL_GO_SECRET_KEY='')
    def test_sin_claves_cargadas_nada_es_valido(self):
        cuerpo = b'{}'
        self.assertFalse(dlocal_go.firma_valida(cuerpo, _firmar(cuerpo)))

    @mock.patch('directorio.dlocal_go.requests.request')
    def test_el_pedido_lleva_bearer_user_agent_y_json(self, request):
        request.return_value = mock.Mock(status_code=200, json=lambda: {'ok': 1})
        dlocal_go.obtener_pago('DP-1')
        _, kwargs = request.call_args
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer api-key-de-prueba:secret-de-prueba')
        self.assertIn('AtencionPsiLatam', kwargs['headers']['User-Agent'])  # sin esto Cloudflare lo bloquea (error 1010)

    @mock.patch('directorio.dlocal_go.requests.request')
    def test_un_error_de_dlocal_se_convierte_en_DLocalError(self, request):
        request.return_value = mock.Mock(status_code=403, text='{"code":3001}')
        with self.assertRaises(dlocal_go.DLocalError) as cm:
            dlocal_go.obtener_pago('DP-1')
        self.assertEqual(cm.exception.status, 403)

    @mock.patch('directorio.dlocal_go.requests.request')
    def test_los_listados_recorren_todas_las_paginas(self, request):
        paginas = [
            mock.Mock(status_code=200, json=lambda: {'data': [{'id': 1}, {'id': 2}], 'total_pages': 2}),
            mock.Mock(status_code=200, json=lambda: {'data': [{'id': 3}], 'total_pages': 2}),
        ]
        request.side_effect = paginas
        self.assertEqual([s['id'] for s in dlocal_go.listar_suscripciones(11)], [1, 2, 3])

    @mock.patch('directorio.dlocal_go.requests.request')
    def test_listado_vacio_no_se_cuelga(self, request):
        request.return_value = mock.Mock(status_code=200, json=lambda: {'data': [], 'total_pages': 0})
        self.assertEqual(dlocal_go.listar_suscripciones(11), [])


@override_settings(**CLAVES)
class SincronizacionTests(BaseDLocalTests):
    def _sync(self, subs, ejecuciones):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', return_value=subs), \
                mock.patch('directorio.dlocal_go.listar_ejecuciones', return_value=ejecuciones):
            return suscripciones.sincronizar_psicologo(Psicologo.objects.get(pk=self.psi.pk))

    def test_pago_completado_activa_y_guarda_plan_y_suscripcion(self):
        self.assertEqual(self._sync([self.sub()], [self.ejec('COMPLETED')]), 'activa')
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.suscripcion_activa)
        self.assertEqual(self.psi.dlocal_subscription_id, '900')
        self.assertIsNotNone(self.psi.fecha_pago_confirmado)

    def test_el_mail_se_compara_sin_importar_mayusculas(self):
        self.assertEqual(self._sync([self.sub(email='ANA@Example.COM')], [self.ejec('COMPLETED')]), 'activa')

    def test_tambien_se_reconoce_por_el_external_id(self):
        s = self.sub(email='otro@mail.com', external_id=suscripciones.external_id_de(self.psi))
        self.assertEqual(self._sync([s], [self.ejec('COMPLETED')]), 'activa')

    def test_suscripcion_de_otra_persona_no_activa_a_nadie(self):
        self.assertEqual(self._sync([self.sub(email='otra@mail.com')], [self.ejec('COMPLETED')]), 'sin_suscripcion')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_elegi_el_plan_pero_todavia_no_pago_queda_pendiente(self):
        self.assertEqual(self._sync([self.sub(status='CREATED')], []), 'pendiente')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_cobro_pendiente_no_activa(self):
        self.assertEqual(self._sync([self.sub()], [self.ejec('PENDING')]), 'pendiente')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_primer_pago_rechazado_nunca_activa(self):
        self.assertEqual(self._sync([self.sub()], [self.ejec('DECLINED')]), 'declinada')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def _activa_con_rechazo_reciente(self, hace):
        self.psi.activar_suscripcion(dlocal_subscription_id='900', plan='basico')
        Psicologo.objects.filter(pk=self.psi.pk).update(pago_declinado_desde=timezone.now() - hace)
        ejec = [self.ejec('COMPLETED', '2026-09-03T10:00:00'), self.ejec('DECLINED', '2026-10-03T10:00:00')]
        return self._sync([self.sub()], ejec)

    def test_un_rechazo_reciente_no_despublica_todavia(self):
        self.assertEqual(self._activa_con_rechazo_reciente(timedelta(hours=6)), 'en_gracia')
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.suscripcion_activa)

    def test_el_primer_rechazo_arranca_el_contador_de_gracia(self):
        self.psi.activar_suscripcion(dlocal_subscription_id='900', plan='basico')
        ejec = [self.ejec('COMPLETED', '2026-09-03T10:00:00'), self.ejec('DECLINED', '2026-10-03T10:00:00')]
        self.assertEqual(self._sync([self.sub()], ejec), 'en_gracia')
        self.psi.refresh_from_db()
        self.assertIsNotNone(self.psi.pago_declinado_desde)

    def test_pasados_los_dias_de_gracia_se_despublica_solo(self):
        self.assertEqual(self._activa_con_rechazo_reciente(timedelta(days=5)), 'declinada')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)
        self.assertFalse(self.psi.publicado)

    def test_si_vuelve_a_pagar_se_limpia_el_rechazo(self):
        self.psi.activar_suscripcion(dlocal_subscription_id='900', plan='basico')
        Psicologo.objects.filter(pk=self.psi.pk).update(pago_declinado_desde=timezone.now() - timedelta(days=1))
        ejec = [self.ejec('DECLINED', '2026-10-03T10:00:00'), self.ejec('COMPLETED', '2026-10-04T10:00:00')]
        self.assertEqual(self._sync([self.sub()], ejec), 'activa')
        self.psi.refresh_from_db()
        self.assertIsNone(self.psi.pago_declinado_desde)
        self.assertTrue(self.psi.suscripcion_activa)

    def test_suscripcion_dada_de_baja_despublica(self):
        self.psi.activar_suscripcion(dlocal_subscription_id='900', plan='basico')
        self.assertEqual(self._sync([self.sub(active=False)], [self.ejec('COMPLETED')]), 'baja')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_el_profesional_exento_no_consulta_la_api(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(exento_de_pago=True)
        with mock.patch('directorio.dlocal_go.listar_suscripciones') as listar:
            self.assertEqual(suscripciones.sincronizar_psicologo(Psicologo.objects.get(pk=self.psi.pk)), 'exento')
            listar.assert_not_called()

    def test_si_se_suscribio_dos_veces_vale_la_mas_reciente(self):
        vieja = self.sub(id=1, active=False)
        vieja['created_at'] = '2026-01-01T10:00:00'
        nueva = self.sub(id=2)
        self.assertEqual(self._sync([vieja, nueva], [self.ejec('COMPLETED')]), 'activa')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.dlocal_subscription_id, '2')

    def test_sincronizar_todos_arma_el_resumen(self):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', return_value=[self.sub()]), \
                mock.patch('directorio.dlocal_go.listar_ejecuciones', return_value=[self.ejec('COMPLETED')]):
            self.assertEqual(suscripciones.sincronizar_todos(), {'activa': 1})


@override_settings(**CLAVES)
class CheckoutRealTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_conectado_muestra_ir_a_pagar_y_no_el_modo_de_prueba(self):
        resp = self.client.get(reverse('portal_checkout'))
        self.assertContains(resp, 'Ir a pagar')
        self.assertNotContains(resp, 'modo de prueba')
        self.assertContains(resp, 'S/ 49')

    def test_elegir_un_plan_manda_al_link_de_pago_con_mail_y_external_id(self):
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'premium'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('https://checkout.dlocalgo.com/validate/subscription/tok-p?'))
        self.assertIn('email=ana%40example.com', resp['Location'])
        self.assertIn(f'external_id=psi-{self.psi.pk}', resp['Location'])
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.plan, 'premium')
        self.assertFalse(self.psi.suscripcion_activa)   # elegir no es pagar

    def test_plan_inexistente_no_manda_a_ningun_lado(self):
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'platino'})
        self.assertRedirects(resp, reverse('portal_checkout'))

    def test_pais_sin_planes_creados_avisa_que_todavia_no_esta_disponible(self):
        PlanDLocal.objects.all().delete()
        resp = self.client.get(reverse('portal_checkout'))
        self.assertContains(resp, 'El cobro todavía no está disponible')
        self.assertNotContains(resp, 'Ir a pagar')

    def test_el_pago_simulado_ya_no_existe_con_claves_cargadas(self):
        resp = self.client.post(reverse('portal_simular_pago'), {'plan': 'basico'})
        self.assertEqual(resp.status_code, 404)
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_si_dlocal_vuelve_con_error_se_muestra_el_aviso(self):
        resp = self.client.get(reverse('portal_checkout') + '?error=1')
        self.assertContains(resp, 'No pudimos procesar el pago')

    def test_ya_suscripta_no_vuelve_a_pagar(self):
        self.psi.activar_suscripcion(plan='basico')
        self.assertRedirects(self.client.get(reverse('portal_checkout')), reverse('portal_dashboard'))


@override_settings(**CLAVES)
class RetornoDePagoTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_llegar_a_la_pagina_de_exito_sin_haber_pagado_no_activa_a_nadie(self):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', return_value=[]):
            resp = self.client.get(reverse('portal_checkout_retorno') + f'?external_id=psi-{self.psi.pk}')
        self.assertContains(resp, 'Estamos confirmando tu pago')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_si_dlocal_confirma_se_activa_y_va_al_panel(self):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', return_value=[self.sub()]), \
                mock.patch('directorio.dlocal_go.listar_ejecuciones', return_value=[self.ejec('COMPLETED')]):
            resp = self.client.get(reverse('portal_checkout_retorno'))
        self.assertRedirects(resp, reverse('portal_dashboard'))
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.suscripcion_activa)

    def test_si_la_api_falla_no_rompe_la_pagina(self):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', side_effect=dlocal_go.DLocalError('caído')):
            resp = self.client.get(reverse('portal_checkout_retorno'))
        self.assertEqual(resp.status_code, 200)

    def test_despues_de_muchos_intentos_deja_de_recargarse(self):
        with mock.patch('directorio.dlocal_go.listar_suscripciones', return_value=[]):
            resp = self.client.get(reverse('portal_checkout_retorno') + '?n=10')
        self.assertContains(resp, 'todavía no figura confirmado')
        self.assertNotContains(resp, 'http-equiv="refresh"')


@override_settings(**CLAVES)
class WebhookTests(BaseDLocalTests):
    def _post(self, cuerpo, firmar=True, firma=None):
        extra = {}
        if firmar:
            extra['HTTP_AUTHORIZATION'] = firma or _firmar(cuerpo)
        return self.client.post(reverse('portal_dlocal_webhook'), data=cuerpo, content_type='application/json', **extra)

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get(reverse('portal_dlocal_webhook')).status_code, 405)

    def test_sin_firma_o_con_firma_falsa_se_rechaza(self):
        cuerpo = b'{"payment_id":"DP-1"}'
        self.assertEqual(self._post(cuerpo, firmar=False).status_code, 403)
        self.assertEqual(self._post(cuerpo, firma='V2-HMAC-SHA256, Signature: 0000').status_code, 403)

    def test_firma_valida_busca_el_pago_y_sincroniza_a_quien_pago(self):
        cuerpo = b'{"payment_id":"DP-1"}'
        with mock.patch('directorio.dlocal_go.obtener_pago', return_value={'payer': {'email': 'Ana@Example.com'}}), \
                mock.patch('directorio.suscripciones.sincronizar_psicologo') as sync:
            resp = self._post(cuerpo)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sync.call_args[0][0].pk, self.psi.pk)

    def test_pago_de_alguien_que_no_es_profesional_responde_200_sin_sincronizar(self):
        cuerpo = b'{"payment_id":"DP-1"}'
        with mock.patch('directorio.dlocal_go.obtener_pago', return_value={'payer': {'email': 'nadie@mail.com'}}), \
                mock.patch('directorio.suscripciones.sincronizar_psicologo') as sync:
            self.assertEqual(self._post(cuerpo).status_code, 200)
            sync.assert_not_called()

    def test_si_dlocal_falla_responde_502_para_que_reintente(self):
        cuerpo = b'{"payment_id":"DP-1"}'
        with mock.patch('directorio.dlocal_go.obtener_pago', side_effect=dlocal_go.DLocalError('caído')):
            self.assertEqual(self._post(cuerpo).status_code, 502)

    def test_cuerpo_sin_payment_id_o_roto_es_400(self):
        self.assertEqual(self._post(b'{}').status_code, 400)
        self.assertEqual(self._post(b'esto no es json').status_code, 400)


@override_settings(**CLAVES)
class ComandosTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        PlanDLocal.objects.all().delete()

    def _correr(self, *args):
        salida = io.StringIO()
        call_command(*args, stdout=salida)
        return salida.getvalue()

    def test_crear_planes_sin_apply_solo_muestra_y_no_toca_nada(self):
        with mock.patch('directorio.dlocal_go.crear_plan') as crear:
            texto = self._correr('crear_planes_dlocal')
            crear.assert_not_called()
        self.assertEqual(PlanDLocal.objects.count(), 0)
        self.assertIn('CREARÍA', texto)

    def test_crear_planes_con_apply_crea_basico_y_premium_en_moneda_local(self):
        respuestas = iter([
            {'id': 21, 'plan_token': 'tb', 'subscribe_url': 'https://checkout.dlocalgo.com/validate/subscription/tb'},
            {'id': 22, 'plan_token': 'tp', 'subscribe_url': 'https://checkout.dlocalgo.com/validate/subscription/tp'},
        ])
        with mock.patch('directorio.dlocal_go.crear_plan', side_effect=lambda **kw: next(respuestas)) as crear:
            self._correr('crear_planes_dlocal', '--apply')
        self.assertEqual(PlanDLocal.objects.count(), 2)
        montos = sorted((c.kwargs['monto'], c.kwargs['moneda'], c.kwargs['pais_iso']) for c in crear.call_args_list)
        self.assertEqual(montos, [(49, 'PEN', 'PE'), (85, 'PEN', 'PE')])
        kw = crear.call_args_list[0].kwargs
        self.assertTrue(kw['success_url'].endswith(reverse('portal_checkout_retorno')))
        self.assertTrue(kw['notification_url'].endswith(reverse('portal_dlocal_webhook')))

    def test_crear_planes_es_seguro_de_repetir(self):
        PlanDLocal.objects.create(
            pais=self.pais, plan='basico', dlocal_plan_id=1, plan_token='x', subscribe_url='https://x.com/a', monto=49, moneda='PEN',
        )
        with mock.patch('directorio.dlocal_go.crear_plan', return_value={
            'id': 2, 'plan_token': 'y', 'subscribe_url': 'https://x.com/b',
        }) as crear:
            self._correr('crear_planes_dlocal', '--apply')
        self.assertEqual(crear.call_count, 1)   # solo el Premium, que faltaba
        self.assertEqual(PlanDLocal.objects.count(), 2)

    def test_crear_planes_omite_un_pais_sin_precio_cargado(self):
        Pais.objects.filter(pk=self.pais.pk).update(precio_premium=0)
        with mock.patch('directorio.dlocal_go.crear_plan', return_value={
            'id': 2, 'plan_token': 'y', 'subscribe_url': 'https://x.com/b',
        }) as crear:
            self._correr('crear_planes_dlocal', '--apply')
        self.assertEqual(crear.call_count, 1)

    @override_settings(DLOCAL_GO_API_KEY='', DLOCAL_GO_SECRET_KEY='')
    def test_sin_claves_el_apply_falla_con_mensaje_claro(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._correr('crear_planes_dlocal', '--apply')

    def test_sincronizar_suscripciones_muestra_el_resumen(self):
        with mock.patch('directorio.suscripciones.sincronizar_todos', return_value={'activa': 2, 'baja': 1}):
            texto = self._correr('sincronizar_suscripciones')
        self.assertIn('activa: 2', texto)
        self.assertIn('baja: 1', texto)


@override_settings(**CLAVES)
class BajaDesdeElAdminTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser('admin_baja', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)
        self.psi.activar_suscripcion(dlocal_subscription_id='900', plan='basico')

    def _accion(self, **extra):
        return self.client.post(reverse('admin:directorio_psicologo_changelist'), {
            'action': 'dar_de_baja_dlocal_action', '_selected_action': [self.psi.pk], **extra,
        })

    def test_primero_pide_confirmacion_y_no_cancela_nada(self):
        with mock.patch('directorio.dlocal_go.desactivar_suscripcion') as baja:
            resp = self._accion()
            baja.assert_not_called()
        self.assertContains(resp, 'No se puede deshacer')
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.suscripcion_activa)

    def test_confirmada_cancela_en_dlocal_y_despublica(self):
        with mock.patch('directorio.dlocal_go.desactivar_suscripcion') as baja:
            self._accion(apply='1')
        baja.assert_called_once_with(11, 900)   # plan básico (id 11), suscripción 900
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.suscripcion_activa)

    def test_si_dlocal_falla_el_profesional_sigue_activo(self):
        with mock.patch('directorio.dlocal_go.desactivar_suscripcion', side_effect=dlocal_go.DLocalError('caído')):
            self._accion(apply='1')
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.suscripcion_activa)

    def test_una_suscripcion_de_prueba_no_se_manda_a_cancelar(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(dlocal_subscription_id='SIMULADO-DEV')
        with mock.patch('directorio.dlocal_go.desactivar_suscripcion') as baja:
            self._accion(apply='1')
            baja.assert_not_called()
