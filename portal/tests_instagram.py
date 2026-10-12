"""Usuario de Instagram y casilla de colaborador/a (solo Plan Premium)."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from directorio.instagram import normalizar_instagram
from directorio.models import Orientacion, Pais, Psicologo
from directorio.tests_dlocal import CLAVES, BaseDLocalTests


class NormalizarInstagramTests(TestCase):
    def test_acepta_arroba_usuario_y_link(self):
        for entrada in ('@Atencion.Psi', 'atencion.psi', '  @atencion.psi ', 'https://www.instagram.com/atencion.psi/',
                        'instagram.com/atencion.psi?igsh=abc', 'http://instagram.com/Atencion.Psi'):
            self.assertEqual(normalizar_instagram(entrada), 'atencion.psi', entrada)

    def test_vacio_devuelve_vacio(self):
        self.assertEqual(normalizar_instagram(''), '')
        self.assertEqual(normalizar_instagram('   '), '')

    def test_rechaza_lo_que_no_es_un_usuario(self):
        for malo in ('hola que tal', '@@', 'a' * 31, 'user$name', 'https://example.com/foo bar'):
            with self.assertRaises(ValueError, msg=malo):
                normalizar_instagram(malo)


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)


class RegistroInstagramTests(_Base):
    def test_el_registro_no_pide_instagram(self):
        resp = self.client.get(reverse('portal_registro', args=['peru']))
        self.assertNotContains(resp, 'Instagram')
        self.assertNotContains(resp, 'name="instagram"')

    def test_registrarse_sin_instagram_funciona(self):
        self.client.post(reverse('portal_registro', args=['peru']), dict(
            nombre='Nueva', email='nueva@example.com', whatsapp='51999999999',
            password='ClaveSegura123', acepto_terminos='on',
        ))
        self.assertEqual(Psicologo.objects.get(usuario__username='nueva@example.com').instagram, '')


class PerfilInstagramTests(_Base):
    def setUp(self):
        super().setUp()
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519',
        )
        self.client.force_login(self.usuario)

    def _post(self, **extra):
        datos = dict(
            nombre='Psico', matricula='1', whatsapp='519', ciudad='', modalidad='online', bio='', docencia='',
            **{'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
               'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000'},
        )
        datos.update(extra)
        return self.client.post(reverse('portal_editar_perfil'), datos)

    def test_el_usuario_se_guarda_y_se_muestra_con_arroba(self):
        self._post(instagram='https://instagram.com/Psico.Ok')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.instagram, 'psico.ok')
        self.assertContains(self.client.get(reverse('portal_editar_perfil')), 'value="@psico.ok"')

    def test_usuario_invalido_muestra_error(self):
        resp = self._post(instagram='hola que tal')
        self.assertContains(resp, 'Escribí tu usuario así')
        self.psi.refresh_from_db()
        self.assertEqual(self.psi.instagram, '')

    def test_la_casilla_de_colaborador_no_aparece_en_el_plan_basico(self):
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertNotContains(resp, 'name="quiere_colaborar"')

    def test_en_el_basico_se_ignora_aunque_la_manden_a_mano(self):
        self._post(instagram='@psico', quiere_colaborar='on')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.quiere_colaborar)

    def test_en_el_premium_aparece_y_se_guarda(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(plan='premium')
        self.assertContains(self.client.get(reverse('portal_editar_perfil')), 'name="quiere_colaborar"')
        self._post(instagram='@psico', quiere_colaborar='on')
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.quiere_colaborar)
        self.assertEqual(self.psi.instagram, 'psico')

    def test_ser_colaborador_sin_instagram_da_error(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(plan='premium')
        resp = self._post(quiere_colaborar='on')
        self.assertContains(resp, 'necesitamos tu usuario de Instagram')
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.quiere_colaborar)


@override_settings(**CLAVES)
class CheckoutColaboradorTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_el_checkout_ofrece_la_casilla_y_el_usuario(self):
        resp = self.client.get(reverse('portal_checkout'))
        self.assertContains(resp, 'name="quiere_colaborar"')
        self.assertContains(resp, 'name="instagram"')
        self.assertContains(resp, 'Quiero ser colaborador/a')

    def test_premium_con_casilla_guarda_instagram_y_colaboracion(self):
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'premium', 'quiere_colaborar': 'on', 'instagram': '@Ana.Psi'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('checkout.dlocalgo.com', resp['Location'])
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.quiere_colaborar)
        self.assertEqual(self.psi.instagram, 'ana.psi')

    def test_basico_ignora_la_casilla(self):
        self.client.post(reverse('portal_checkout'), {'plan': 'basico', 'quiere_colaborar': 'on', 'instagram': '@ana.psi'})
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.quiere_colaborar)
        self.assertEqual(self.psi.instagram, 'ana.psi')

    def test_premium_con_casilla_pero_sin_instagram_vuelve_con_error(self):
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'premium', 'quiere_colaborar': 'on', 'instagram': ''})
        self.assertRedirects(resp, reverse('portal_checkout'))
        self.psi.refresh_from_db()
        self.assertFalse(self.psi.quiere_colaborar)
        self.assertEqual(self.psi.plan, 'basico')   # no avanzó al pago

    def test_usa_el_instagram_del_registro_si_no_lo_cambia(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(instagram='ana.psi')
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'premium', 'quiere_colaborar': 'on', 'instagram': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('checkout.dlocalgo.com', resp['Location'])
        self.psi.refresh_from_db()
        self.assertTrue(self.psi.quiere_colaborar)

    def test_instagram_invalido_no_avanza(self):
        resp = self.client.post(reverse('portal_checkout'), {'plan': 'premium', 'instagram': 'no valido!'})
        self.assertRedirects(resp, reverse('portal_checkout'))
