"""Barra nueva, Sobre nosotros y mezcla de destacados del inicio."""
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from . import destacados
from .models import Orientacion, Pais, Psicologo


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True, orden=1)
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True, orden=2)
        self.argentina = Pais.objects.create(
            nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS', activo=False, orden=0,
            es_externo=True, url_externa='https://atencionpsi.com.ar',
        )

    def _psi(self, pais, nombre, email):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=pais, nombre=nombre, matricula='1', whatsapp='51999999999', bio='bio',
            foto='psicologos/test.jpg', ciudad='Lima', suscripcion_activa=True, publicado_por_usuario=True,
        )
        psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0])
        return psi


class BarraTests(_Base):
    def test_trae_los_enlaces_principales_y_botones(self):
        resp = self.client.get(reverse('hub'))
        for texto in ('Inicio', 'Buscador', 'Sobre nosotros', 'Preguntas frecuentes', 'Portal profesional', 'Sumate al equipo'):
            self.assertContains(resp, texto)
        self.assertContains(resp, reverse('sobre_nosotros'))

    def test_marca_la_pagina_actual(self):
        resp = self.client.get(reverse('sobre_nosotros'))
        self.assertContains(resp, 'class="activo" aria-current="page">Sobre nosotros')

    def test_el_boton_sumate_lleva_al_registro_del_pais_actual(self):
        resp = self.client.get(reverse('pais_home', args=['chile']))
        self.assertContains(resp, reverse('portal_registro', args=['chile']))

    def test_argentina_inactiva_no_aparece_en_el_selector(self):
        self.assertNotContains(self.client.get(reverse('hub')), 'atencionpsi.com.ar')

    @mock.patch('directorio.destacados._feed_argentina', return_value=[])
    def test_argentina_activa_aparece_y_manda_al_com_ar(self, _feed):
        Pais.objects.filter(pk=self.argentina.pk).update(activo=True)
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'href="https://atencionpsi.com.ar"')
        self.assertContains(resp, 'img/flags/ar.svg')

    def test_tiene_el_menu_de_celular(self):
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'id="navToggle"')
        self.assertContains(resp, 'aria-controls="navMenu"')


