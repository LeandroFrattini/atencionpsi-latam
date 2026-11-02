"""Guardado parcial del perfil ("Guardar avance"): se puede guardar lo que se tenga, de a partes,
sin completar lo obligatorio para publicar (nombre, habilitación profesional, WhatsApp)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from directorio.models import Orientacion, Pais, Psicologo

FORMSET = {
    'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
    'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000',
}


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='México', slug='mexico', codigo_iso='MX', bandera_emoji='🇲🇽', moneda='MXN',
            etiqueta_matricula='N° de Cédula Profesional', activo=True,
        )
        self.usuario = User.objects.create_user('nueva@example.com', password='ClaveSegura123')
        # Como queda una cuenta recién registrada: sin habilitación, sin foto, sin descripción.
        self.psi = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Ana Pérez', matricula='', whatsapp='5255123456',
        )
        self.client.force_login(self.usuario)

    def _post(self, accion=None, **campos):
        datos = dict(nombre='Ana Pérez', matricula='', whatsapp='5255123456', ciudad='', modalidad='online', bio='', docencia='', **FORMSET)
        datos.update(campos)
        if accion:
            datos['accion'] = accion
        return self.client.post(reverse('portal_editar_perfil'), datos, follow=True)


class GuardarAvanceTests(_Base):
    def test_guarda_lo_que_hay_aunque_falten_los_obligatorios(self):
        resp = self._post('parcial', nombre='', matricula='', whatsapp='', bio='Trabajo con adultos y jóvenes.')
        self.assertRedirects(resp, reverse('portal_editar_perfil'))
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.bio, 'Trabajo con adultos y jóvenes.')
        self.assertContains(resp, 'Guardamos tu avance')

    def test_un_campo_obligatorio_vacio_no_pisa_lo_que_ya_estaba_guardado(self):
        self._post('parcial', nombre='', whatsapp='', bio='Hola')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.nombre, 'Ana Pérez')
        self.assertEqual(self.psi.whatsapp, '5255123456')

    def test_si_completa_un_obligatorio_se_guarda(self):
        self._post('parcial', matricula='1234567', whatsapp='5255999888')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.matricula, '1234567')
        self.assertEqual(self.psi.whatsapp, '5255999888')

    def test_se_puede_cargar_de_a_partes_y_cada_parte_se_conserva(self):
        self._post('parcial', bio='Primera parte: mi descripción.')
        self._post('parcial', bio='Primera parte: mi descripción.', ciudad='', matricula='999')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.bio, 'Primera parte: mi descripción.')
        self.assertEqual(self.psi.matricula, '999')

    def test_el_aviso_dice_que_falta_para_publicar(self):
        resp = self._post('parcial', bio='Algo')
        self.assertContains(resp, 'Para publicar te falta')
        self.assertContains(resp, 'N° de Cédula Profesional')   # la habilitación, con el nombre del país
        self.assertContains(resp, 'tu foto')
        self.assertContains(resp, 'al menos una orientación')
        self.assertNotContains(resp, 'tu descripción')           # la descripción sí quedó cargada

    def test_el_aviso_dice_cuando_ya_esta_todo(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(matricula='123', foto='psicologos/x.jpg')
        orientacion = Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0]
        self.psi.orientaciones.add(orientacion)
        # Como el navegador: la orientación ya tildada viaja en el formulario.
        resp = self._post('parcial', matricula='123', bio='Completa', orientaciones=[orientacion.pk])
        self.assertContains(resp, 'Ya tenés todo para publicar')

    def test_guardar_avance_no_publica_el_perfil(self):
        self._post('parcial', bio='Algo')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.publicado_por_usuario)

    def test_sigue_validando_lo_que_si_se_cargo(self):
        """Parcial no es "todo vale": un dato mal cargado igual se rechaza."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(reverse('portal_editar_perfil'), dict(
            nombre='', matricula='', whatsapp='', ciudad='', modalidad='online', bio='', docencia='',
            accion='parcial', foto=SimpleUploadedFile('x.jpg', b'esto no es una imagen', content_type='image/jpeg'),
            **FORMSET,
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'portal-error')


class LoObligatorioSigueExigiendoseParaPublicarTests(_Base):
    def test_guardar_normal_sin_habilitacion_sigue_dando_error(self):
        resp = self._post(None, matricula='', bio='No se guarda')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'portal-error')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.bio, '')

    def test_guardar_y_publicar_sin_nombre_da_error(self):
        resp = self._post('publicar', nombre='', bio='x')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'portal-error')

    def test_guardar_y_publicar_con_el_perfil_incompleto_no_publica(self):
        self._post('publicar', bio='Solo la descripción')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.publicado)


class BotonesDeLaPantallaTests(_Base):
    def test_perfil_sin_publicar_muestra_guardar_avance_sin_validacion_del_navegador(self):
        html = self.client.get(reverse('portal_editar_perfil')).content.decode()
        self.assertIn('value="parcial"', html)
        self.assertIn('formnovalidate', html)
        self.assertIn('Guardar avance', html)
        self.assertIn('Guardar y publicar', html)
        self.assertIn('no se pierde nada', html)
        # Un botón en el formulario y otro en la barra fija del celular.
        self.assertEqual(html.count('Guardar avance</button>'), 2)

    def test_perfil_ya_publicado_solo_tiene_guardar(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(
            matricula='123', bio='x', foto='psicologos/x.jpg', exento_de_pago=True, publicado_por_usuario=True,
        )
        self.psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Gestalt')[0])
        html = self.client.get(reverse('portal_editar_perfil')).content.decode()
        self.assertNotIn('Guardar avance', html)
        self.assertNotIn('value="parcial"', html)
        self.assertIn('>Guardar</button>', html)
