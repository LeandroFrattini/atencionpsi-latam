import io
import os

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from directorio.models import Orientacion, Pais, Psicologo


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True,
            codigo_telefono='51',
        )
        self.orientacion, _ = Orientacion.objects.get_or_create(nombre='Sistémica')
        self.usuario = User.objects.create_user('psi@example.com', email='psi@example.com', password='ClaveSegura123')

    def psi(self, completo=True, **extra):
        datos = dict(usuario=self.usuario, pais=self.pais, nombre='Lic. Ana Pérez', whatsapp='51999999999')
        if completo:
            datos.update(matricula='123', bio='Trabajo con adultos.', foto='psicologos/test.jpg')
        datos.update(extra)
        psi = Psicologo.objects.create(**datos)
        if completo:
            psi.orientaciones.add(self.orientacion)
        self.client.force_login(self.usuario)
        return psi


class FaltantesDelPerfilTests(_Base):
    def test_un_perfil_nuevo_lista_todo_lo_que_falta(self):
        psi = self.psi(completo=False, whatsapp='')
        self.assertEqual(
            psi.faltantes_perfil,
            ['N° de Matrícula', 'tu WhatsApp', 'tu foto', 'tu descripción', 'al menos una orientación'],
        )

    def test_coincide_con_perfil_completo_en_cada_combinacion(self):
        psi = self.psi(completo=False)
        self.assertFalse(psi.perfil_completo)
        for campo, valor in (('matricula', '123'), ('foto', 'psicologos/t.jpg'), ('bio', 'Hola')):
            self.assertEqual(psi.perfil_completo, not psi.faltantes_perfil)
            setattr(psi, campo, valor)
            psi.save()
        self.assertFalse(psi.perfil_completo)
        self.assertEqual(psi.faltantes_perfil, ['al menos una orientación'])
        psi.orientaciones.add(self.orientacion)
        self.assertTrue(psi.perfil_completo)
        self.assertEqual(psi.faltantes_perfil, [])


class VistaPreviaTests(_Base):
    def test_hay_que_estar_logueado(self):
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertEqual(resp.status_code, 302)

    def test_muestra_el_perfil_aunque_no_este_publicado_y_no_se_indexa(self):
        self.psi()
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Lic. Ana Pérez')
        self.assertContains(resp, 'Trabajo con adultos.')
        self.assertContains(resp, '<meta name="robots" content="noindex, nofollow">')
        self.assertContains(resp, 'Así se va a ver tu perfil cuando lo publiques')

    def test_el_perfil_publico_sigue_dando_404_si_no_esta_publicado(self):
        psi = self.psi()
        self.assertEqual(self.client.get(psi.url_publica).status_code, 404)

    def test_el_perfil_publico_sigue_indexable(self):
        psi = self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        resp = self.client.get(psi.url_publica, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(resp, '<meta name="robots" content="index, follow">')
        self.assertNotContains(resp, 'Vista previa')

    def test_dice_que_falta_cuando_esta_incompleto(self):
        self.psi(completo=False)
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertContains(resp, 'te falta: ')
        self.assertContains(resp, 'tu foto')

    def test_los_botones_son_de_mentira_y_no_hay_link_para_compartir(self):
        self.psi()
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertNotContains(resp, 'wa.me/51999999999')
        self.assertNotContains(resp, 'id="btn-compartir"')
        self.assertContains(resp, 'data-vista-previa')

    def test_publicado_ofrece_ver_el_perfil_publico_y_no_el_boton_de_publicar(self):
        psi = self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertContains(resp, 'Ver el perfil público')
        self.assertNotContains(resp, 'Publicar mi perfil')

    def test_cada_uno_ve_solo_su_propio_perfil(self):
        self.psi()
        otro = User.objects.create_user('otro@example.com', password='ClaveSegura123')
        Psicologo.objects.create(usuario=otro, pais=self.pais, nombre='Otra Persona', matricula='9', whatsapp='51888')
        resp = self.client.get(reverse('portal_vista_previa'))
        self.assertNotContains(resp, 'Otra Persona')


class EditorDelPerfilTests(_Base):
    def test_trae_la_tarjeta_en_vivo_y_los_pasos_para_publicar(self):
        self.psi(completo=False)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, 'Así te ven los pacientes')
        self.assertContains(resp, 'id="previa-tarjeta"')
        self.assertContains(resp, 'Guardar y publicar')
        self.assertContains(resp, reverse('portal_vista_previa'))

    def test_antes_de_pagar_avisa_que_el_plan_se_elige_al_publicar(self):
        self.psi()
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, 'Hasta ese momento no pagás nada')

    def test_ya_publicado_no_ofrece_publicar_de_nuevo(self):
        self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, 'Tu perfil está publicado')
        self.assertNotContains(resp, 'Guardar y publicar')

    def _post(self, **extra):
        datos = dict(
            nombre='Lic. Ana Pérez', matricula='123', whatsapp='51999999999', ciudad='', modalidad='online',
            bio='Trabajo con adultos.', docencia='', orientaciones=[self.orientacion.pk],
            **{'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
               'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000'},
        )
        datos.update(extra)
        return self.client.post(reverse('portal_editar_perfil'), datos)

    def test_guardar_se_queda_en_el_editor(self):
        self.psi()
        self.assertRedirects(self._post(), reverse('portal_editar_perfil'))

    def test_guardar_y_publicar_con_todo_completo_pero_sin_plan_va_al_checkout(self):
        psi = self.psi()
        resp = self._post(accion='publicar')
        self.assertRedirects(resp, reverse('portal_checkout'))
        psi.refresh_from_db()
        self.assertTrue(psi.publicado_por_usuario)
        self.assertFalse(psi.publicado)

    def test_guardar_y_publicar_con_plan_lo_publica(self):
        psi = self.psi(suscripcion_activa=True)
        resp = self._post(accion='publicar')
        self.assertRedirects(resp, reverse('portal_dashboard'))
        psi.refresh_from_db()
        self.assertTrue(psi.publicado)

    def test_guardar_y_publicar_con_algo_faltante_vuelve_al_editor_y_dice_que(self):
        psi = self.psi(completo=False)
        resp = self._post(accion='publicar', bio='', orientaciones=[])
        self.assertRedirects(resp, reverse('portal_editar_perfil'), fetch_redirect_response=False)
        psi.refresh_from_db()
        self.assertFalse(psi.publicado_por_usuario)

    def test_guardar_y_publicar_cuenta_lo_que_se_acaba_de_guardar(self):
        psi = self.psi(completo=False)
        resp = self._post(accion='publicar', foto=self._foto())
        # La foto nueva se guardó: lo único que falta es lo que no se mandó (nada), o sea queda completo.
        psi.refresh_from_db()
        self.assertTrue(psi.foto.name)
        self.assertRedirects(resp, reverse('portal_checkout'))

    def _foto(self, tamano=(200, 200)):
        buf = io.BytesIO()
        Image.new('RGB', tamano, (120, 150, 120)).save(buf, format='JPEG')
        buf.seek(0)
        return SimpleUploadedFile('foto.jpg', buf.read(), content_type='image/jpeg')

    def test_una_foto_de_mas_de_5_mb_se_rechaza_con_un_aviso(self):
        psi = self.psi()
        ruido = io.BytesIO()
        Image.frombytes('RGB', (1800, 1500), os.urandom(1800 * 1500 * 3)).save(ruido, format='PNG')
        self.assertGreater(ruido.tell(), 5 * 1024 * 1024)
        grande = SimpleUploadedFile('grande.png', ruido.getvalue(), content_type='image/png')
        resp = self._post(foto=grande)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'el máximo es 5 MB')
        psi.refresh_from_db()
        self.assertEqual(psi.foto.name, 'psicologos/test.jpg')

    def test_el_menu_tiene_un_link_a_mi_perfil(self):
        self.psi()
        self.assertContains(self.client.get(reverse('portal_dashboard')), reverse('portal_editar_perfil'))


