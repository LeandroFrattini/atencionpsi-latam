"""El profesional puede cambiar su contraseña desde el menú de su cuenta."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from directorio.models import Pais, Psicologo


class CambiarContrasenaTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', email='psico@example.com', password='ClaveVieja2026!')
        self.psi = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.url = reverse('portal_cambiar_contrasena')

    def _datos(self, **extra):
        datos = {'old_password': 'ClaveVieja2026!', 'new_password1': 'ClaveNuevaMuySegura9', 'new_password2': 'ClaveNuevaMuySegura9'}
        datos.update(extra)
        return datos

    def test_hay_que_haber_iniciado_sesion(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('portal_login'), resp['Location'])
        self.assertEqual(self.client.post(self.url, self._datos()).status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveVieja2026!'))

    def test_el_menu_tiene_el_enlace_en_todas_las_pantallas_del_portal(self):
        self.client.force_login(self.usuario)
        for nombre in ('portal_dashboard', 'portal_agenda', 'portal_turnos', 'portal_pacientes', 'portal_cambiar_contrasena'):
            resp = self.client.get(reverse(nombre))
            self.assertContains(resp, f'href="{self.url}"', msg_prefix=nombre)
            self.assertContains(resp, 'Contraseña', msg_prefix=nombre)

    def test_la_pagina_muestra_los_tres_campos_en_castellano(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Contraseña actual')
        self.assertContains(resp, 'Contraseña nueva')
        self.assertContains(resp, 'Repetí la contraseña nueva')
        self.assertContains(resp, 'noindex')

    def test_cambia_la_contrasena_y_sigue_con_la_sesion_iniciada(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(self.url, self._datos(), follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('portal_dashboard'))
        self.assertContains(resp, 'cambiaste tu contraseña')   # y sigue adentro, sin pedir login de nuevo
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveNuevaMuySegura9'))

    def test_despues_puede_entrar_con_la_nueva_y_ya_no_con_la_vieja(self):
        self.client.force_login(self.usuario)
        self.client.post(self.url, self._datos())
        self.client.logout()
        login = reverse('portal_login')
        vieja = self.client.post(login, {'username': 'psico@example.com', 'password': 'ClaveVieja2026!'})
        self.assertEqual(vieja.status_code, 200)   # vuelve al formulario: no la acepta
        nueva = self.client.post(login, {'username': 'psico@example.com', 'password': 'ClaveNuevaMuySegura9'})
        self.assertRedirects(nueva, reverse('portal_dashboard'))

    def test_pide_la_contrasena_actual_correcta(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(self.url, self._datos(old_password='otra-cosa'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'portal-error')
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveVieja2026!'))

    def test_las_dos_nuevas_tienen_que_coincidir(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(self.url, self._datos(new_password2='otra-distinta-9999'))
        self.assertEqual(resp.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveVieja2026!'))

    def test_rechaza_contrasenas_cortas_o_demasiado_comunes(self):
        self.client.force_login(self.usuario)
        for mala in ('corta1', '12345678', 'password'):
            resp = self.client.post(self.url, self._datos(new_password1=mala, new_password2=mala))
            self.assertEqual(resp.status_code, 200, mala)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveVieja2026!'))
