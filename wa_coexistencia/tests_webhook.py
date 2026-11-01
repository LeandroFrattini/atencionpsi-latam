import datetime
import hashlib
import hmac
import json
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from directorio.models import Pais

from .models import ConfiguracionWhatsApp, ContactoWhatsApp, MensajeRecibido, RespuestaPais
from .webhook import pais_del_telefono

SECRETO = 'secreto-de-prueba'
MEDIA_PRUEBAS = tempfile.mkdtemp(prefix='wa-pruebas-')
ENTORNO = {'META_APP_SECRET': SECRETO, 'WHATSAPP_TOKEN': 'TOKEN-X', 'WHATSAPP_VERIFY_TOKEN': 'frase-de-verificacion'}


def _aviso(telefono='51999111222', wa_id='wamid.1', tipo='text'):
    return {'object': 'whatsapp_business_account', 'entry': [{'id': '1', 'changes': [{'field': 'messages', 'value': {
        'messaging_product': 'whatsapp',
        'messages': [{'from': telefono, 'id': wa_id, 'type': tipo, 'text': {'body': 'hola'}}],
    }}]}]}


def _ok():
    r = mock.Mock()
    r.ok = True
    r.status_code = 200
    return r


class _Base(TestCase):
    def setUp(self):
        entorno = mock.patch.dict(os.environ, ENTORNO)
        entorno.start()
        self.addCleanup(entorno.stop)
        self.addCleanup(shutil.rmtree, MEDIA_PRUEBAS, ignore_errors=True)
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN',
                                        activo=True, codigo_telefono='51')
        self.uruguay = Pais.objects.create(nombre='Uruguay', slug='uruguay', codigo_iso='UY', bandera_emoji='🇺🇾',
                                           moneda='UYU', activo=True, codigo_telefono='598')
        self.config = ConfiguracionWhatsApp.obtener()
        self.config.activa = True
        self.config.texto_bienvenida = 'Hola, gracias por escribir.'
        self.config.save()
        RespuestaPais.objects.create(configuracion=self.config, pais=self.peru, texto='Mensaje para Perú')
        RespuestaPais.objects.create(configuracion=self.config, pais=self.uruguay, texto='Mensaje para Uruguay')
        self.url = reverse('wa_webhook')

    def enviar_aviso(self, datos, firma=None):
        cuerpo = json.dumps(datos).encode()
        if firma is None:
            firma = 'sha256=' + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
        return self.client.post(self.url, cuerpo, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=firma)


class VerificacionTests(_Base):
    def test_responde_el_desafio_si_la_frase_coincide(self):
        resp = self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'frase-de-verificacion',
                                          'hub.challenge': '12345'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'12345')

    def test_rechaza_una_frase_incorrecta_o_sin_configurar(self):
        self.assertEqual(self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'otra',
                                                    'hub.challenge': '1'}).status_code, 403)
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': ''}):
            self.assertEqual(self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': '',
                                                        'hub.challenge': '1'}).status_code, 403)

    def test_firma_invalida_o_ausente_se_rechaza_y_no_responde_nada(self):
        with mock.patch('wa_coexistencia.webhook.requests') as pedidos:
            self.assertEqual(self.enviar_aviso(_aviso(), firma='sha256=' + '0' * 64).status_code, 403)
            self.assertEqual(self.enviar_aviso(_aviso(), firma='').status_code, 403)
            pedidos.post.assert_not_called()
        self.assertFalse(MensajeRecibido.objects.exists())


class PaisDelTelefonoTests(_Base):
    def test_detecta_el_pais_por_el_codigo(self):
        self.assertEqual(pais_del_telefono('51999111222'), self.peru)
        self.assertEqual(pais_del_telefono('59899123456'), self.uruguay)
        self.assertIsNone(pais_del_telefono('5491155556666'))

    def test_gana_el_codigo_mas_largo(self):
        Pais.objects.create(nombre='Otro', slug='otro', codigo_iso='XX', bandera_emoji='x', moneda='X', activo=True,
                            codigo_telefono='5199')
        self.assertEqual(pais_del_telefono('51991112222').slug, 'otro')
        self.assertEqual(pais_del_telefono('51911112222').slug, 'peru')