class SobreNosotrosTests(_Base):
    def test_responde_y_tiene_el_tono_calido(self):
        resp = self.client.get(reverse('sobre_nosotros'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pedir ayuda es el primer paso')
        self.assertContains(resp, 'Cuidar a quienes cuidan')
        self.assertContains(resp, 'Con cariño')

    def test_enlaza_al_buscador_y_al_registro(self):
        resp = self.client.get(reverse('sobre_nosotros'))
        self.assertContains(resp, reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, reverse('portal_registro', args=['peru']))

    def test_aparece_en_el_sitemap_y_en_el_pie(self):
        self.assertIn('/sobre-nosotros/', self.client.get('/sitemap.xml').content.decode())
        self.assertContains(self.client.get(reverse('faq')), reverse('sobre_nosotros'))


@override_settings(ARGENTINA_FEED_URL='https://atencionpsi.com.ar/api/destacados/')
class MezclaTests(_Base):
    FEED = {'profesionales': [
        {'nombre': 'Ana Argentina', 'ciudad': 'Bahía Blanca', 'orientacion': 'Gestalt',
         'foto': 'https://atencionpsi.com.ar/media/a.jpg', 'url': 'https://atencionpsi.com.ar/psicologo/ana/'},
    ]}

    def _feed(self, datos=None):
        respuesta = mock.Mock()
        respuesta.json.return_value = datos if datos is not None else self.FEED
        return mock.patch('directorio.destacados.requests.get', return_value=respuesta)

    def test_mezcla_profesionales_de_varios_paises_con_su_bandera(self):
        self._psi(self.peru, 'Pe Uno', 'a@example.com')
        self._psi(self.chile, 'Chi Uno', 'b@example.com')
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'Psicólogos destacados')
        self.assertContains(resp, 'Pe Uno')
        self.assertContains(resp, 'Chi Uno')
        self.assertContains(resp, 'img/flags/pe.svg')
        self.assertContains(resp, 'img/flags/cl.svg')
        # La sección tiene que estar en el cuerpo de la página, no dentro del <title>.
        html = resp.content.decode()
        titulo = html[html.index('<title>'):html.index('</title>')]
        self.assertNotIn('mini-card', titulo)
        self.assertGreater(html.index('class="mix-destacados"'), html.index('<main>'))
        self.assertEqual(html.count('class="mini-card"'), 2)

    def test_el_orden_cambia_entre_visitas(self):
        for i in range(6):
            self._psi(self.peru if i % 2 else self.chile, f'Psi{i}', f'p{i}@example.com')
        ordenes = {tuple(d['nombre'] for d in destacados.mezcla_de_psicologos(6)) for _ in range(30)}
        self.assertGreater(len(ordenes), 1)

    def test_reparte_entre_paises_aunque_uno_tenga_muchos(self):
        for i in range(6):
            self._psi(self.peru, f'Pe{i}', f'pe{i}@example.com')
        self._psi(self.chile, 'Chi Unico', 'c@example.com')
        for _ in range(10):
            nombres = [d['nombre'] for d in destacados.mezcla_de_psicologos(4)]
            self.assertIn('Chi Unico', nombres)

    def test_el_inicio_muestra_diez_profesionales_en_dos_filas_de_cinco(self):
        """10 tarjetas más chicas (2 filas de 5) en vez de 8 (2 filas de 4)."""
        self.assertEqual(destacados.CANTIDAD_DESTACADOS_INICIO, 10)
        for i in range(8):
            self._psi(self.peru, f'Pe{i}', f'pe{i}@example.com')
        for i in range(8):
            self._psi(self.chile, f'Chi{i}', f'ch{i}@example.com')
        html = self.client.get(reverse('hub')).content.decode()
        self.assertEqual(html.count('class="mini-card"'), 10)
        # Y ambos países están representados (5 y 5), no solo el que tiene más.
        self.assertEqual(html.count('img/flags/pe.svg'), html.count('img/flags/cl.svg'))

    def test_si_hay_menos_de_diez_muestra_los_que_hay(self):
        for i in range(3):
            self._psi(self.peru, f'Pe{i}', f'pe{i}@example.com')
        html = self.client.get(reverse('hub')).content.decode()
        self.assertEqual(html.count('class="mini-card"'), 3)

    def test_la_grilla_del_inicio_es_de_cinco_columnas(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'static', 'css', 'base.css'), encoding='utf-8') as f:
            css = f.read()
        self.assertRegex(css, r'\.mix-grid \{[^}]*repeat\(5, minmax\(0, 1fr\)\)')

    def test_no_muestra_nada_si_no_hay_profesionales(self):
        self.assertNotContains(self.client.get(reverse('hub')), 'Psicólogos destacados')

    def test_no_incluye_perfiles_sin_publicar(self):
        psi = self._psi(self.peru, 'Oculto', 'o@example.com')
        Psicologo.objects.filter(pk=psi.pk).update(publicado_por_usuario=False)
        self.assertNotContains(self.client.get(reverse('hub')), 'Oculto')

    def test_incluye_a_los_de_argentina_si_esta_activa_y_abren_en_otra_pestana(self):
        Pais.objects.filter(pk=self.argentina.pk).update(activo=True)
        with self._feed():
            resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'Ana Argentina')
        self.assertContains(resp, 'href="https://atencionpsi.com.ar/psicologo/ana/" class="mini-card" target="_blank"')
        self.assertContains(resp, 'img/flags/ar.svg')

    def test_con_argentina_inactiva_no_consulta_el_feed(self):
        with self._feed() as pedido:
            self.client.get(reverse('hub'))
        pedido.assert_not_called()

    def test_si_el_feed_falla_el_inicio_sigue_andando(self):
        Pais.objects.filter(pk=self.argentina.pk).update(activo=True)
        self._psi(self.peru, 'Pe Uno', 'a@example.com')
        with mock.patch('directorio.destacados.requests.get', side_effect=Exception('sin red')):
            resp = self.client.get(reverse('hub'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pe Uno')
        self.assertNotContains(resp, 'Ana Argentina')

    def test_ignora_filas_del_feed_sin_nombre_o_sin_enlace(self):
        Pais.objects.filter(pk=self.argentina.pk).update(activo=True)
        malo = {'profesionales': [{'nombre': '', 'url': 'x'}, {'nombre': 'Sin url'}]}
        with self._feed(malo):
            self.assertEqual(destacados.mezcla_de_psicologos(8), [])

    def test_el_feed_se_guarda_unos_minutos(self):
        Pais.objects.filter(pk=self.argentina.pk).update(activo=True)
        with self._feed() as pedido:
            destacados.mezcla_de_psicologos(8)
            destacados.mezcla_de_psicologos(8)
        self.assertEqual(pedido.call_count, 1)


class SaludoDelProfesionalTests(_Base):
    def test_sin_sesion_se_ve_el_portal_profesional_y_sumate(self):
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'Portal profesional')
        self.assertContains(resp, 'Sumate al equipo')
        self.assertNotContains(resp, 'Hola, ')

    def test_con_sesion_de_profesional_dice_hola_con_su_nombre_y_oculta_el_portal(self):
        psi = self._psi(self.peru, 'Lic. María Gonzales', 'maria@example.com')
        self.client.force_login(psi.usuario)
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'Hola, María')
        self.assertContains(resp, reverse('portal_dashboard'))
        html = resp.content.decode()
        barra = html[html.index('<header'):html.index('</header>')]
        self.assertNotIn('Portal profesional', barra)
        self.assertNotIn('Sumate al equipo', barra)
        self.assertIn('Mi cuenta', html[html.index('<footer'):])

    def test_el_saludo_aparece_en_todas_las_paginas(self):
        psi = self._psi(self.peru, 'Camila Torres', 'camila@example.com')
        self.client.force_login(psi.usuario)
        for url in (reverse('faq'), reverse('sobre_nosotros'), reverse('buscador_pais', args=['peru']), reverse('portal_dashboard')):
            self.assertContains(self.client.get(url), 'Hola, Camila', msg_prefix=url)

    def test_una_cuenta_que_no_es_de_profesional_sigue_viendo_el_portal(self):
        admin = User.objects.create_superuser('admin_nav', 'a@example.com', 'ClaveSegura123')
        self.client.force_login(admin)
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'Portal profesional')
        self.assertNotContains(resp, 'Hola, ')

    def test_nombre_corto_saca_los_titulos(self):
        for nombre, esperado in (('Lic. María Gonzales', 'María'), ('Mg. Dr. Pedro Pérez', 'Pedro'), ('Camila Torres', 'Camila'), ('  Dra.   Ana', 'Ana')):
            self.assertEqual(Psicologo(nombre=nombre).nombre_corto, esperado)
