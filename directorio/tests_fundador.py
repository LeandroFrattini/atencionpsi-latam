"""Códigos de fundador: 3 meses gratis para los primeros profesionales."""
import datetime
from io import StringIO

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CodigoFundador, Orientacion, Pais, Psicologo


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True)

    def _datos(self, **extra):
        datos = dict(
            nombre='Nueva Psicóloga', email='nueva@example.com', whatsapp='51999999999',
            password='ClaveSegura123', acepto_terminos='on',
        )
        datos.update(extra)
        return datos

    def _registrar(self, codigo_texto='', pais='peru', **extra):
        return self.client.post(reverse('portal_registro', args=[pais]), self._datos(codigo_fundador=codigo_texto, **extra))


class CodigoFundadorModeloTests(_Base):
    def test_se_genera_solo_con_formato_y_sin_caracteres_ambiguos(self):
        c = CodigoFundador.objects.create()
        self.assertRegex(c.codigo, r'^FUNDADOR-[A-HJ-NP-Z2-9]{6}$')

    def test_no_se_repiten(self):
        codigos = {CodigoFundador.objects.create().codigo for _ in range(30)}
        self.assertEqual(len(codigos), 30)

    def test_un_codigo_escrito_a_mano_se_normaliza(self):
        c = CodigoFundador.objects.create(codigo='  amigos-lima ')
        self.assertEqual(c.codigo, 'AMIGOS-LIMA')

    def test_motivos_de_rechazo(self):
        ok = CodigoFundador.objects.create(pais=self.peru)
        self.assertIsNone(ok.motivo_de_rechazo(self.peru))
        self.assertIn('Perú', ok.motivo_de_rechazo(self.chile))

        apagado = CodigoFundador.objects.create(activo=False)
        self.assertIn('no está activo', apagado.motivo_de_rechazo(self.peru))

        vencido = CodigoFundador.objects.create(canjeable_hasta=timezone.localdate() - datetime.timedelta(days=1))
        self.assertIn('venció', vencido.motivo_de_rechazo(self.peru))

        self.assertIsNone(CodigoFundador.objects.create().motivo_de_rechazo(self.chile))   # sin país: vale en todos


class RegistroConCodigoTests(_Base):
    def test_registro_con_codigo_da_tres_meses_gratis(self):
        c = CodigoFundador.objects.create(pais=self.peru, meses_gratis=3)
        antes = timezone.now()
        resp = self._registrar(c.codigo)
        self.assertEqual(resp.status_code, 200)
        psi = Psicologo.objects.get(usuario__username='nueva@example.com')
        self.assertEqual(psi.codigo_fundador, c)
        esperado = antes + relativedelta(months=3)
        self.assertLess(abs((psi.gratis_hasta - esperado).total_seconds()), 60)
        self.assertTrue(psi.en_periodo_fundador)
        self.assertTrue(psi.tiene_acceso)
        self.assertFalse(psi.suscripcion_activa)
        self.assertIsNotNone(psi.fecha_pago_confirmado)

    def test_el_codigo_se_acepta_en_minusculas_y_con_espacios(self):
        c = CodigoFundador.objects.create()
        self._registrar('  ' + c.codigo.lower() + ' ')
        self.assertTrue(Psicologo.objects.get(usuario__username='nueva@example.com').en_periodo_fundador)

    def test_un_codigo_de_un_solo_uso_no_se_puede_usar_dos_veces(self):
        c = CodigoFundador.objects.create()
        self._registrar(c.codigo)
        resp = self._registrar(c.codigo, email='otra@example.com', nombre='Otra Persona')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ya fue utilizado')
        self.assertFalse(User.objects.filter(username='otra@example.com').exists())

    def test_un_codigo_con_varios_usos_alcanza_hasta_el_maximo(self):
        c = CodigoFundador.objects.create(usos_maximos=2)
        self._registrar(c.codigo, email='a@example.com')
        self._registrar(c.codigo, email='b@example.com')
        resp = self._registrar(c.codigo, email='c@example.com')
        self.assertContains(resp, 'ya fue utilizado')
        self.assertEqual(c.usos, 2)

    def test_codigo_inexistente_muestra_error_y_no_crea_la_cuenta(self):
        resp = self._registrar('FUNDADOR-NOEXISTE')
        self.assertContains(resp, 'No encontramos ese código')
        self.assertFalse(User.objects.filter(username='nueva@example.com').exists())

    def test_codigo_de_otro_pais_se_rechaza(self):
        c = CodigoFundador.objects.create(pais=self.chile)
        resp = self._registrar(c.codigo, pais='peru')
        self.assertContains(resp, 'Ese código es para Chile')
        self.assertFalse(User.objects.filter(username='nueva@example.com').exists())

    def test_sin_codigo_el_registro_sigue_igual_que_antes(self):
        self._registrar('')
        psi = Psicologo.objects.get(usuario__username='nueva@example.com')
        self.assertIsNone(psi.codigo_fundador)
        self.assertIsNone(psi.gratis_hasta)
        self.assertFalse(psi.tiene_acceso)

    def test_el_link_con_el_codigo_lo_trae_precargado(self):
        resp = self.client.get(reverse('portal_registro', args=['peru']) + '?codigo=fundador-abc123')
        self.assertContains(resp, 'value="FUNDADOR-ABC123"')