class RespuestaAutomaticaTests(_Base):
    @mock.patch('wa_coexistencia.webhook.requests')
    def test_responde_bienvenida_y_el_mensaje_del_pais(self, pedidos):
        pedidos.post.return_value = _ok()
        resp = self.enviar_aviso(_aviso('51999111222'))
        self.assertEqual(resp.status_code, 200)
        enviados = [c.kwargs['json'] for c in pedidos.post.call_args_list]
        self.assertEqual([m['text']['body'] for m in enviados], ['Hola, gracias por escribir.', 'Mensaje para Perú'])
        self.assertTrue(all(m['to'] == '51999111222' and m['messaging_product'] == 'whatsapp' for m in enviados))
        self.assertTrue(pedidos.post.call_args.args[0].endswith('/1228482323672734/messages'))
        self.assertEqual(pedidos.post.call_args.kwargs['headers'], {'Authorization': 'Bearer TOKEN-X'})

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_el_segundo_mensaje_cambia_con_el_pais(self, pedidos):
        pedidos.post.return_value = _ok()
        self.enviar_aviso(_aviso('59899123456'))
        cuerpos = [c.kwargs['json']['text']['body'] for c in pedidos.post.call_args_list]
        self.assertEqual(cuerpos[-1], 'Mensaje para Uruguay')

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_pais_sin_mensaje_propio_usa_el_general_o_solo_la_bienvenida(self, pedidos):
        pedidos.post.return_value = _ok()
        self.enviar_aviso(_aviso('5491155556666', wa_id='a'))
        self.assertEqual(pedidos.post.call_count, 1)    # sin texto general: solo la bienvenida
        self.config.texto_otro_pais = 'Mensaje general'
        self.config.save()
        pedidos.post.reset_mock()
        self.enviar_aviso(_aviso('5491177778888', wa_id='b'))
        self.assertEqual([c.kwargs['json']['text']['body'] for c in pedidos.post.call_args_list],
                         ['Hola, gracias por escribir.', 'Mensaje general'])

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_con_archivo_se_manda_el_documento_con_el_texto_de_pie(self, pedidos):
        pedidos.post.return_value = _ok()
        respuesta = RespuestaPais.objects.get(pais=self.peru)
        with override_settings(MEDIA_ROOT=MEDIA_PRUEBAS):
            respuesta.archivo.save('guia.pdf', SimpleUploadedFile('guia.pdf', b'%PDF-1.4'))
        self.enviar_aviso(_aviso('51999111222'))
        segundo = pedidos.post.call_args_list[1].kwargs['json']
        self.assertEqual(segundo['type'], 'document')
        self.assertEqual(segundo['document']['caption'], 'Mensaje para Perú')
        self.assertTrue(segundo['document']['filename'].endswith('.pdf'))
        self.assertTrue(segundo['document']['link'].startswith('http'))

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_una_imagen_se_manda_como_imagen(self, pedidos):
        pedidos.post.return_value = _ok()
        respuesta = RespuestaPais.objects.get(pais=self.peru)
        with override_settings(MEDIA_ROOT=MEDIA_PRUEBAS):
            respuesta.archivo.save('foto.png', SimpleUploadedFile('foto.png', b'x'))
        self.enviar_aviso(_aviso('51999111222'))
        segundo = pedidos.post.call_args_list[1].kwargs['json']
        self.assertEqual(segundo['type'], 'image')
        self.assertNotIn('filename', segundo['image'])

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_un_texto_largo_con_archivo_va_en_un_mensaje_aparte(self, pedidos):
        pedidos.post.return_value = _ok()
        respuesta = RespuestaPais.objects.get(pais=self.peru)
        respuesta.texto = 'x' * 1001
        with override_settings(MEDIA_ROOT=MEDIA_PRUEBAS):
            respuesta.archivo.save('guia.pdf', SimpleUploadedFile('guia.pdf', b'%PDF-1.4'))
        self.enviar_aviso(_aviso('51999111222'))
        tipos = [c.kwargs['json']['type'] for c in pedidos.post.call_args_list]
        self.assertEqual(tipos, ['text', 'document', 'text'])
        self.assertNotIn('caption', pedidos.post.call_args_list[1].kwargs['json']['document'])

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_no_repite_dentro_del_periodo_y_si_despues(self, pedidos):
        pedidos.post.return_value = _ok()
        self.enviar_aviso(_aviso(wa_id='m1'))
        self.assertEqual(pedidos.post.call_count, 2)
        self.enviar_aviso(_aviso(wa_id='m2'))                       # otra vez a la hora: no
        self.assertEqual(pedidos.post.call_count, 2)
        ContactoWhatsApp.objects.update(ultima_respuesta=timezone.now() - datetime.timedelta(hours=25))
        self.enviar_aviso(_aviso(wa_id='m3'))                       # pasaron 25 h: sí
        self.assertEqual(pedidos.post.call_count, 4)

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_el_mismo_mensaje_reintentado_por_meta_se_atiende_una_vez(self, pedidos):
        pedidos.post.return_value = _ok()
        self.enviar_aviso(_aviso(wa_id='igual'))
        ContactoWhatsApp.objects.update(ultima_respuesta=None)
        self.enviar_aviso(_aviso(wa_id='igual'))
        self.assertEqual(pedidos.post.call_count, 2)

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_apagado_no_responde_nada(self, pedidos):
        self.config.activa = False
        self.config.save()
        self.assertEqual(self.enviar_aviso(_aviso()).status_code, 200)
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_estados_y_reacciones_no_activan_respuesta(self, pedidos):
        estado = {'entry': [{'changes': [{'value': {'statuses': [{'id': 'x', 'status': 'delivered'}]}}]}]}
        self.assertEqual(self.enviar_aviso(estado).status_code, 200)
        self.enviar_aviso(_aviso(wa_id='r1', tipo='reaction'))
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_si_meta_rechaza_la_bienvenida_no_sigue_ni_marca_al_contacto(self, pedidos):
        rechazo = mock.Mock(ok=False, status_code=400, text='error')
        pedidos.post.return_value = rechazo
        with self.assertLogs('wa_coexistencia.webhook', level='ERROR'):
            resp = self.enviar_aviso(_aviso())
        self.assertEqual(resp.status_code, 200)          # igual 200: si no, Meta reintenta
        self.assertEqual(pedidos.post.call_count, 1)
        self.assertIsNone(ContactoWhatsApp.objects.get().ultima_respuesta)

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_sin_token_de_envio_no_rompe(self, pedidos):
        with mock.patch.dict(os.environ, {'WHATSAPP_TOKEN': ''}):
            with self.assertLogs('wa_coexistencia.webhook', level='ERROR'):
                self.assertEqual(self.enviar_aviso(_aviso()).status_code, 200)
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_un_numero_raro_o_un_cuerpo_sin_mensajes_no_rompe(self, pedidos):
        self.assertEqual(self.enviar_aviso(_aviso(telefono='no-es-numero')).status_code, 200)
        self.assertEqual(self.enviar_aviso({'entry': []}).status_code, 200)
        pedidos.post.assert_not_called()


class AdminTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser('admin@example.com', 'admin@example.com', 'ClaveSegura123'))

    def test_la_configuracion_se_edita_en_el_admin_y_no_se_duplica(self):
        url = reverse('admin:wa_coexistencia_configuracionwhatsapp_change', args=[1])
        self.assertEqual(self.client.get(url).status_code, 200)
        ConfiguracionWhatsApp(texto_bienvenida='otra').save()
        self.assertEqual(ConfiguracionWhatsApp.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('admin:wa_coexistencia_configuracionwhatsapp_add')).status_code, 403)

    def test_no_se_puede_borrar(self):
        resp = self.client.post(reverse('admin:wa_coexistencia_configuracionwhatsapp_delete', args=[1]), {'post': 'yes'})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(ConfiguracionWhatsApp.objects.exists())


class PoliticaDePrivacidadTests(TestCase):
    """Meta pide que la política cubra WhatsApp y una forma de eliminar los datos."""

    def test_menciona_whatsapp_y_tiene_el_ancla_de_eliminacion_de_datos(self):
        resp = self.client.get(reverse('privacidad'))
        self.assertContains(resp, 'Si nos escribís por WhatsApp')
        self.assertContains(resp, 'WhatsApp (Meta)')
        self.assertContains(resp, 'id="eliminar-datos"')


class ContactosTests(_Base):
    @mock.patch('wa_coexistencia.webhook.requests')
    def test_con_las_respuestas_apagadas_igual_queda_anotado_que_escribieron(self, pedidos):
        self.config.activa = False
        self.config.save()
        self.enviar_aviso(_aviso('51999111222'))
        contacto = ContactoWhatsApp.objects.get(telefono='51999111222')
        self.assertIsNotNone(contacto.ultimo_mensaje)
        self.assertIsNone(contacto.ultima_respuesta)
        pedidos.post.assert_not_called()

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_si_responde_bien_queda_la_fecha_y_sin_error(self, pedidos):
        pedidos.post.return_value = _ok()
        self.enviar_aviso(_aviso('51999111222'))
        contacto = ContactoWhatsApp.objects.get()
        self.assertIsNotNone(contacto.ultima_respuesta)
        self.assertEqual(contacto.ultimo_error, '')

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_si_meta_rechaza_queda_el_motivo_para_verlo_en_el_admin(self, pedidos):
        pedidos.post.return_value = mock.Mock(ok=False, status_code=400, text='{"error":{"message":"pago"}}')
        with self.assertLogs('wa_coexistencia.webhook', level='ERROR'):
            self.enviar_aviso(_aviso('51999111222'))
        contacto = ContactoWhatsApp.objects.get()
        self.assertIn('400', contacto.ultimo_error)
        self.assertIn('pago', contacto.ultimo_error)
        self.assertIsNone(contacto.ultima_respuesta)

    @mock.patch('wa_coexistencia.webhook.requests')
    def test_sin_token_de_envio_queda_anotado(self, pedidos):
        with mock.patch.dict(os.environ, {'WHATSAPP_TOKEN': ''}):
            with self.assertLogs('wa_coexistencia.webhook', level='ERROR'):
                self.enviar_aviso(_aviso('51999111222'))
        self.assertIn('WHATSAPP_TOKEN', ContactoWhatsApp.objects.get().ultimo_error)

    def test_el_admin_lista_los_contactos_pero_no_deja_editarlos(self):
        ContactoWhatsApp.objects.create(telefono='51999111222', ultimo_mensaje=timezone.now())
        self.client.force_login(User.objects.create_superuser('a@example.com', 'a@example.com', 'ClaveSegura123'))
        resp = self.client.get(reverse('admin:wa_coexistencia_contactowhatsapp_changelist'))
        self.assertContains(resp, '51999111222')
        self.assertEqual(self.client.get(reverse('admin:wa_coexistencia_contactowhatsapp_add')).status_code, 403)
