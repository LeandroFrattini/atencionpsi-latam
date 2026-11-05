"""Contador de clicks en el botón de WhatsApp de cada profesional (para el admin)."""
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ClickWhatsApp, Orientacion, Pais, Psicologo, VisitaPerfil

NAVEGADOR = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
            precio_basico=49, precio_premium=85, activo=True, codigo_telefono='51',
        )

    def psi(self, email='ana@example.com', whatsapp='+51 999-111-222', publicado=True):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre='Ana Pérez', matricula='123', whatsapp=whatsapp, bio='Mi bio',
            foto='psicologos/x.jpg', publicado_por_usuario=publicado, exento_de_pago=True, ciudad='Lima',
        )
        psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0])
        return Psicologo.objects.get(pk=psi.pk)

    def url(self, psi, origen=None):
        base = reverse('ir_whatsapp', args=['peru', psi.pk])
        return base + (f'?o={origen}' if origen else '')

    def clicks(self, psi=None):
        qs = ClickWhatsApp.objects.all() if psi is None else ClickWhatsApp.objects.filter(psicologo=psi)
        return sum(c.cantidad for c in qs)


class ClickTests(_Base):
    def test_redirige_al_chat_del_profesional_y_cuenta_el_click(self):
        psi = self.psi()
        resp = self.client.get(self.url(psi, 'perfil'), HTTP_USER_AGENT=NAVEGADOR)
        self.assertRedirects(resp, 'https://wa.me/51999111222', fetch_redirect_response=False)
        self.assertEqual(self.clicks(psi), 1)
        self.assertEqual(ClickWhatsApp.objects.get().origen, 'perfil')

    def test_los_clicks_del_mismo_dia_se_suman_en_una_fila_por_origen(self):
        psi = self.psi()
        for origen in ('perfil', 'perfil', 'buscador'):
            self.client.get(self.url(psi, origen), HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(ClickWhatsApp.objects.count(), 2)
        self.assertEqual(ClickWhatsApp.objects.get(origen='perfil').cantidad, 2)
        self.assertEqual(self.clicks(psi), 3)

    def test_un_origen_raro_se_cuenta_como_buscador(self):
        psi = self.psi()
        self.client.get(self.url(psi, 'cualquier-cosa'), HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(ClickWhatsApp.objects.get().origen, 'buscador')

    def test_un_robot_llega_pero_no_cuenta(self):
        psi = self.psi()
        for agente in ('Googlebot/2.1 (+http://www.google.com/bot.html)', 'WhatsApp/2.23.20', ''):
            resp = self.client.get(self.url(psi), HTTP_USER_AGENT=agente)
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.clicks(), 0)

    def test_quien_administra_no_cuenta(self):
        psi = self.psi()
        staff = User.objects.create_user('equipo@example.com', password='ClaveSegura123', is_staff=True)
        self.client.force_login(staff)
        self.client.get(self.url(psi), HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(self.clicks(), 0)

    def test_el_profesional_tocando_su_propio_boton_no_cuenta(self):
        psi = self.psi()
        self.client.force_login(psi.usuario)
        resp = self.client.get(self.url(psi), HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.clicks(), 0)

    def test_otro_profesional_si_cuenta(self):
        psi, otro = self.psi(), self.psi('otra@example.com')
        self.client.force_login(otro.usuario)
        self.client.get(self.url(psi), HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(self.clicks(psi), 1)

    def test_no_se_cuenta_para_perfiles_no_publicados_ni_sin_numero(self):
        self.assertEqual(self.client.get(self.url(self.psi(publicado=False)), HTTP_USER_AGENT=NAVEGADOR).status_code, 404)
        sin_numero = self.psi('c@example.com', whatsapp='')
        self.assertEqual(self.client.get(self.url(sin_numero), HTTP_USER_AGENT=NAVEGADOR).status_code, 404)
        self.assertEqual(self.client.get('/peru/p/9999/whatsapp/', HTTP_USER_AGENT=NAVEGADOR).status_code, 404)
        self.assertEqual(self.clicks(), 0)

    def test_si_falla_el_conteo_igual_llega_a_whatsapp(self):
        psi = self.psi()
        with mock.patch('directorio.views._sumar', side_effect=Exception('base caída')):
            resp = self.client.get(self.url(psi), HTTP_USER_AGENT=NAVEGADOR)
        self.assertRedirects(resp, 'https://wa.me/51999111222', fetch_redirect_response=False)

    def test_la_respuesta_no_se_guarda_en_cache(self):
        self.assertIn('no-store', self.client.get(self.url(self.psi()), HTTP_USER_AGENT=NAVEGADOR)['Cache-Control'])

    def test_robots_no_deja_a_google_pasar_por_ahi(self):
        self.assertContains(self.client.get('/robots.txt'), 'Disallow: /*/whatsapp/')


class BotonesDelSitioTests(_Base):
    def test_el_perfil_y_la_tarjeta_pasan_por_el_contador(self):
        psi = self.psi()
        perfil = self.client.get(psi.url_publica, HTTP_USER_AGENT=NAVEGADOR)
        self.assertContains(perfil, self.url(psi, 'perfil'))
        buscador = self.client.get(reverse('buscador_pais', args=['peru']), HTTP_USER_AGENT=NAVEGADOR)
        self.assertContains(buscador, self.url(psi, 'buscador'))
        self.assertNotContains(buscador, 'https://wa.me/51999111222')
        self.assertNotContains(perfil, 'href="https://wa.me/51999111222"')


class VistaDelAdminTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('admin@example.com', password='ClaveSegura123')
        self.client.force_login(self.admin)

    def test_la_lista_muestra_los_clicks_de_30_dias_sin_duplicar_las_visitas(self):
        psi = self.psi()
        hoy = timezone.localdate()
        VisitaPerfil.objects.create(fecha=hoy, psicologo=psi, cantidad=3)
        VisitaPerfil.objects.create(fecha=hoy - datetime.timedelta(days=1), psicologo=psi, cantidad=4)
        ClickWhatsApp.objects.create(fecha=hoy, psicologo=psi, origen='perfil', cantidad=2)
        ClickWhatsApp.objects.create(fecha=hoy, psicologo=psi, origen='buscador', cantidad=1)
        ClickWhatsApp.objects.create(fecha=hoy - datetime.timedelta(days=60), psicologo=psi, origen='perfil', cantidad=9)
        resp = self.client.get(reverse('admin:directorio_psicologo_changelist'))
        self.assertEqual(resp.status_code, 200)
        fila = resp.context['cl'].result_list[0]
        self.assertEqual(fila.visitas_30, 7)          # no se multiplica por los clicks
        self.assertEqual(fila.clicks_wa_30, 3)        # los de hace 60 días no entran
        self.assertContains(resp, 'Clicks WhatsApp (30 d)')

    def test_el_reporte_de_visitas_trae_los_clicks_por_dia_y_por_profesional(self):
        psi = self.psi()
        hoy = timezone.localdate()
        ClickWhatsApp.objects.create(fecha=hoy, psicologo=psi, origen='perfil', cantidad=2)
        ClickWhatsApp.objects.create(fecha=hoy - datetime.timedelta(days=20), psicologo=psi, origen='buscador', cantidad=5)
        resp = self.client.get(reverse('admin:directorio_psicologo_visitas'))
        self.assertEqual(resp.status_code, 200)
        fila = next(f for f in resp.context['profesionales'] if f['psicologo'] == psi)
        self.assertEqual((fila['wa_siete'], fila['wa_treinta'], fila['wa_total']), (2, 7, 7))
        self.assertEqual(dict(resp.context['dias_wa'])[hoy], 2)
        self.assertContains(resp, 'Clicks en WhatsApp por día')

    def test_el_detalle_dia_por_dia_esta_en_el_admin_y_es_de_solo_lectura(self):
        ClickWhatsApp.objects.create(fecha=timezone.localdate(), psicologo=self.psi(), origen='perfil')
        self.assertEqual(self.client.get(reverse('admin:directorio_clickwhatsapp_changelist')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:directorio_clickwhatsapp_add')).status_code, 403)
