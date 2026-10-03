"""Planes de dLocal Go: registrar los que ya existen (creados desde su panel),
dejarlos con descripción corta y direcciones de retorno/aviso, y los textos.
Ningún test llama a la API real."""
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import dlocal_go, planes_dlocal
from .models import Pais, PlanDLocal
from .tests_dlocal import CLAVES, BaseDLocalTests


def _remoto(id, pais='PE', moneda='PEN', monto=49.0, active=True, nombre='Plan', **extra):
    return dict(
        id=id, name=nombre, country=pais, currency=moneda, amount=monto, active=active,
        frequency_type='MONTHLY', plan_token=f'tok{id}',
        subscribe_url=f'https://checkout.dlocalgo.com/validate/subscription/tok{id}', **extra,
    )


@override_settings(**CLAVES)
class ImportarPlanesTests(BaseDLocalTests):
    def setUp(self):
        super().setUp()
        PlanDLocal.objects.all().delete()
        self.admin_user = User.objects.create_superuser('admin_imp', 'a@example.com', 'ClaveAdminSegura2026')

    def _importar(self, remotos, aplicar=True):
        with mock.patch('directorio.dlocal_go.listar_planes', return_value=remotos):
            return planes_dlocal.importar_planes(aplicar=aplicar)

    def test_registra_cada_plan_por_pais_y_por_monto(self):
        self._importar([_remoto(25229, monto=49.0), _remoto(25230, monto=85.0)])
        basico = PlanDLocal.objects.get(pais=self.pais, plan='basico')
        premium = PlanDLocal.objects.get(pais=self.pais, plan='premium')
        self.assertEqual((basico.dlocal_plan_id, premium.dlocal_plan_id), (25229, 25230))
        self.assertEqual(basico.subscribe_url, 'https://checkout.dlocalgo.com/validate/subscription/tok25229')

    def test_sin_apply_solo_informa_y_no_guarda(self):
        informe = self._importar([_remoto(1, monto=49.0)], aplicar=False)
        self.assertEqual(PlanDLocal.objects.count(), 0)
        self.assertEqual(informe[0][0], 'registraría')

    def test_es_seguro_de_repetir(self):
        self._importar([_remoto(1, monto=49.0)])
        informe = self._importar([_remoto(1, monto=49.0)])
        self.assertEqual(informe[0][0], 'igual')
        self.assertEqual(PlanDLocal.objects.count(), 1)

    def test_un_plan_con_otro_monto_no_se_registra_a_ciegas(self):
        informe = self._importar([_remoto(1, monto=60.0)])
        self.assertEqual(PlanDLocal.objects.count(), 0)
        self.assertEqual(informe[0][0], 'omitido')
        self.assertIn('no coincide', informe[0][1])

    def test_se_omiten_inactivos_otro_pais_y_otra_moneda(self):
        informe = self._importar([
            _remoto(1, monto=49.0, active=False),
            _remoto(2, pais='BR', moneda='BRL', monto=49.0),
            _remoto(3, moneda='USD', monto=49.0),
        ])
        self.assertEqual(PlanDLocal.objects.count(), 0)
        self.assertEqual([r for r, _ in informe], ['omitido'] * 3)

    def test_si_cambio_el_link_se_actualiza(self):
        self._importar([_remoto(1, monto=49.0)])
        informe = self._importar([_remoto(9, monto=49.0)])
        self.assertEqual(informe[0][0], 'actualizado')
        self.assertEqual(PlanDLocal.objects.get(pais=self.pais, plan='basico').dlocal_plan_id, 9)

    def test_el_comando_importar_muestra_el_informe(self):
        salida = io.StringIO()
        with mock.patch('directorio.dlocal_go.listar_planes', return_value=[_remoto(1, monto=49.0)]):
            call_command('importar_planes_dlocal', '--apply', stdout=salida)
        self.assertIn('REGISTRADO', salida.getvalue())
        self.assertEqual(PlanDLocal.objects.count(), 1)

    def test_el_boton_del_admin_registra_los_planes(self):
        self.client.force_login(self.admin_user)
        with mock.patch('directorio.dlocal_go.listar_planes', return_value=[_remoto(1, monto=49.0)]):
            resp = self.client.post(reverse('admin:directorio_plandlocal_importar'))
        self.assertRedirects(resp, reverse('admin:directorio_plandlocal_changelist'))
        self.assertEqual(PlanDLocal.objects.count(), 1)

    def test_el_boton_del_admin_no_responde_a_un_GET(self):
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('admin:directorio_plandlocal_importar')).status_code, 405)

    def test_la_lista_de_planes_muestra_el_boton(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('admin:directorio_plandlocal_changelist'))
        self.assertContains(resp, 'Importar planes desde dLocal Go')

    def test_si_dlocal_falla_el_boton_avisa_sin_romper(self):
        self.client.force_login(self.admin_user)
        with mock.patch('directorio.dlocal_go.listar_planes', side_effect=dlocal_go.DLocalError('caído')):
            resp = self.client.post(reverse('admin:directorio_plandlocal_importar'), follow=True)
        self.assertContains(resp, 'No se pudo hablar con dLocal Go')


