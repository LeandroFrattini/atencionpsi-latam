"""Buscador: búsqueda por palabras, filtros, orden, fragmento en vivo, filtros activos y vacíos."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import buscador
from .models import Ciudad, Especialidad, Orientacion, Pais, Psicologo, Publico


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
            activo=True, muestra_precio_sesion=True,
        )
        self.ansiedad = Especialidad.objects.get(nombre='Ansiedad')
        self.duelo = Especialidad.objects.get(nombre='Duelo y pérdidas')
        self.psicoanalisis = Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0]
        self.gestalt = Orientacion.objects.get_or_create(nombre='Gestalt')[0]
        self.adultos = Publico.objects.get_or_create(nombre='Adultos')[0]
        self.ana = self._psi('ana@example.com', 'Ana Pérez', 'Lima', 'online', 120, [self.ansiedad], [self.psicoanalisis], 'Acompaño procesos de ansiedad en adultos.')
        self.beto = self._psi('beto@example.com', 'Beto Núñez', 'Arequipa', 'presencial', 80, [self.duelo], [self.gestalt], 'Trabajo con duelos y pérdidas.')
        self.carla = self._psi('carla@example.com', 'Carla Ríos', 'Lima', 'ambas', 100, [self.ansiedad, self.duelo], [self.gestalt], '')

    def _psi(self, email, nombre, ciudad, modalidad, precio, esp, orient, bio):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre=nombre, matricula='1', whatsapp='51999999999', bio=bio or 'bio',
            foto='psicologos/test.jpg', ciudad=ciudad, modalidad=modalidad, precio_sesion=precio,
            suscripcion_activa=True, publicado_por_usuario=True,
        )
        psi.especialidades.set(esp)
        psi.orientaciones.set(orient)
        psi.publicos.set([self.adultos])
        return psi

    def buscar(self, **params):
        return self.client.get(reverse('buscador_pais', args=['peru']), params)

    def nombres(self, resp):
        return [p.nombre for p in resp.context['psicologos']]


class BusquedaPorPalabrasTests(_Base):
    def test_encuentra_por_ciudad_sin_importar_tildes_ni_mayusculas(self):
        self.assertEqual(sorted(self.nombres(self.buscar(q='LIMA'))), ['Ana Pérez', 'Carla Ríos'])

    def test_encuentra_por_nombre_sin_tildes(self):
        self.assertEqual(self.nombres(self.buscar(q='nunez')), ['Beto Núñez'])

    def test_encuentra_por_motivo_y_por_enfoque(self):
        self.assertEqual(sorted(self.nombres(self.buscar(q='duelo'))), ['Beto Núñez', 'Carla Ríos'])
        self.assertEqual(self.nombres(self.buscar(q='psicoanalisis')), ['Ana Pérez'])

    def test_busca_tambien_en_la_descripcion(self):
        self.assertEqual(self.nombres(self.buscar(q='procesos')), ['Ana Pérez'])

    def test_todas_las_palabras_tienen_que_coincidir(self):
        self.assertEqual(self.nombres(self.buscar(q='ansiedad lima')), ['Ana Pérez', 'Carla Ríos'])
        self.assertEqual(self.nombres(self.buscar(q='ansiedad arequipa')), [])

    def test_ignora_palabras_vacias_como_psicologo_en(self):
        self.assertEqual(sorted(self.nombres(self.buscar(q='psicólogo en Lima'))), ['Ana Pérez', 'Carla Ríos'])

    def test_lo_que_coincide_en_el_nombre_va_primero(self):
        # "ana" está en el nombre de Ana y en la descripción ("ansiedad" no, pero 'procesos de ansiedad en adultos' sí contiene 'an')
        resp = self.buscar(q='ana')
        self.assertEqual(self.nombres(resp)[0], 'Ana Pérez')

    def test_sin_resultados_muestra_salida_en_vez_de_una_pagina_vacia(self):
        resp = self.buscar(q='zzzzz')
        self.assertContains(resp, 'No encontramos a nadie con esa búsqueda')
        self.assertContains(resp, 'Ver todos los psicólogos')
        self.assertContains(resp, 'Escribinos y te ayudamos')
        self.assertContains(resp, 'chip-filtro')   # motivos para seguir explorando

    def test_no_incluye_a_quien_no_esta_publicado(self):
        Psicologo.objects.filter(pk=self.ana.pk).update(publicado_por_usuario=False)
        self.assertNotIn('Ana Pérez', self.nombres(self.buscar(q='lima')))


class FiltrosTests(_Base):
    def test_modalidad_online_incluye_a_quienes_atienden_en_ambas(self):
        self.assertEqual(sorted(self.nombres(self.buscar(modalidad='online'))), ['Ana Pérez', 'Carla Ríos'])

    def test_modalidad_presencial_incluye_a_quienes_atienden_en_ambas(self):
        self.assertEqual(sorted(self.nombres(self.buscar(modalidad='presencial'))), ['Beto Núñez', 'Carla Ríos'])

    def test_los_links_viejos_con_ids_siguen_funcionando(self):
        self.assertEqual(sorted(self.nombres(self.buscar(especialidad=self.duelo.pk))), ['Beto Núñez', 'Carla Ríos'])
        self.assertEqual(sorted(self.nombres(self.buscar(orientacion=self.gestalt.pk))), ['Beto Núñez', 'Carla Ríos'])
        self.assertEqual(len(self.nombres(self.buscar(publico=self.adultos.pk))), 3)
        self.assertEqual(sorted(self.nombres(self.buscar(ciudad='lima'))), ['Ana Pérez', 'Carla Ríos'])

    def test_se_combinan_texto_y_filtros(self):
        self.assertEqual(self.nombres(self.buscar(q='ansiedad', modalidad='presencial')), ['Carla Ríos'])

    def test_valores_raros_no_rompen_la_pagina(self):
        resp = self.buscar(modalidad='cualquiera', orden='inventado', especialidad='abc', q='  ')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.nombres(resp)), 3)

    def test_los_desplegables_solo_ofrecen_lo_que_tiene_alguien_publicado(self):
        Especialidad.objects.create(nombre='Tema sin nadie', aprobado=True)
        Ciudad.objects.create(pais=self.pais, nombre='Ciudad vacía', aprobado=True)
        resp = self.buscar()
        self.assertNotContains(resp, 'Tema sin nadie')
        self.assertNotContains(resp, 'Ciudad vacía')
        self.assertContains(resp, '>Duelo y pérdidas</option>')


class OrdenTests(_Base):
    def test_por_precio(self):
        self.assertEqual(self.nombres(self.buscar(orden='precio_asc')), ['Beto Núñez', 'Carla Ríos', 'Ana Pérez'])
        self.assertEqual(self.nombres(self.buscar(orden='precio_desc')), ['Ana Pérez', 'Carla Ríos', 'Beto Núñez'])

    def test_por_nombre(self):
        self.assertEqual(self.nombres(self.buscar(orden='nombre')), ['Ana Pérez', 'Beto Núñez', 'Carla Ríos'])

    def test_los_destacados_van_primero_por_defecto(self):
        Psicologo.objects.filter(pk=self.carla.pk).update(destacado=True)
        self.assertEqual(self.nombres(self.buscar())[0], 'Carla Ríos')

    def test_sin_precio_visible_en_el_pais_no_se_ofrece_ordenar_por_precio(self):
        Pais.objects.filter(pk=self.pais.pk).update(muestra_precio_sesion=False)
        resp = self.buscar(orden='precio_asc')
        self.assertNotContains(resp, 'Menor precio')


class VivoYFiltrosActivosTests(_Base):
    def test_el_fragmento_trae_solo_la_parte_que_cambia(self):
        resp = self.buscar(q='lima', fragmento=1)
        html = resp.content.decode()
        self.assertNotIn('<html', html)
        self.assertNotIn('<header', html)
        self.assertIn('psicologos-grid', html)
        self.assertIn('data-q="lima"', html)

    def test_la_pagina_completa_trae_el_buscador_y_las_sugerencias(self):
        resp = self.buscar()
        self.assertContains(resp, 'id="q"')
        self.assertContains(resp, 'role="combobox"')
        self.assertContains(resp, 'id="sugerencias-datos"')
        sugerencias = resp.context['sugerencias']
        tipos = {s['t'] for s in sugerencias}
        self.assertEqual(tipos, {'ciudad', 'motivo', 'enfoque', 'publico', 'profesional'})

    def test_las_sugerencias_traen_cantidad_de_profesionales(self):
        lima = next(s for s in self.buscar().context['sugerencias'] if s['t'] == 'ciudad' and s['n'] == 'Lima')
        self.assertEqual(lima['c'], 2)

    def test_los_filtros_activos_se_pueden_quitar_uno_por_uno(self):
        resp = self.buscar(q='ansiedad', modalidad='online', ciudad='Lima')
        pills = {p['etiqueta']: p['quitar'] for p in resp.context['pills']}
        self.assertEqual(set(pills), {'“ansiedad”', 'Online', 'Lima'})
        self.assertNotIn('ciudad=', pills['Lima'])
        self.assertIn('modalidad=online', pills['Lima'])
        self.assertNotIn('q=', pills['“ansiedad”'])

    def test_sin_filtros_no_hay_pills_ni_limpiar(self):
        resp = self.buscar()
        self.assertNotContains(resp, 'Limpiar todo')
        self.assertEqual(resp.context['pills'], [])

    def test_los_chips_de_motivos_alternan_el_filtro(self):
        resp = self.buscar()
        chip = next(c for c in resp.context['motivos_chips'] if c['nombre'] == 'Ansiedad')
        self.assertFalse(chip['activo'])
        self.assertIn(f'especialidad={self.ansiedad.pk}', chip['url'])
        activo = next(c for c in self.buscar(especialidad=self.ansiedad.pk).context['motivos_chips'] if c['nombre'] == 'Ansiedad')
        self.assertTrue(activo['activo'])
        self.assertNotIn('especialidad=', activo['url'])   # un segundo clic lo quita

    def test_el_contador_habla_en_singular(self):
        self.assertContains(self.buscar(q='nunez'), '<strong>1</strong> psicólogo/a')

    def test_pais_sin_profesionales_invita_a_sumarse(self):
        Psicologo.objects.all().delete()
        resp = self.buscar()
        self.assertContains(resp, 'Todavía no hay psicólogos publicados en Perú')
        self.assertContains(resp, reverse('portal_registro', args=['peru']))

    def test_argentina_sigue_redirigiendo_afuera(self):
        Pais.objects.create(nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS',
                            activo=True, es_externo=True, url_externa='https://atencionpsi.com.ar')
        resp = self.client.get('/argentina/buscar/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://atencionpsi.com.ar')


class NormalizacionTests(TestCase):
    def test_palabras_saca_las_vacias_y_normaliza(self):
        self.assertEqual(buscador.palabras('Busco PSICÓLOGA para ansiedad en Lima'), ['ansiedad', 'lima'])
        self.assertEqual(buscador.palabras('   '), [])
