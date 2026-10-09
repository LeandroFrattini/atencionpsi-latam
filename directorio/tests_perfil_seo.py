"""Perfil con la URL por nombre, páginas por ciudad y por especialidad,
especialidades moderadas y sitemap (2026-10)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from turnos.models import TipoSesion

from .models import Ciudad, Especialidad, Orientacion, Pais, Psicologo
from .taxonomia import buscar_o_proponer


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True,
        )
        self.lima = Ciudad.objects.create(pais=self.pais, nombre='Lima', aprobado=True)
        self.cusco = Ciudad.objects.create(pais=self.pais, nombre='Cusco', aprobado=True)
        self.orientacion = Orientacion.objects.get_or_create(nombre='Cognitivo conductual')[0]
        self.ansiedad = Especialidad.objects.get(nombre='Ansiedad')
        self.psi = self._psi('ana@example.com', 'Lic. Ana Pérez Gómez', 'Lima')

    def _psi(self, email, nombre, ciudad, publicado=True):
        usuario = User.objects.create_user(email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre=nombre, matricula='123', whatsapp='51999999999',
            bio='Bio de prueba', foto='psicologos/test.jpg', ciudad=ciudad,
            suscripcion_activa=publicado, publicado_por_usuario=publicado,
        )
        psi.orientaciones.add(self.orientacion)
        return psi


class SlugYUrlTests(_Base):
    def test_el_slug_saca_los_titulos_y_termina_con_el_id(self):
        self.assertEqual(self.psi.slug_url, f'ana-perez-gomez-{self.psi.pk}')
        self.assertEqual(self.psi.url_publica, f'/peru/psicologo/ana-perez-gomez-{self.psi.pk}/')

    def test_las_ciudades_sembradas_tienen_slug_unico_por_pais(self):
        self.assertEqual(self.lima.slug, 'lima')
        mal = Ciudad.objects.filter(slug='')
        self.assertFalse(mal.exists())

    def test_el_slug_de_especialidad_se_genera_solo(self):
        e = Especialidad.objects.create(nombre='Procrastinación', aprobado=False)
        self.assertEqual(e.slug, 'procrastinacion')


class PerfilTests(_Base):
    def test_el_perfil_responde_en_la_url_con_nombre(self):
        resp = self.client.get(self.psi.url_publica)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<h1>Lic. Ana Pérez Gómez</h1>', html=False)
        self.assertContains(resp, 'Psicólogo/a en Lima')

    def test_la_url_vieja_redirige_con_301_a_la_nueva(self):
        resp = self.client.get(f'/peru/p/{self.psi.pk}/')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], self.psi.url_publica)

    def test_slug_incorrecto_con_el_id_bueno_redirige_a_la_url_canonica(self):
        resp = self.client.get(f'/peru/psicologo/otro-nombre-{self.psi.pk}/')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], self.psi.url_publica)

    def test_no_publicado_da_404_en_ambas_urls(self):
        psi = self._psi('b@example.com', 'Beto Sin Pago', 'Lima', publicado=False)
        self.assertEqual(self.client.get(psi.url_publica).status_code, 404)
        self.assertEqual(self.client.get(f'/peru/p/{psi.pk}/').status_code, 404)

    def test_slug_sin_id_da_404(self):
        self.assertEqual(self.client.get('/peru/psicologo/ana/').status_code, 404)

    def test_muestra_precios_y_duracion_de_las_sesiones(self):
        TipoSesion.objects.create(psicologo=self.psi, nombre='Individual', duracion_min=50, precio=13990)
        resp = self.client.get(self.psi.url_publica)
        self.assertContains(resp, 'Individual')
        self.assertContains(resp, '50 min')
        self.assertContains(resp, '13.990')
        self.assertContains(resp, 'Reservar turno')

    def test_muestra_especialidades_aprobadas_y_no_las_pendientes(self):
        pendiente = Especialidad.objects.create(nombre='Tema Pendiente', aprobado=False, propuesto_por=self.psi)
        self.psi.especialidades.set([self.ansiedad, pendiente])
        resp = self.client.get(self.psi.url_publica)
        self.assertContains(resp, 'Ansiedad')
        self.assertNotContains(resp, 'Tema Pendiente')
        self.assertContains(resp, '"knowsAbout": ["Ansiedad"]')

    def test_muestra_otros_psicologos_de_la_misma_ciudad(self):
        otro = self._psi('c@example.com', 'Carla Otra Colega', 'Lima')
        resp = self.client.get(self.psi.url_publica)
        self.assertContains(resp, 'Otros psicólogos en Lima')
        self.assertContains(resp, otro.url_publica)

    def test_las_migas_enlazan_a_la_ciudad(self):
        resp = self.client.get(self.psi.url_publica)
        self.assertContains(resp, reverse('psicologos_en_ciudad', args=['peru', 'lima']))


class LandingCiudadTests(_Base):
    def test_lista_los_profesionales_de_la_ciudad(self):
        cusqueno = self._psi('d@example.com', 'Dario Cusqueño', 'Cusco')
        resp = self.client.get(reverse('psicologos_en_ciudad', args=['peru', 'lima']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Psicólogos en Lima')
        self.assertContains(resp, self.psi.url_publica)
        self.assertNotContains(resp, cusqueno.url_publica)
        self.assertContains(resp, 'index, follow')

    def test_ciudad_sin_profesionales_queda_en_noindex(self):
        resp = self.client.get(reverse('psicologos_en_ciudad', args=['peru', 'cusco']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'noindex, follow')
        self.assertContains(resp, 'Todavía no hay psicólogos publicados en Cusco')

    def test_ciudad_pendiente_o_inexistente_da_404(self):
        Ciudad.objects.create(pais=self.pais, nombre='Pueblo Nuevo', aprobado=False)
        self.assertEqual(self.client.get('/peru/psicologos-en-pueblo-nuevo/').status_code, 404)
        self.assertEqual(self.client.get('/peru/psicologos-en-no-existe/').status_code, 404)

    def test_pais_externo_no_tiene_paginas(self):
        Pais.objects.create(
            nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS',
            activo=True, es_externo=True, url_externa='https://atencionpsi.com.ar',
        )
        self.assertEqual(self.client.get('/argentina/psicologos-en-lima/').status_code, 404)


class LandingEspecialidadTests(_Base):
    def test_lista_solo_a_quienes_la_tienen_aprobada(self):
        self.psi.especialidades.add(self.ansiedad)
        sin = self._psi('e@example.com', 'Eva Sin Tema', 'Lima')
        resp = self.client.get(reverse('psicologos_por_especialidad', args=['peru', 'ansiedad']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.psi.url_publica)
        self.assertNotContains(resp, sin.url_publica)
        self.assertContains(resp, 'Psicólogos para ansiedad en Perú')

    def test_especialidad_sin_profesionales_queda_en_noindex(self):
        resp = self.client.get(reverse('psicologos_por_especialidad', args=['peru', 'ansiedad']))
        self.assertContains(resp, 'noindex, follow')

    def test_especialidad_pendiente_da_404(self):
        Especialidad.objects.create(nombre='Tema Raro', aprobado=False)
        self.assertEqual(self.client.get('/peru/psicologos-para-tema-raro/').status_code, 404)


class BuscadorEspecialidadTests(_Base):
    def test_el_filtro_por_especialidad_funciona(self):
        self.psi.especialidades.add(self.ansiedad)
        otro = self._psi('f@example.com', 'Fede Otro', 'Lima')
        resp = self.client.get(reverse('buscador_pais', args=['peru']), {'especialidad': self.ansiedad.pk})
        self.assertContains(resp, self.psi.url_publica)
        self.assertNotContains(resp, otro.url_publica)

    def test_el_desplegable_ofrece_solo_especialidades_aprobadas(self):
        Especialidad.objects.create(nombre='Tema Pendiente', aprobado=False)
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, '>Ansiedad</option>')
        self.assertNotContains(resp, 'Tema Pendiente')


class ModeracionEspecialidadTests(_Base):
    def test_proponer_una_especialidad_nueva_nace_pendiente(self):
        obj, pendiente = buscar_o_proponer(Especialidad, 'Procrastinación', self.psi)
        self.assertTrue(pendiente)
        self.assertFalse(obj.aprobado)

    def test_proponer_una_que_ya_existe_ignora_tildes_y_la_reusa(self):
        antes = Especialidad.objects.count()
        obj, pendiente = buscar_o_proponer(Especialidad, 'ANSIEDAD', self.psi)
        self.assertFalse(pendiente)
        self.assertEqual(obj.pk, self.ansiedad.pk)
        self.assertEqual(Especialidad.objects.count(), antes)

    def test_el_profesional_la_agrega_desde_su_perfil_y_queda_pendiente(self):
        self.client.force_login(self.psi.usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'especialidad_nueva')

    def test_el_aviso_del_admin_cuenta_las_especialidades_pendientes(self):
        from directorio.templatetags.moderacion_tags import propuestas_pendientes
        Especialidad.objects.create(nombre='Tema Pendiente', aprobado=False, propuesto_por=self.psi)
        textos = [i['texto'] for i in propuestas_pendientes()]
        self.assertIn('1 especialidad', textos)


class SitemapTests(_Base):
    def test_incluye_perfil_ciudades_y_especialidades_con_gente(self):
        self.psi.especialidades.add(self.ansiedad)
        contenido = self.client.get('/sitemap.xml').content.decode()
        self.assertIn(self.psi.url_publica, contenido)
        self.assertIn('/peru/psicologos-en-lima/', contenido)
        self.assertIn('/peru/psicologos-para-ansiedad/', contenido)

    def test_no_lista_paginas_vacias(self):
        contenido = self.client.get('/sitemap.xml').content.decode()
        self.assertNotIn('/peru/psicologos-en-cusco/', contenido)
        self.assertNotIn('/peru/psicologos-para-ansiedad/', contenido)


class HomePaisEnlacesTests(_Base):
    def test_el_home_enlaza_a_ciudades_y_especialidades_con_gente(self):
        self.psi.especialidades.add(self.ansiedad)
        resp = self.client.get(reverse('pais_home', args=['peru']))
        self.assertContains(resp, '/peru/psicologos-en-lima/')
        self.assertContains(resp, '/peru/psicologos-para-ansiedad/')
        self.assertNotContains(resp, '/peru/psicologos-en-cusco/')
