"""Acción del admin: dar acceso gratis hasta una fecha (y quitarlo)."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Orientacion, Pais, Psicologo


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.admin_user = User.objects.create_superuser('admin_g', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)
        self.lista = reverse('admin:directorio_psicologo_changelist')
        self.orientacion = Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0]

    def _psi(self, email, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre='Psi ' + email.split('@')[0], matricula='1', whatsapp='51999999999',
            bio='bio', foto='psicologos/test.jpg', publicado_por_usuario=True, **extra,
        )
        psi.orientaciones.add(self.orientacion)
        return psi

    def accion(self, accion, psis, **extra):
        datos = {'action': accion, '_selected_action': [p.pk for p in psis]}
        datos.update(extra)
        return self.client.post(self.lista, datos)

    @staticmethod
    def manana():
        return (timezone.localdate() + datetime.timedelta(days=30)).isoformat()


class DarGratisHastaTests(_Base):
    def test_las_acciones_aparecen_en_la_lista(self):
        self._psi('a@example.com')
        resp = self.client.get(self.lista)
        self.assertContains(resp, 'Dar acceso gratis hasta una fecha')
        self.assertContains(resp, 'Quitar el período gratis')

    def test_primero_pide_la_fecha(self):
        psi = self._psi('a@example.com')
        resp = self.accion('dar_gratis_hasta_action', [psi])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Gratis hasta (inclusive)')
        self.assertContains(resp, psi.nombre)
        psi.refresh_from_db()
        self.assertIsNone(psi.gratis_hasta)   # todavía no cambió nada

    def test_con_la_fecha_lo_deja_gratis_hasta_el_final_de_ese_dia(self):
        psi = self._psi('a@example.com')
        resp = self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=self.manana())
        self.assertEqual(resp.status_code, 302)
        psi.refresh_from_db()
        limite = timezone.localtime(psi.gratis_hasta)
        self.assertEqual(limite.date().isoformat(), self.manana())
        self.assertEqual((limite.hour, limite.minute), (23, 59))
        self.assertTrue(psi.en_periodo_fundador)
        self.assertTrue(psi.tiene_acceso)
        self.assertTrue(psi.publicado)
        self.assertIsNotNone(psi.fecha_pago_confirmado)

    def test_funciona_para_varios_a_la_vez(self):
        psis = [self._psi(f'p{i}@example.com') for i in range(3)]
        self.accion('dar_gratis_hasta_action', psis, apply='1', fecha=self.manana())
        for p in psis:
            p.refresh_from_db()
            self.assertTrue(p.en_periodo_fundador)

    def test_rechaza_una_fecha_pasada(self):
        psi = self._psi('a@example.com')
        ayer = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        resp = self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=ayer)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'de hoy en adelante')
        psi.refresh_from_db()
        self.assertIsNone(psi.gratis_hasta)

    def test_a_quien_ya_paga_no_se_le_toca(self):
        pago = self._psi('pago@example.com', suscripcion_activa=True)
        self.accion('dar_gratis_hasta_action', [pago], apply='1', fecha=self.manana())
        pago.refresh_from_db()
        self.assertIsNone(pago.gratis_hasta)

    def test_vuelve_a_habilitar_el_aviso_de_fin_del_periodo(self):
        psi = self._psi('a@example.com', recordatorio_vencimiento_enviado=True)
        self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=self.manana())
        psi.refresh_from_db()
        self.assertFalse(psi.recordatorio_vencimiento_enviado)

    def test_al_vencer_se_despublica_solo(self):
        psi = self._psi('a@example.com')
        self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=self.manana())
        Psicologo.objects.filter(pk=psi.pk).update(gratis_hasta=timezone.now() - datetime.timedelta(seconds=1))
        psi.refresh_from_db()
        self.assertFalse(psi.publicado)

    def test_quien_no_es_admin_no_puede(self):
        psi = self._psi('a@example.com')
        self.client.logout()
        self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=self.manana())
        psi.refresh_from_db()
        self.assertIsNone(psi.gratis_hasta)


class QuitarGratisTests(_Base):
    def test_pide_confirmacion_y_avisa_que_se_despublica(self):
        psi = self._psi('a@example.com', gratis_hasta=timezone.now() + datetime.timedelta(days=10))
        resp = self.accion('quitar_gratis_action', [psi])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'se despublica en el acto')
        psi.refresh_from_db()
        self.assertIsNotNone(psi.gratis_hasta)

    def test_al_confirmar_se_lo_saca_y_deja_de_estar_publicado(self):
        psi = self._psi('a@example.com', gratis_hasta=timezone.now() + datetime.timedelta(days=10))
        self.assertTrue(psi.publicado)
        self.accion('quitar_gratis_action', [psi], apply='1')
        psi.refresh_from_db()
        self.assertIsNone(psi.gratis_hasta)
        self.assertFalse(psi.publicado)


class VerloElProfesionalEnSuMenuTests(_Base):
    """Después de darle el gratis, el profesional lo ve en el menú de su cuenta."""

    def _entrar(self, email='menu@example.com', **extra):
        psi = self._psi(email, **extra)
        self.client.logout()
        self.client.force_login(psi.usuario)
        return psi

    def test_el_menu_dice_hasta_cuando_es_gratis_en_todas_las_pantallas(self):
        psi = self._entrar(gratis_hasta=timezone.now() + datetime.timedelta(days=20))
        esperado = f'Gratis hasta el {timezone.localtime(psi.gratis_hasta):%d/%m/%Y}'
        for nombre in ('portal_dashboard', 'portal_agenda', 'portal_turnos', 'portal_pacientes', 'portal_cambiar_contrasena'):
            self.assertContains(self.client.get(reverse(nombre)), esperado, msg_prefix=nombre)

    def test_se_lo_ve_justo_despues_de_que_lo_cargues_desde_el_admin(self):
        psi = self._psi('menu@example.com')
        self.accion('dar_gratis_hasta_action', [psi], apply='1', fecha=self.manana())
        self.client.logout()
        self.client.force_login(psi.usuario)
        self.assertContains(self.client.get(reverse('portal_dashboard')), 'Gratis hasta el')

    def test_quien_paga_o_no_tiene_gratis_no_ve_el_aviso(self):
        self._entrar(suscripcion_activa=True, gratis_hasta=timezone.now() + datetime.timedelta(days=20))
        self.assertNotContains(self.client.get(reverse('portal_dashboard')), 'portal-nav-gratis')
        self.client.logout()
        self._entrar(email='sin_gratis@example.com')
        self.assertNotContains(self.client.get(reverse('portal_dashboard')), 'Gratis hasta el')

    def test_vencido_ya_no_aparece(self):
        self._entrar(gratis_hasta=timezone.now() - datetime.timedelta(days=1))
        self.assertNotContains(self.client.get(reverse('portal_dashboard')), 'portal-nav-gratis')