class PeriodoFundadorTests(_Base):
    def _psi(self, gratis_hasta):
        usuario = User.objects.create_user('f@example.com', password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre='Fundadora Test', matricula='1', whatsapp='51999999999',
            bio='bio', foto='psicologos/test.jpg', publicado_por_usuario=True, gratis_hasta=gratis_hasta,
        )
        psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Psicoanálisis')[0])
        return psi

    def test_dentro_del_periodo_esta_publicada(self):
        psi = self._psi(timezone.now() + datetime.timedelta(days=30))
        self.assertTrue(psi.publicado)
        self.assertContains(self.client.get(reverse('buscador_pais', args=['peru'])), 'Fundadora Test')

    def test_al_vencer_se_despublica_sola(self):
        psi = self._psi(timezone.now() - datetime.timedelta(seconds=1))
        self.assertFalse(psi.en_periodo_fundador)
        self.assertFalse(psi.publicado)
        self.assertNotContains(self.client.get(reverse('buscador_pais', args=['peru'])), 'Fundadora Test')

    def test_si_activa_la_suscripcion_sigue_publicada_despues_de_vencer(self):
        psi = self._psi(timezone.now() - datetime.timedelta(days=1))
        psi.suscripcion_activa = True
        psi.save()
        self.assertTrue(psi.publicado)

    def test_el_panel_muestra_hasta_cuando_es_gratis(self):
        psi = self._psi(timezone.now() + datetime.timedelta(days=30))
        self.client.force_login(psi.usuario)
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertContains(resp, 'gratis hasta el')
        self.assertContains(resp, f'{psi.gratis_hasta:%d/%m/%Y}')
        self.assertNotContains(resp, 'Suscripción pendiente')

    def test_vencido_el_panel_pide_activar_la_suscripcion(self):
        psi = self._psi(timezone.now() - datetime.timedelta(days=1))
        self.client.force_login(psi.usuario)
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertContains(resp, 'Suscripción pendiente')
        self.assertContains(resp, 'Activar suscripción')

    def test_durante_el_periodo_puede_entrar_al_checkout_para_suscribirse(self):
        psi = self._psi(timezone.now() + datetime.timedelta(days=30))
        self.client.force_login(psi.usuario)
        self.assertEqual(self.client.get(reverse('portal_checkout')).status_code, 200)


class RecordatoriosFundadorTests(_Base):
    def _psi(self, email, dias, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre='Psi ' + email, matricula='1', whatsapp='1',
            gratis_hasta=timezone.now() + datetime.timedelta(days=dias), **extra,
        )
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - datetime.timedelta(days=3))
        return psi

    def test_avisa_una_semana_antes_de_vencer_y_una_sola_vez(self):
        cerca = self._psi('cerca@example.com', 5)
        lejos = self._psi('lejos@example.com', 60)
        call_command('enviar_recordatorios', '--apply', stdout=StringIO())
        destinos = [m.to[0] for m in mail.outbox if 'período gratis' in m.subject]
        self.assertEqual(destinos, ['cerca@example.com'])
        cerca.refresh_from_db()
        self.assertTrue(cerca.recordatorio_vencimiento_enviado)
        mail.outbox.clear()
        call_command('enviar_recordatorios', '--apply', stdout=StringIO())
        self.assertFalse([m for m in mail.outbox if 'período gratis' in m.subject])
        lejos.refresh_from_db()
        self.assertFalse(lejos.recordatorio_vencimiento_enviado)

    def test_no_le_pide_pagar_a_quien_todavia_esta_en_su_periodo_gratis(self):
        self._psi('gratis@example.com', 60)
        call_command('enviar_recordatorios', '--apply', stdout=StringIO())
        self.assertFalse([m for m in mail.outbox if 'Terminá de activar' in m.subject])

    def test_dry_run_no_manda_nada(self):
        self._psi('cerca@example.com', 3)
        call_command('enviar_recordatorios', stdout=StringIO())
        self.assertEqual(mail.outbox, [])


class AdminCodigosFundadorTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser('admin_cod', 'a@example.com', 'ClaveAdminSegura2026')
        self.client.force_login(self.admin_user)

    def test_la_lista_tiene_el_boton_de_generar(self):
        resp = self.client.get(reverse('admin:directorio_codigofundador_changelist'))
        self.assertContains(resp, 'Generar códigos en lote')

    def test_genera_en_lote_y_muestra_los_links(self):
        resp = self.client.post(reverse('admin:directorio_codigofundador_generar'), {
            'pais': self.peru.pk, 'cantidad': 5, 'meses_gratis': 3, 'nota': 'Perú tanda 1',
        })
        self.assertEqual(resp.status_code, 200)
        codigos = CodigoFundador.objects.all()
        self.assertEqual(codigos.count(), 5)
        self.assertTrue(all(c.meses_gratis == 3 and c.usos_maximos == 1 and c.pais == self.peru for c in codigos))
        for c in codigos:
            self.assertContains(resp, f'/portal/peru/registro/?codigo={c.codigo}')

    def test_no_crea_nada_con_datos_invalidos(self):
        resp = self.client.post(reverse('admin:directorio_codigofundador_generar'), {'cantidad': 0, 'meses_gratis': 3})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CodigoFundador.objects.count(), 0)
