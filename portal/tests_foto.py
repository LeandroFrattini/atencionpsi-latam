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