@override_settings(**CLAVES)
class ConfigurarPlanesTests(BaseDLocalTests):
    def _configurar(self, remotos, aplicar):
        with mock.patch('directorio.dlocal_go.listar_planes', return_value=remotos), \
                mock.patch('directorio.dlocal_go.actualizar_plan') as patch:
            informe = planes_dlocal.configurar_planes(aplicar=aplicar)
        return informe, patch

    def _plan_sin_urls(self):
        return _remoto(11, monto=49.0, description='Tu perfil publicado en el buscador de Atención Psi Perú, optimizado')

    def test_sin_apply_muestra_que_cambiaria_y_no_escribe_en_dlocal(self):
        informe, patch = self._configurar([self._plan_sin_urls()], aplicar=False)
        patch.assert_not_called()
        self.assertEqual(informe[0][0], 'actualizaría')
        self.assertIn('notification_url', informe[0][1])

    def test_con_apply_manda_la_descripcion_corta_y_las_cuatro_direcciones(self):
        _, patch = self._configurar([self._plan_sin_urls()], aplicar=True)
        self.assertEqual(patch.call_args[0][0], 11)
        campos = patch.call_args.kwargs
        self.assertEqual(set(campos), {'description', 'success_url', 'error_url', 'back_url', 'notification_url'})
        self.assertTrue(campos['notification_url'].endswith(reverse('portal_dlocal_webhook')))
        self.assertLessEqual(len(campos['description']), 100)

    def test_no_toca_monto_nombre_ni_moneda(self):
        _, patch = self._configurar([self._plan_sin_urls()], aplicar=True)
        for prohibido in ('amount', 'name', 'currency', 'country', 'frequency_type'):
            self.assertNotIn(prohibido, patch.call_args.kwargs)

    def test_un_plan_ya_bien_configurado_no_se_toca(self):
        ok = _remoto(
            11, monto=49.0, description=planes_dlocal.descripcion_plan(self.pais, 'basico'), **planes_dlocal.urls_del_plan(),
        )
        informe, patch = self._configurar([ok], aplicar=True)
        patch.assert_not_called()
        self.assertEqual(informe[0][0], 'igual')

    def test_un_plan_que_no_corresponde_a_ningun_nivel_se_omite_y_no_se_toca(self):
        informe, patch = self._configurar([_remoto(999, monto=60.0)], aplicar=True)   # monto que no es de ningún plan
        patch.assert_not_called()
        self.assertEqual(informe[0][0], 'omitido')

    def test_funciona_aunque_los_planes_todavia_no_esten_registrados(self):
        PlanDLocal.objects.all().delete()
        informe, patch = self._configurar([self._plan_sin_urls()], aplicar=True)
        patch.assert_called_once()
        self.assertEqual(informe[0][0], 'actualizado')


class DescripcionesDePlanesTests(TestCase):
    def test_todas_entran_enteras_en_el_limite_de_dlocal(self):
        for pais in Pais.objects.filter(es_externo=False):
            for plan in ('basico', 'premium'):
                texto = planes_dlocal.descripcion_plan(pais, plan)
                self.assertLessEqual(
                    len(texto), planes_dlocal.LARGO_MAXIMO_DESCRIPCION, f'{pais.nombre} {plan}: {texto}',
                )

    def test_el_nombre_coincide_con_el_de_los_planes_ya_creados_en_el_panel(self):
        peru = Pais.objects.get(slug='peru')
        self.assertEqual(planes_dlocal.nombre_plan(peru, 'basico'), 'Atención Psi Perú - Plan Básico')
        self.assertEqual(planes_dlocal.nombre_plan(peru, 'premium'), 'Atención Psi Perú - Plan Premium')
