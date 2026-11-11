"""'Hago factura para reintegro': casilla en el perfil (todos los países) y tilde en el perfil público y en las tarjetas."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Orientacion, Pais, Psicologo

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        # Perú muestra el precio de sesión en el perfil; Chile no: la casilla tiene que estar en los dos.
        self.peru = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN',
                                        activo=True, muestra_precio_sesion=True, codigo_telefono='51')
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP',
                                         activo=True, muestra_precio_sesion=False, codigo_telefono='56')
        self.orientacion, _ = Orientacion.objects.get_or_create(nombre='Sistémica')
        self.n = 0

    def psi(self, pais=None, **extra):
        self.n += 1
        email = f'psi{self.n}@example.com'
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        datos = dict(usuario=usuario, pais=pais or self.chile, nombre=f'Ana Número{self.n}', matricula='123',
                     whatsapp='56912345678', bio='Bio.', foto='psicologos/test.jpg', suscripcion_activa=True,
                     publicado_por_usuario=True)
        datos.update(extra)
        psi = Psicologo.objects.create(**datos)
        psi.orientaciones.add(self.orientacion)
        return psi


class EditorTests(_Base):
    def test_la_casilla_esta_en_el_editor_de_todos_los_paises(self):
        for pais in (self.peru, self.chile):
            psi = self.psi(pais)
            self.client.force_login(psi.usuario)
            resp = self.client.get(reverse('portal_editar_perfil'))
            self.assertContains(resp, 'name="hace_factura"', msg_prefix=pais.nombre)
            self.assertContains(resp, 'Hago factura para reintegro', msg_prefix=pais.nombre)

    def _post(self, **extra):
        datos = {
            'nombre': 'Ana', 'matricula': '123', 'whatsapp': '56912345678', 'ciudad': '', 'modalidad': 'online',
            'bio': 'Bio.', 'docencia': '', 'orientaciones': [self.orientacion.pk],
            'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
            'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000',
        }
        datos.update(extra)
        return self.client.post(reverse('portal_editar_perfil'), datos)

    def test_tildarla_la_guarda_y_destildarla_la_saca(self):
        psi = self.psi()
        self.client.force_login(psi.usuario)
        self._post(hace_factura='on')
        psi.refresh_from_db()
        self.assertTrue(psi.hace_factura)
        self._post()   # sin la casilla en el envío = destildada
        psi.refresh_from_db()
        self.assertFalse(psi.hace_factura)

    def test_por_defecto_viene_destildada(self):
        self.assertFalse(self.psi().hace_factura)

    def test_la_vista_previa_en_vivo_del_editor_la_incluye(self):
        psi = self.psi()
        self.client.force_login(psi.usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, "campo('hace_factura')")
        self.assertContains(resp, 'Factura para reintegro')


class PublicoTests(_Base):
    def test_el_perfil_publico_muestra_el_tilde_solo_si_la_tildo(self):
        con = self.psi(hace_factura=True)
        sin = self.psi()
        self.assertContains(self.client.get(con.url_publica, **UA), 'Hace factura para reintegro')
        self.assertNotContains(self.client.get(sin.url_publica, **UA), 'Hace factura para reintegro')

    def test_la_tarjeta_del_buscador_la_muestra_solo_a_quien_corresponde(self):
        self.psi(hace_factura=True)
        resp = self.client.get(reverse('buscador_pais', args=['chile']), **UA)
        self.assertContains(resp, 'Factura para reintegro')
        self.assertEqual(resp.content.decode().count('Factura para reintegro'), 1)
        Psicologo.objects.update(hace_factura=False)
        self.assertNotContains(self.client.get(reverse('buscador_pais', args=['chile']), **UA), 'Factura para reintegro')

    def test_la_vista_previa_del_portal_tambien_la_muestra(self):
        psi = self.psi(hace_factura=True, publicado_por_usuario=False)
        self.client.force_login(psi.usuario)
        self.assertContains(self.client.get(reverse('portal_vista_previa')), 'Hace factura para reintegro')


class AdminTests(_Base):
    def test_se_puede_filtrar_por_hace_factura(self):
        con = self.psi(hace_factura=True)
        sin = self.psi()
        self.client.force_login(User.objects.create_superuser('a@example.com', 'a@example.com', 'ClaveSegura123'))
        resp = self.client.get(reverse('admin:directorio_psicologo_changelist'), {'hace_factura__exact': '1'})
        self.assertContains(resp, con.nombre)
        self.assertNotContains(resp, sin.nombre)