class CheckoutYPanelTests(_Base):
    def test_el_checkout_con_el_perfil_listo_lo_dice(self):
        self.psi()
        resp = self.client.get(reverse('portal_checkout'))
        self.assertContains(resp, 'Tu perfil está listo: elegí tu plan y publicalo')

    def test_el_checkout_con_el_perfil_incompleto_dice_que_falta(self):
        self.psi(completo=False)
        resp = self.client.get(reverse('portal_checkout'))
        self.assertContains(resp, 'Todavía te falta completar')

    def test_el_panel_con_perfil_completo_sin_plan_ofrece_publicar(self):
        self.psi()
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertContains(resp, 'Perfil listo — elegí tu plan para publicarlo')
        self.assertContains(resp, 'Publicar mi perfil')

    def test_el_panel_con_perfil_incompleto_dice_que_falta(self):
        self.psi(completo=False)
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertContains(resp, 'te falta: ')
        self.assertContains(resp, 'Completar mi perfil')


class MailPerfilCasiListoTests(_Base):
    """A los 2 días de registrarse sin plan: 'tu perfil está casi listo', según lo que le falte."""

    def _vieja(self, completo, **extra):
        import datetime
        from django.utils import timezone
        psi = self.psi(completo=completo, **extra)
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=3))
        return psi

    def _correr(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('enviar_recordatorios', '--apply', stdout=io.StringIO())
        return mail.outbox

    def test_con_el_perfil_incompleto_dice_que_le_falta_y_manda_al_editor(self):
        self._vieja(completo=False)
        salida = self._correr()
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0].subject, 'Tu perfil en Atención Psi está casi listo')
        self.assertIn('te falta: ', salida[0].body)
        self.assertIn('tu foto', salida[0].body)
        self.assertIn('/portal/perfil/', salida[0].body)
        self.assertIn('Hola Ana', salida[0].body)

    def test_con_el_perfil_completo_solo_le_pide_elegir_el_plan(self):
        self._vieja(completo=True)
        salida = self._correr()
        self.assertEqual(len(salida), 1)
        self.assertIn('elegir tu plan y publicarlo', salida[0].body)
        self.assertNotIn('te falta', salida[0].body)

    def test_se_manda_una_sola_vez(self):
        self._vieja(completo=False)
        self._correr()
        self.assertEqual(len(self._correr()), 0)

    def test_no_se_manda_a_quien_ya_tiene_plan_o_gratis(self):
        self._vieja(completo=True, suscripcion_activa=True)
        self.assertEqual(self._correr(), [])

    def test_no_se_manda_a_quien_no_confirmo_el_email(self):
        psi = self._vieja(completo=False)
        User.objects.filter(pk=psi.usuario_id).update(is_active=False)
        self.assertEqual(self._correr(), [])
