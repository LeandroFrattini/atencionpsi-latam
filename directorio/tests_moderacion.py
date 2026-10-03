"""Orientaciones, públicos y ciudades que escribe un profesional a mano:
nacen pendientes, las ve solo él y la dueña las aprueba desde el admin
(2026-10-02)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Ciudad, Orientacion, Pais, Psicologo, Publico
from .taxonomia import buscar_o_proponer, clave


class ListasBaseTests(TestCase):
    """Sembradas por la migración 0015 (el test DB las corre igual que producción)."""

    def test_hay_lista_base_de_orientaciones_y_publicos_aprobada(self):
        self.assertTrue(Orientacion.objects.filter(nombre='Psicoanálisis', aprobado=True).exists())
        self.assertTrue(Orientacion.objects.filter(nombre='EMDR / Trauma', aprobado=True).exists())
        self.assertTrue(Publico.objects.filter(nombre='Adultos mayores', aprobado=True).exists())

    def test_hay_ciudades_de_cada_pais_activo(self):
        for slug, ciudad in (('peru', 'Lima'), ('uruguay', 'Montevideo'), ('chile', 'Santiago')):
            self.assertTrue(
                Ciudad.objects.filter(pais__slug=slug, nombre=ciudad, aprobado=True).exists(), f'{slug}: {ciudad}',
            )

    def test_cada_pais_activo_tiene_bastantes_ciudades(self):
        for slug in ('peru', 'uruguay', 'chile'):
            self.assertGreaterEqual(Ciudad.objects.filter(pais__slug=slug).count(), 30, slug)

    def test_no_se_repiten_ciudades_dentro_de_un_pais_ignorando_tildes(self):
        for pais in Pais.objects.filter(es_externo=False):
            claves = [clave(c.nombre) for c in Ciudad.objects.filter(pais=pais)]
            self.assertEqual(len(claves), len(set(claves)), pais.slug)


class ClaveYProponerTests(TestCase):
    def test_clave_ignora_mayusculas_tildes_y_espacios(self):
        self.assertEqual(clave('  Psicoanálisis '), clave('psicoanalisis'))

    def test_proponer_algo_nuevo_lo_crea_pendiente(self):
        obj, pendiente = buscar_o_proponer(Publico, 'Surfistas', None)
        self.assertTrue(pendiente)
        self.assertFalse(obj.aprobado)

    def test_proponer_algo_que_ya_esta_lo_reusa(self):
        antes = Publico.objects.count()
        obj, pendiente = buscar_o_proponer(Publico, 'ADULTOS', None)
        self.assertFalse(pendiente)
        self.assertTrue(obj.aprobado)
        self.assertEqual(Publico.objects.count(), antes)

    def test_texto_vacio_no_crea_nada(self):
        self.assertEqual(buscar_o_proponer(Publico, '   ', None), (None, False))


class VisibilidadPublicaTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True,
        )
        usuario = User.objects.create_user('p@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre='Psi Test', matricula='1', whatsapp='51999999999',
            bio='bio', foto='psicologos/test.jpg', suscripcion_activa=True, publicado_por_usuario=True,
            ciudad='Pisco Elqui',
        )
        self.aprobada = Orientacion.objects.create(nombre='Aprobada X')
        self.pendiente = Orientacion.objects.create(nombre='Pendiente X', aprobado=False, propuesto_por=self.psi)
        self.publico_ok = Publico.objects.create(nombre='Público Ok')
        self.publico_pend = Publico.objects.create(
            nombre='Público Pendiente', aprobado=False, propuesto_por=self.psi,
        )
        self.psi.orientaciones.set([self.aprobada, self.pendiente])
        self.psi.publicos.set([self.publico_ok, self.publico_pend])
        Ciudad.objects.create(pais=self.pais, nombre='Pisco Elqui', aprobado=False, propuesto_por=self.psi)

    def test_propiedades_publicas_solo_devuelven_lo_aprobado(self):
        self.assertEqual([o.nombre for o in self.psi.orientaciones_publicas], ['Aprobada X'])
        self.assertEqual([p.nombre for p in self.psi.publicos_publicos], ['Público Ok'])
        self.assertEqual(self.psi.ciudad_publica, '')

    def test_una_ciudad_que_no_esta_en_la_tabla_se_muestra_igual(self):
        psi = Psicologo.objects.get(pk=self.psi.pk)
        psi.ciudad = 'Pueblo Chico'
        self.assertEqual(psi.ciudad_publica, 'Pueblo Chico')

    def test_la_tarjeta_del_buscador_no_muestra_lo_pendiente(self):
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, 'Aprobada X')
        self.assertContains(resp, 'Público Ok')
        self.assertNotContains(resp, 'Pendiente X')
        self.assertNotContains(resp, 'Público Pendiente')
        self.assertNotContains(resp, 'Pisco Elqui')

    def test_los_filtros_del_buscador_no_ofrecen_lo_pendiente(self):
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        # Se chequea por el texto de la opción (no por el id: los ids de
        # orientaciones y públicos se pisan entre sí).
        self.assertContains(resp, '>Aprobada X</option>')
        self.assertContains(resp, '>Público Ok</option>')
        self.assertNotContains(resp, '>Pendiente X</option>')
        self.assertNotContains(resp, '>Público Pendiente</option>')
        self.assertNotContains(resp, '>Pisco Elqui</option>')

    def test_el_perfil_publico_no_filtra_la_ciudad_pendiente(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.psi.pk]))
        self.assertNotContains(resp, 'Pisco Elqui')

    def test_al_aprobar_pasa_a_verse_en_lo_publico(self):
        Orientacion.objects.filter(pk=self.pendiente.pk).update(aprobado=True)
        Ciudad.objects.filter(nombre='Pisco Elqui').update(aprobado=True)
        psi = Psicologo.objects.get(pk=self.psi.pk)
        self.assertIn('Pendiente X', [o.nombre for o in psi.orientaciones_publicas])
        self.assertEqual(psi.ciudad_publica, 'Pisco Elqui')


class AdminModeracionTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser('admin_mod', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)

    def test_aprobar_seleccionados_aprueba_publicos_pendientes(self):
        p = Publico.objects.create(nombre='Surfistas', aprobado=False)
        resp = self.client.post(reverse('admin:directorio_publico_changelist'), {
            'action': 'aprobar_seleccionados', '_selected_action': [p.pk],
        })
        self.assertEqual(resp.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.aprobado)

    def test_aprobar_seleccionados_aprueba_ciudades_pendientes(self):
        pais = Pais.objects.get(slug='peru')
        c = Ciudad.objects.create(pais=pais, nombre='Pisco Elqui', aprobado=False)
        self.client.post(reverse('admin:directorio_ciudad_changelist'), {
            'action': 'aprobar_seleccionados', '_selected_action': [c.pk],
        })
        c.refresh_from_db()
        self.assertTrue(c.aprobado)

    def test_el_inicio_del_admin_avisa_si_hay_propuestas_pendientes(self):
        Publico.objects.create(nombre='Surfistas', aprobado=False)
        Orientacion.objects.create(nombre='Biodanza', aprobado=False)
        resp = self.client.get(reverse('admin:index'))
        self.assertContains(resp, 'Propuestas de profesionales para revisar')
        self.assertContains(resp, '1 público')
        self.assertContains(resp, '1 orientación')

    def test_el_inicio_del_admin_no_avisa_si_no_hay_nada_pendiente(self):
        resp = self.client.get(reverse('admin:index'))
        self.assertNotContains(resp, 'Propuestas de profesionales para revisar')

    def test_las_listas_de_moderacion_cargan(self):
        for nombre in ('ciudad', 'orientacion', 'publico'):
            resp = self.client.get(reverse(f'admin:directorio_{nombre}_changelist'))
            self.assertEqual(resp.status_code, 200, nombre)
