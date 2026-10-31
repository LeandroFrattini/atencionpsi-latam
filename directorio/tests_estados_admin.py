"""Lista de profesionales del admin: por país, con su estado (publicado, solo cuenta, etc.)."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import estados
from .models import Orientacion, Pais, Psicologo


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True, orden=1)
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True, orden=2)
        self.admin_user = User.objects.create_superuser('admin_est', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)
        self.orientacion = Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0]
        self.lista = reverse('admin:directorio_psicologo_changelist')
        self.n = 0

    def psi(self, nombre='Psi', pais=None, completo=True, activo=True, **extra):
        self.n += 1
        email = f'psi{self.n}@example.com'
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123', is_active=activo)
        datos = dict(usuario=usuario, pais=pais or self.peru, nombre=nombre, matricula='1' if completo else '', whatsapp='51999999999')
        if completo:
            datos.update(bio='bio', foto='psicologos/test.jpg')
        datos.update(extra)
        p = Psicologo.objects.create(**datos)
        if completo:
            p.orientaciones.add(self.orientacion)
        return p

    def estado(self, p):
        return estados.con_estado(Psicologo.objects.filter(pk=p.pk)).get().estado_codigo


class EstadoCalculadoTests(_Base):
    def test_publicado(self):
        p = self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        self.assertEqual(self.estado(p), 'publicado')

    def test_listo_pero_sin_tocar_publicar(self):
        p = self.psi(suscripcion_activa=True, publicado_por_usuario=False)
        self.assertEqual(self.estado(p), 'listo')

    def test_con_acceso_pero_perfil_incompleto(self):
        p = self.psi(completo=False, suscripcion_activa=True)
        self.assertEqual(self.estado(p), 'incompleto')

    def test_perfil_completo_pero_sin_plan_es_el_contacto_caliente(self):
        p = self.psi(completo=True)
        self.assertEqual(self.estado(p), 'por_pagar')

    def test_solo_cuenta(self):
        self.assertEqual(self.estado(self.psi(completo=False)), 'sin_pago')

    def test_email_sin_confirmar(self):
        self.assertEqual(self.estado(self.psi(completo=False, activo=False)), 'sin_confirmar')

    def test_gratis_vigente_cuenta_como_acceso_y_vencido_aparte(self):
        vigente = self.psi(gratis_hasta=timezone.now() + datetime.timedelta(days=10), publicado_por_usuario=True)
        vencido = self.psi(gratis_hasta=timezone.now() - datetime.timedelta(days=1), publicado_por_usuario=True)
        self.assertEqual(self.estado(vigente), 'publicado')
        self.assertEqual(self.estado(vencido), 'vencido')

    def test_exento_de_pago_cuenta_como_acceso(self):
        self.assertEqual(self.estado(self.psi(exento_de_pago=True, publicado_por_usuario=True)), 'publicado')

    def test_sin_orientacion_el_perfil_no_esta_completo(self):
        p = self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        p.orientaciones.clear()
        self.assertEqual(self.estado(p), 'incompleto')

    def test_sin_foto_o_sin_bio_no_esta_completo(self):
        sin_foto = self.psi(suscripcion_activa=True)
        Psicologo.objects.filter(pk=sin_foto.pk).update(foto=None)
        sin_bio = self.psi(suscripcion_activa=True)
        Psicologo.objects.filter(pk=sin_bio.pk).update(bio='')
        self.assertEqual(self.estado(sin_foto), 'incompleto')
        self.assertEqual(self.estado(sin_bio), 'incompleto')

    def test_coincide_con_lo_que_decide_el_sitio(self):
        """Para todas las combinaciones, 'publicado' en el admin == Psicologo.publicado."""
        casos = []
        for completo in (True, False):
            for acceso in ('nada', 'paga', 'exento', 'gratis', 'vencido'):
                for publico in (True, False):
                    extra = {'publicado_por_usuario': publico}
                    if acceso == 'paga':
                        extra['suscripcion_activa'] = True
                    elif acceso == 'exento':
                        extra['exento_de_pago'] = True
                    elif acceso == 'gratis':
                        extra['gratis_hasta'] = timezone.now() + datetime.timedelta(days=5)
                    elif acceso == 'vencido':
                        extra['gratis_hasta'] = timezone.now() - datetime.timedelta(days=5)
                    casos.append(self.psi(completo=completo, **extra))
        for p in casos:
            p.refresh_from_db()
            self.assertEqual(self.estado(p) == 'publicado', p.publicado, f'{p.nombre} {p.pk}')


class ListaDelAdminTests(_Base):
    def filas(self, params=None):
        resp = self.client.get(self.lista, params or {})
        self.assertEqual(resp.status_code, 200)
        return resp, [p.nombre for p in resp.context['cl'].result_list]

    def test_ordena_por_pais_y_dentro_de_cada_pais_por_estado(self):
        self.psi('Chile Publicado', pais=self.chile, suscripcion_activa=True, publicado_por_usuario=True)
        self.psi('Peru Solo Cuenta', completo=False)
        self.psi('Peru Publicado', suscripcion_activa=True, publicado_por_usuario=True)
        self.psi('Peru Sin Confirmar', completo=False, activo=False)
        self.psi('Peru Por Pagar')
        _, nombres = self.filas()
        self.assertEqual(nombres, ['Peru Publicado', 'Peru Por Pagar', 'Peru Solo Cuenta', 'Peru Sin Confirmar', 'Chile Publicado'])

    def test_filtra_por_pais_y_por_estado(self):
        self.psi('A Peru Publicado', suscripcion_activa=True, publicado_por_usuario=True)
        self.psi('B Chile Publicado', pais=self.chile, suscripcion_activa=True, publicado_por_usuario=True)
        self.psi('C Peru Solo Cuenta', completo=False)
        self.assertEqual(self.filas({'estado': 'publicado'})[1], ['A Peru Publicado', 'B Chile Publicado'])
        self.assertEqual(self.filas({'pais__id__exact': self.peru.pk})[1], ['A Peru Publicado', 'C Peru Solo Cuenta'])
        self.assertEqual(self.filas({'pais__id__exact': self.peru.pk, 'estado': 'sin_pago'})[1], ['C Peru Solo Cuenta'])

    def test_un_estado_inventado_no_rompe_la_lista(self):
        self.psi('Ana')
        self.assertEqual(len(self.filas({'estado': 'cualquiera'})[1]), 1)

    def test_muestra_estado_acceso_email_y_whatsapp_con_link(self):
        self.psi('Ana Paga', suscripcion_activa=True, publicado_por_usuario=True, plan='premium')
        self.psi('Beto Gratis', gratis_hasta=timezone.now() + datetime.timedelta(days=10))
        resp, _ = self.filas()
        self.assertContains(resp, 'Publicado')
        self.assertContains(resp, 'Paga (Premium)')
        self.assertContains(resp, 'Gratis hasta')
        self.assertContains(resp, 'https://wa.me/51999999999')
        self.assertContains(resp, '@example.com')

    def test_se_puede_buscar_por_email(self):
        p = self.psi('Ana')
        self.psi('Beto')
        self.assertEqual(self.filas({'q': p.usuario.email})[1], ['Ana'])

    def test_muestra_las_visitas_de_los_ultimos_30_dias(self):
        from .models import VisitaPerfil
        p = self.psi('Ana', suscripcion_activa=True, publicado_por_usuario=True)
        VisitaPerfil.objects.create(fecha=timezone.localdate(), psicologo=p, cantidad=7)
        VisitaPerfil.objects.create(fecha=timezone.localdate() - datetime.timedelta(days=60), psicologo=p, cantidad=100)
        fila = self.client.get(self.lista).context['cl'].result_list[0]
        self.assertEqual(fila.visitas_30, 7)

    def test_las_acciones_de_siempre_siguen_estando(self):
        self.psi('Ana')
        resp = self.client.get(self.lista)
        for texto in ('Dar acceso gratis hasta una fecha', 'Quitar el período gratis', 'Generar post de feed de Instagram'):
            self.assertContains(resp, texto)


class CuadroDelInicioTests(_Base):
    def test_cuenta_por_pais_y_por_estado_con_links(self):
        self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        self.psi(completo=False)
        self.psi(completo=False)
        self.psi(pais=self.chile, suscripcion_activa=True, publicado_por_usuario=True)
        resp = self.client.get(reverse('admin:index'))
        self.assertContains(resp, 'Profesionales por país y estado')
        filas, total = estados.resumen_por_pais()
        por_pais = {f['pais'].nombre: f for f in filas}
        self.assertEqual(por_pais['Perú']['estados']['publicado'], 1)
        self.assertEqual(por_pais['Perú']['estados']['sin_pago'], 2)
        self.assertEqual(por_pais['Perú']['total'], 3)
        self.assertEqual(por_pais['Chile']['estados']['publicado'], 1)
        self.assertEqual((total['total'], total['estados']['publicado']), (4, 2))
        self.assertContains(resp, f'?pais__id__exact={self.peru.pk}&amp;estado=sin_pago')

    def test_los_links_del_cuadro_llevan_a_la_lista_filtrada(self):
        self.psi('Solo Cuenta', completo=False)
        self.psi('Publicado', suscripcion_activa=True, publicado_por_usuario=True)
        resp = self.client.get(self.lista, {'pais__id__exact': self.peru.pk, 'estado': 'sin_pago'})
        self.assertEqual([p.nombre for p in resp.context['cl'].result_list], ['Solo Cuenta'])

    def test_no_aparecen_los_paises_sin_profesionales(self):
        self.psi()
        filas, _ = estados.resumen_por_pais()
        self.assertEqual([f['pais'].nombre for f in filas], ['Perú'])

    def test_sin_profesionales_no_muestra_el_cuadro(self):
        self.assertNotContains(self.client.get(reverse('admin:index')), 'Profesionales por país y estado')


class WhatsappSinCodigoTests(_Base):
    def test_avisa_cuando_el_whatsapp_no_trae_el_codigo_del_pais(self):
        Pais.objects.filter(pk=self.peru.pk).update(codigo_telefono='51')
        self.psi('Con Codigo', whatsapp='+51 987 654 321')
        self.psi('Sin Codigo', whatsapp='987654321')
        resp = self.client.get(self.lista)
        self.assertContains(resp, 'Le falta el código de país (+51)')
        self.assertEqual(resp.content.decode().count('Le falta el código de país'), 1)   # solo a uno

    def test_sin_codigo_cargado_para_el_pais_no_avisa(self):
        Pais.objects.filter(pk=self.peru.pk).update(codigo_telefono='')
        self.psi('Ana', whatsapp='987654321')
        self.assertNotContains(self.client.get(self.lista), 'Le falta el código de país')

    def test_el_cuadro_del_inicio_tiene_estados_en_filas_y_paises_en_columnas(self):
        self.psi(suscripcion_activa=True, publicado_por_usuario=True)
        self.psi(pais=self.chile, completo=False)
        resp = self.client.get(reverse('admin:index'))
        self.assertContains(resp, 'Perú')
        self.assertContains(resp, 'Chile')
        self.assertContains(resp, f'?pais__id__exact={self.chile.pk}&amp;estado=sin_pago')
        self.assertContains(resp, f'?pais__id__exact={self.peru.pk}&amp;estado=publicado')
