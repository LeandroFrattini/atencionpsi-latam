"""Contador de visitas por página y por profesional (sin robots)."""
import datetime

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from . import visitas
from .bot_detector import es_bot
from .models import Orientacion, Pais, Psicologo, Visita, VisitaPerfil

NAVEGADOR = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.psi = self._psi('ana@example.com', 'Ana Pérez')
        self.hoy = timezone.localdate()

    def _psi(self, email, nombre):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre=nombre, matricula='1', whatsapp='51999999999', bio='bio',
            foto='psicologos/test.jpg', ciudad='Lima', suscripcion_activa=True, publicado_por_usuario=True,
        )
        psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0])
        return psi

    def ver(self, url, agente=NAVEGADOR, **extra):
        return self.client.get(url, HTTP_USER_AGENT=agente, **extra)

    def visitas_de(self, pagina):
        return sum(Visita.objects.filter(pagina=pagina).values_list('cantidad', flat=True))


class ConteoPorPaginaTests(_Base):
    def test_cuenta_una_visita_real_por_pagina_y_por_dia(self):
        self.ver(reverse('faq'))
        self.ver(reverse('faq'))
        self.ver(reverse('hub'))
        self.assertEqual(self.visitas_de('/faq/'), 2)
        self.assertEqual(self.visitas_de('/'), 1)
        self.assertEqual(Visita.objects.filter(pagina='/faq/').count(), 1)   # una sola fila por día

    def test_no_cuenta_a_los_robots(self):
        for agente in (
            'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'WhatsApp/2.23.20.0 A', 'facebookexternalhit/1.1', 'python-requests/2.31.0', 'curl/8.0.1',
            'Mozilla/5.0 (compatible; AhrefsBot/7.0)', 'UptimeRobot/2.0', 'Render/1.0 health check',
            'Mozilla/5.0 Chrome-Lighthouse AppleWebKit/537.36',
        ):
            self.ver(reverse('faq'), agente=agente)
        self.assertEqual(self.visitas_de('/faq/'), 0)

    def test_sin_user_agent_tampoco_cuenta(self):
        self.client.get(reverse('faq'))
        self.assertEqual(self.visitas_de('/faq/'), 0)

    def test_no_cuenta_el_panel_ni_el_portal_ni_la_api_ni_los_archivos(self):
        self.ver('/admin/login/')
        self.ver('/portal/login/')
        self.ver('/robots.txt')
        self.ver('/sitemap.xml')
        self.assertEqual(Visita.objects.count(), 0)

    def test_no_cuenta_paginas_que_dan_error_ni_pedidos_que_no_son_get(self):
        self.ver('/pagina-que-no-existe/')
        self.client.post(reverse('contacto'), {}, HTTP_USER_AGENT=NAVEGADOR)
        self.assertEqual(Visita.objects.filter(pagina='/pagina-que-no-existe/').count(), 0)

    def test_no_cuenta_las_actualizaciones_en_vivo_del_buscador(self):
        self.ver(reverse('buscador_pais', args=['peru']))
        self.ver(reverse('buscador_pais', args=['peru']) + '?q=lima&fragmento=1')
        self.ver(reverse('buscador_pais', args=['peru']), HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(self.visitas_de('/peru/buscar/'), 1)

    def test_la_busqueda_con_filtros_cuenta_como_la_misma_pagina(self):
        self.ver(reverse('buscador_pais', args=['peru']) + '?q=ansiedad')
        self.ver(reverse('buscador_pais', args=['peru']) + '?modalidad=online')
        self.assertEqual(self.visitas_de('/peru/buscar/'), 2)

    def test_no_cuenta_a_quien_administra_el_sitio(self):
        admin = User.objects.create_superuser('admin_v', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(admin)
        self.ver(reverse('faq'))
        self.assertEqual(self.visitas_de('/faq/'), 0)

    def test_una_falla_al_contar_no_rompe_la_pagina(self):
        from unittest import mock
        with mock.patch('directorio.middleware._sumar', side_effect=RuntimeError('base caída')):
            resp = self.ver(reverse('faq'))
        self.assertEqual(resp.status_code, 200)


class ConteoPorProfesionalTests(_Base):
    def test_cuenta_las_visitas_al_perfil_de_cada_profesional(self):
        otra = self._psi('otra@example.com', 'Otra Persona')
        self.ver(self.psi.url_publica)
        self.ver(self.psi.url_publica)
        self.ver(otra.url_publica)
        self.assertEqual(sum(VisitaPerfil.objects.filter(psicologo=self.psi).values_list('cantidad', flat=True)), 2)
        self.assertEqual(sum(VisitaPerfil.objects.filter(psicologo=otra).values_list('cantidad', flat=True)), 1)
        self.assertEqual(self.visitas_de(self.psi.url_publica), 2)   # y también como página

    def test_los_robots_no_suman_al_perfil(self):
        self.ver(self.psi.url_publica, agente='Mozilla/5.0 (compatible; bingbot/2.0)')
        self.assertFalse(VisitaPerfil.objects.exists())

    def test_la_visita_del_propio_profesional_no_cuenta(self):
        self.client.force_login(self.psi.usuario)
        self.ver(self.psi.url_publica)
        self.assertFalse(VisitaPerfil.objects.exists())

    def test_la_visita_de_otro_profesional_si_cuenta(self):
        otra = self._psi('otra@example.com', 'Otra Persona')
        self.client.force_login(otra.usuario)
        self.ver(self.psi.url_publica)
        self.assertEqual(VisitaPerfil.objects.filter(psicologo=self.psi).count(), 1)

    def test_el_link_viejo_redirige_y_cuenta_una_sola_vez(self):
        self.ver(f'/peru/p/{self.psi.pk}/', follow=True)
        self.assertEqual(sum(VisitaPerfil.objects.filter(psicologo=self.psi).values_list('cantidad', flat=True)), 1)

    def test_un_perfil_no_publicado_no_suma(self):
        Psicologo.objects.filter(pk=self.psi.pk).update(publicado_por_usuario=False)
        self.ver(self.psi.url_publica)
        self.assertFalse(VisitaPerfil.objects.exists())


class ResumenTests(_Base):
    def _cargar(self, dias_atras, cantidad):
        VisitaPerfil.objects.create(fecha=self.hoy - datetime.timedelta(days=dias_atras), psicologo=self.psi, cantidad=cantidad)

    def test_resumen_del_profesional(self):
        self._cargar(0, 3)
        self._cargar(2, 4)
        self._cargar(20, 5)
        self._cargar(60, 10)
        r = visitas.resumen_perfil(self.psi)
        self.assertEqual((r['hoy'], r['siete'], r['treinta'], r['total']), (3, 7, 12, 22))
        self.assertEqual(len(r['dias']), 7)
        self.assertEqual(r['dias'][-1], (self.hoy, 3))

    def test_el_profesional_ve_sus_numeros_en_su_cuenta(self):
        self._cargar(0, 3)
        self.client.force_login(self.psi.usuario)
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertContains(resp, 'Visitas a tu perfil público')
        self.assertContains(resp, 'últimos 7 días')
        self.assertContains(resp, 'No se cuentan robots ni tus propias visitas')
        self.assertEqual(resp.context['visitas']['hoy'], 3)

    def test_cada_profesional_ve_solo_las_suyas(self):
        otra = self._psi('otra@example.com', 'Otra Persona')
        VisitaPerfil.objects.create(fecha=self.hoy, psicologo=otra, cantidad=99)
        self._cargar(0, 1)
        self.client.force_login(self.psi.usuario)
        self.assertEqual(self.client.get(reverse('portal_dashboard')).context['visitas']['total'], 1)


class ReporteDelAdminTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser('admin_rep', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)
        self.url = reverse('admin:directorio_psicologo_visitas')

    def test_el_reporte_muestra_profesionales_y_paginas(self):
        VisitaPerfil.objects.create(fecha=self.hoy, psicologo=self.psi, cantidad=5)
        Visita.objects.create(fecha=self.hoy, pagina='/peru/buscar/', cantidad=9)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ana Pérez')
        self.assertContains(resp, '/peru/buscar/')
        self.assertContains(resp, 'no se incluyen robots')

    def test_ordena_a_los_profesionales_por_visitas(self):
        otra = self._psi('otra@example.com', 'Otra Persona')
        VisitaPerfil.objects.create(fecha=self.hoy, psicologo=otra, cantidad=10)
        VisitaPerfil.objects.create(fecha=self.hoy, psicologo=self.psi, cantidad=2)
        filas = self.client.get(self.url).context['profesionales']
        self.assertEqual([f['psicologo'].nombre for f in filas], ['Otra Persona', 'Ana Pérez'])

    def test_el_inicio_del_admin_tiene_el_boton(self):
        self.assertContains(self.client.get(reverse('admin:index')), self.url)

    def test_quien_no_es_admin_no_puede_verlo(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_las_visitas_son_de_solo_lectura_en_el_admin(self):
        self.assertEqual(self.client.get(reverse('admin:directorio_visita_add')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:directorio_visita_changelist')).status_code, 200)


class DetectorDeRobotsTests(TestCase):
    def test_distingue_personas_de_robots(self):
        fabrica = RequestFactory()
        self.assertFalse(es_bot(fabrica.get('/', HTTP_USER_AGENT=NAVEGADOR)))
        self.assertFalse(es_bot(fabrica.get('/', HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1')))
        self.assertTrue(es_bot(fabrica.get('/', HTTP_USER_AGENT='Googlebot/2.1')))
        self.assertTrue(es_bot(fabrica.get('/')))
        self.assertTrue(es_bot(fabrica.get('/', HTTP_USER_AGENT='x')))
