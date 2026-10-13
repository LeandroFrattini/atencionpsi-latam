"""Si falla el almacenamiento de la foto, el profesional ve un aviso (no una pantalla de error)."""
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from directorio.models import Pais, Psicologo


class FotoConAlmacenamientoCaidoTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.client.force_login(self.usuario)

    def _datos(self, **extra):
        datos = dict(
            nombre='Psico Nuevo', matricula='1', whatsapp='519', ciudad='', modalidad='online', bio='', docencia='',
            **{'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
               'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000'},
        )
        datos.update(extra)
        return datos

    def _foto(self):
        buf = io.BytesIO()
        Image.new('RGB', (200, 200), (120, 150, 120)).save(buf, format='JPEG')
        buf.seek(0)
        return SimpleUploadedFile('foto.jpg', buf.read(), content_type='image/jpeg')

    def test_un_fallo_al_subir_la_foto_avisa_en_el_campo_y_no_da_500(self):
        with mock.patch('django.core.files.storage.FileSystemStorage.save', side_effect=OSError('bucket inexistente')):
            with self.assertLogs('portal.views', level='ERROR') as logs:
                resp = self.client.post(reverse('portal_editar_perfil'), self._datos(foto=self._foto()))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No pudimos guardar la foto')
        self.assertTrue(any('bucket inexistente' in linea for linea in logs.output))   # el detalle queda en los logs
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.nombre, 'Psico')   # no se guardó nada a medias

    def test_sin_foto_nueva_el_perfil_se_guarda_aunque_el_almacenamiento_este_caido(self):
        with mock.patch('django.core.files.storage.FileSystemStorage.save', side_effect=OSError('bucket inexistente')):
            resp = self.client.post(reverse('portal_editar_perfil'), self._datos())
        self.assertEqual(resp.status_code, 302)
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.nombre, 'Psico Nuevo')

    def test_con_el_almacenamiento_sano_la_foto_se_guarda(self):
        resp = self.client.post(reverse('portal_editar_perfil'), self._datos(foto=self._foto()))
        self.assertEqual(resp.status_code, 302)
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.foto.name)


class AclaracionDelWhatsappTests(TestCase):
    """El número va con el código de país o el link de WhatsApp del perfil no funciona."""

    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True, codigo_telefono='51',
        )

    def test_el_registro_lo_aclara_con_el_codigo_del_pais(self):
        resp = self.client.get(reverse('portal_registro', args=['peru']))
        self.assertContains(resp, 'código de tu país adelante')
        self.assertContains(resp, 'por ejemplo +51 para Perú')
        self.assertContains(resp, 'el link de WhatsApp de tu perfil no va a funcionar')
        self.assertContains(resp, 'placeholder="+51 …"')

    def test_el_perfil_tambien_lo_aclara(self):
        usuario = User.objects.create_user('p@example.com', password='ClaveSegura123')
        Psicologo.objects.create(usuario=usuario, pais=self.pais, nombre='Psi', matricula='1', whatsapp='51999999999')
        self.client.force_login(usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, 'por ejemplo +51 para Perú')

    def test_sin_codigo_cargado_da_ejemplos_generales(self):
        Pais.objects.filter(pk=self.pais.pk).update(codigo_telefono='')
        resp = self.client.get(reverse('portal_registro', args=['peru']))
        self.assertContains(resp, '+54 para Argentina o +51 para Perú')

    def test_registrarse_con_el_numero_completo_sigue_funcionando(self):
        resp = self.client.post(reverse('portal_registro', args=['peru']), dict(
            nombre='Nueva', email='nueva@example.com', whatsapp='+51 987 654 321',
            password='ClaveSegura123', acepto_terminos='on',
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Psicologo.objects.get(usuario__username='nueva@example.com').whatsapp_limpio(), '51987654321')
