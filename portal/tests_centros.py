"""Centros especializados (Perú): registro propio con RUC, mismo precio y planes, y figuran en el buscador junto a los
profesionales."""
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from directorio import estados, ruc
from directorio.models import Orientacion, Pais, Psicologo

RUC_VALIDO = '20100070970'
OTRO_RUC_VALIDO = '20131312955'
RUC_PERSONA = '10123456781'


def _pais(**extra):
    Pais.objects.all().delete()
    datos = dict(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
                 precio_basico=49, precio_premium=85, activo=True, codigo_telefono='51', acepta_centros=True)
    datos.update(extra)
    return Pais.objects.create(**datos)


class ValidacionDelRucTests(TestCase):
    def test_acepta_rucs_validos_y_los_deja_solo_con_digitos(self):
        for texto in (RUC_VALIDO, OTRO_RUC_VALIDO, RUC_PERSONA, ' 20-100 070970 '):
            self.assertEqual(ruc.validar_ruc_peru(texto), ''.join(c for c in texto if c.isdigit()), texto)

    def test_rechaza_largo_prefijo_y_digito_verificador_incorrectos(self):
        for malo in ('', '2010007097', '201000709700', 'abc', '30100070970', '20100070971', '20131312950'):
            with self.assertRaises(ValueError, msg=malo):
                ruc.validar_ruc_peru(malo)

    def test_los_mensajes_explican_que_falla(self):
        with self.assertRaisesMessage(ValueError, '11 dígitos'):
            ruc.validar_ruc_peru('123')
        with self.assertRaisesMessage(ValueError, 'último dígito'):
            ruc.validar_ruc_peru('20100070971')

    def test_en_otros_paises_pide_solo_un_numero_razonable(self):
        chile = Pais(codigo_iso='CL')
        self.assertEqual(ruc.validar_documento(chile, '76.543.210-K'), '76543210')
        with self.assertRaises(ValueError):
            ruc.validar_documento(chile, '12')


class RegistroDeCentrosTests(TestCase):
    def setUp(self):
        self.peru = _pais()

    def datos(self, **extra):
        datos = dict(nombre='Centro Mente Sana', ruc=RUC_VALIDO, email='centro@example.com', whatsapp='51988888888',
                     password='ClaveSegura123', acepto_terminos='on')
        datos.update(extra)
        return datos

    def test_la_pagina_de_registro_existe_y_explica_los_planes(self):
        resp = self.client.get(reverse('portal_registro_centro', args=['peru']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sumá tu centro')
        self.assertContains(resp, 'RUC del centro')
        self.assertContains(resp, 'S/ 49')      # los mismos precios que los profesionales
        self.assertContains(resp, 'S/ 85')

    def test_los_paises_sin_centros_no_tienen_esa_pagina(self):
        Pais.objects.filter(pk=self.peru.pk).update(acepta_centros=False)
        self.assertEqual(self.client.get(reverse('portal_registro_centro', args=['peru'])).status_code, 404)
        self.assertEqual(self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos()).status_code, 404)

    def test_crea_la_cuenta_como_centro_con_el_plan_primero(self):
        resp = self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'centro@example.com')
        usuario = User.objects.get(username='centro@example.com')
        self.assertFalse(usuario.is_active)
        centro = usuario.psicologo
        self.assertEqual((centro.tipo, centro.ruc, centro.nombre, centro.pais), ('centro', RUC_VALIDO, 'Centro Mente Sana', self.peru))
        self.assertFalse(centro.ruc_verificado)
        self.assertTrue(centro.plan_primero)       # primero elige plan y paga, igual que los profesionales
        self.assertEqual(centro.matricula, '')

    def test_manda_el_mail_de_confirmacion_y_avisa_al_equipo_que_es_un_centro(self):
        self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos())
        self.assertEqual(len(mail.outbox), 2)
        aviso = next(m for m in mail.outbox if 'centro@example.com' not in m.to)
        self.assertIn('centro', aviso.subject)
        self.assertIn('CENTRO ESPECIALIZADO', aviso.body)
        self.assertIn(RUC_VALIDO, aviso.body)

    def test_rechaza_un_ruc_invalido(self):
        for malo in ('20100070971', '123', 'hola'):
            resp = self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos(ruc=malo))
            self.assertEqual(resp.status_code, 200, malo)
            self.assertFalse(User.objects.filter(username='centro@example.com').exists(), malo)
        self.assertContains(resp, 'portal-error')

    def test_un_ruc_no_se_puede_registrar_dos_veces(self):
        self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos())
        resp = self.client.post(reverse('portal_registro_centro', args=['peru']),
                                self.datos(email='otro@example.com', nombre='Otro nombre'))
        self.assertContains(resp, 'Ya hay un centro registrado con ese RUC')
        self.assertFalse(User.objects.filter(username='otro@example.com').exists())

    def test_el_registro_de_profesionales_sigue_igual_y_ofrece_el_de_centros(self):
        resp = self.client.get(reverse('portal_registro', args=['peru']))
        self.assertContains(resp, reverse('portal_registro_centro', args=['peru']))
        datos = dict(nombre='Ana Pérez', email='ana@example.com', whatsapp='51988888888', password='ClaveSegura123', acepto_terminos='on')
        self.client.post(reverse('portal_registro', args=['peru']), datos)
        ana = Psicologo.objects.get(usuario__username='ana@example.com')
        self.assertEqual((ana.tipo, ana.ruc), ('profesional', ''))

    def test_sin_centros_habilitados_el_registro_de_profesionales_no_ofrece_el_link(self):
        Pais.objects.filter(pk=self.peru.pk).update(acepta_centros=False)
        self.assertNotContains(self.client.get(reverse('portal_registro', args=['peru'])), 'registro-centros')

    def test_confirma_el_email_y_va_a_elegir_el_plan(self):
        self.client.post(reverse('portal_registro_centro', args=['peru']), self.datos())
        import re
        link = re.search(r'/portal/verificar/\S+/\S+/', next(m for m in mail.outbox if 'centro@example.com' in m.to).body).group(0)
        self.assertRedirects(self.client.get(link), reverse('portal_checkout'))


class PerfilDelCentroTests(TestCase):
    def setUp(self):
        self.peru = _pais()
        usuario = User.objects.create_user('centro@example.com', email='centro@example.com', password='ClaveSegura123')
        self.centro = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, tipo='centro', nombre='Centro Mente Sana', ruc=RUC_VALIDO, whatsapp='51988888888',
            exento_de_pago=True,
        )
        self.gestalt = Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0]

    def completar(self):
        Psicologo.objects.filter(pk=self.centro.pk).update(bio='Somos un centro', foto='psicologos/x.jpg', publicado_por_usuario=True)
        self.centro.orientaciones.add(self.gestalt)
        self.centro = Psicologo.objects.get(pk=self.centro.pk)

    def test_el_documento_es_el_ruc_y_no_pide_matricula(self):
        self.assertEqual((self.centro.documento, self.centro.etiqueta_documento), (RUC_VALIDO, 'RUC'))
        self.assertNotIn('RUC', self.centro.faltantes_perfil)
        self.assertNotIn('N° de Colegiatura (CPsP)', self.centro.faltantes_perfil)

    def test_un_centro_completo_se_publica_sin_matricula(self):
        self.assertFalse(self.centro.perfil_completo)
        self.completar()
        self.assertTrue(self.centro.perfil_completo)
        self.assertEqual(self.centro.faltantes_perfil, [])
        self.assertTrue(self.centro.publicado)

    def test_sin_ruc_no_esta_completo_y_lo_dice_con_palabras_de_centro(self):
        self.completar()
        Psicologo.objects.filter(pk=self.centro.pk).update(ruc='')
        centro = Psicologo.objects.get(pk=self.centro.pk)
        self.assertFalse(centro.perfil_completo)
        self.assertEqual(centro.faltantes_perfil, ['RUC'])
        Psicologo.objects.filter(pk=self.centro.pk).update(nombre='', bio='', foto='')
        self.assertEqual(Psicologo.objects.get(pk=self.centro.pk).faltantes_perfil,
                         ['el nombre del centro', 'RUC', 'el logo o una foto del centro', 'la presentación del centro'])

    def test_los_estados_del_admin_coinciden_con_el_sitio(self):
        for completar in (False, True):
            if completar:
                self.completar()
            fila = estados.con_estado(Psicologo.objects.filter(pk=self.centro.pk)).get()
            esperado = 'publicado' if self.centro.publicado else ('listo' if self.centro.puede_publicar else 'incompleto')
            self.assertEqual(fila.estado_codigo, esperado)

    def test_un_profesional_sin_matricula_sigue_incompleto(self):
        usuario = User.objects.create_user('p@example.com', password='ClaveSegura123')
        psi = Psicologo.objects.create(usuario=usuario, pais=self.peru, nombre='Ana', matricula='', whatsapp='51999', exento_de_pago=True)
        self.assertEqual(psi.documento, '')
        self.assertIn(self.peru.etiqueta_matricula, psi.faltantes_perfil)
        self.assertEqual(estados.con_estado(Psicologo.objects.filter(pk=psi.pk)).get().estado_codigo, 'incompleto')

    def test_el_editor_muestra_lo_de_un_centro(self):
        self.client.force_login(self.centro.usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        for campo in ('ruc', 'direccion', 'nombre', 'bio', 'foto'):
            self.assertIn(campo, form.fields, campo)
        for campo in ('matricula', 'docencia', 'sesiones_atendidas'):
            self.assertNotIn(campo, form.fields, campo)
        self.assertEqual(form.fields['nombre'].label, 'Nombre del centro')
        self.assertContains(resp, 'Presentación del centro')
        self.assertContains(resp, 'data-centro="1"')
        self.assertNotContains(resp, 'Formación</h2>')

    def test_el_editor_de_un_profesional_no_cambia(self):
        usuario = User.objects.create_user('p@example.com', password='ClaveSegura123')
        Psicologo.objects.create(usuario=usuario, pais=self.peru, nombre='Ana', matricula='1', whatsapp='51999', exento_de_pago=True)
        self.client.force_login(usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        form = resp.context['form']
        for campo in ('matricula', 'docencia', 'sesiones_atendidas'):
            self.assertIn(campo, form.fields, campo)
        for campo in ('ruc', 'direccion'):
            self.assertNotIn(campo, form.fields, campo)
        self.assertContains(resp, 'data-centro="0"')
        self.assertContains(resp, 'Formación</h2>')

    def datos_editor(self, **extra):
        datos = {'nombre': 'Centro Mente Sana', 'ruc': RUC_VALIDO, 'whatsapp': '51988888888', 'modalidad': 'presencial',
                 'direccion': 'Av. Larco 123, Miraflores', 'bio': 'Somos un centro', 'ciudad': '',
                 'formaciones-TOTAL_FORMS': 0, 'formaciones-INITIAL_FORMS': 0, 'formaciones-MIN_NUM_FORMS': 0,
                 'formaciones-MAX_NUM_FORMS': 1000, 'accion': 'parcial'}
        datos.update(extra)
        return datos

    def test_se_puede_guardar_el_perfil_de_un_centro_con_su_direccion(self):
        self.client.force_login(self.centro.usuario)
        resp = self.client.get(reverse('portal_editar_perfil'))
        prefijo = resp.context['formset'].prefix
        datos = {k.replace('formaciones', prefijo): v for k, v in self.datos_editor().items()}
        resp = self.client.post(reverse('portal_editar_perfil'), datos)
        self.assertIn(resp.status_code, (200, 302))
        self.centro.refresh_from_db()
        self.assertEqual(self.centro.direccion, 'Av. Larco 123, Miraflores')
        self.assertEqual(self.centro.bio, 'Somos un centro')

    def test_cambiar_el_ruc_exige_verificarlo_de_nuevo(self):
        Psicologo.objects.filter(pk=self.centro.pk).update(ruc_verificado=True)
        self.client.force_login(self.centro.usuario)
        prefijo = self.client.get(reverse('portal_editar_perfil')).context['formset'].prefix
        datos = {k.replace('formaciones', prefijo): v for k, v in self.datos_editor(ruc=OTRO_RUC_VALIDO).items()}
        self.client.post(reverse('portal_editar_perfil'), datos)
        self.centro.refresh_from_db()
        self.assertEqual(self.centro.ruc, OTRO_RUC_VALIDO)
        self.assertFalse(self.centro.ruc_verificado)

    def test_no_deja_poner_un_ruc_invalido_ni_el_de_otro_centro(self):
        otro = User.objects.create_user('otro@example.com', password='ClaveSegura123')
        Psicologo.objects.create(usuario=otro, pais=self.peru, tipo='centro', nombre='Otro centro', ruc=OTRO_RUC_VALIDO,
                                 whatsapp='51977777777', exento_de_pago=True)
        self.client.force_login(self.centro.usuario)
        prefijo = self.client.get(reverse('portal_editar_perfil')).context['formset'].prefix
        for malo in ('20100070971', OTRO_RUC_VALIDO):
            datos = {k.replace('formaciones', prefijo): v for k, v in self.datos_editor(ruc=malo).items()}
            resp = self.client.post(reverse('portal_editar_perfil'), datos)
            self.assertEqual(resp.status_code, 200, malo)
            self.assertIn('ruc', resp.context['form'].errors, malo)
        self.centro.refresh_from_db()
        self.assertEqual(self.centro.ruc, RUC_VALIDO)


class CentrosEnElBuscadorTests(TestCase):
    def setUp(self):
        self.peru = _pais()
        gestalt = Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0]
        self.centro = self._crear('centro@example.com', 'Centro Mente Sana', tipo='centro', ruc=RUC_VALIDO, direccion='Av. Larco 123')
        self.ana = self._crear('ana@example.com', 'Ana Pérez', matricula='123')
        for p in (self.centro, self.ana):
            p.orientaciones.add(gestalt)

    def _crear(self, email, nombre, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre=nombre, whatsapp='51999111222', bio='Hola', foto='psicologos/x.jpg',
            publicado_por_usuario=True, exento_de_pago=True, ciudad='Lima', **extra)
        return psi

    def buscar(self, **params):
        return self.client.get(reverse('buscador_pais', args=['peru']), params)

    def test_el_centro_figura_junto_a_los_profesionales_con_su_sello(self):
        resp = self.buscar()
        self.assertContains(resp, 'Centro Mente Sana')
        self.assertContains(resp, 'Ana Pérez')
        self.assertContains(resp, 'Centro especializado')
        self.assertEqual(resp.context['total'], 2)

    def test_filtro_por_tipo(self):
        solo_centros = self.buscar(tipo='centro')
        self.assertEqual([p.nombre for p in solo_centros.context['psicologos']], ['Centro Mente Sana'])
        solo_profesionales = self.buscar(tipo='profesional')
        self.assertEqual([p.nombre for p in solo_profesionales.context['psicologos']], ['Ana Pérez'])
        self.assertEqual(self.buscar(tipo='cualquier-cosa').context['total'], 2)

    def test_el_filtro_aparece_solo_si_hay_centros_publicados(self):
        self.assertContains(self.buscar(), 'name="tipo"')
        Psicologo.objects.filter(pk=self.centro.pk).update(publicado_por_usuario=False)
        self.assertNotContains(self.buscar(), 'name="tipo"')

    def test_el_filtro_activo_se_ve_y_se_puede_quitar(self):
        resp = self.buscar(tipo='centro')
        self.assertEqual(resp.context['pills'][0]['etiqueta'], 'Solo centros especializados')
        self.assertNotIn('tipo=', resp.context['pills'][0]['quitar'])
        self.assertEqual(resp.context['filtros_extra'], 1)

    def test_escribir_centro_en_el_buscador_encuentra_los_centros(self):
        self.assertEqual([p.nombre for p in self.buscar(q='centro').context['psicologos']], ['Centro Mente Sana'])

    def test_hay_un_acceso_visible_a_los_centros_que_se_activa_y_se_quita(self):
        resp = self.buscar()
        self.assertContains(resp, 'chip-centros')
        self.assertEqual(resp.context['centros_url'], reverse('buscador_pais', args=['peru']) + '?tipo=centro')
        activo = self.buscar(tipo='centro')
        self.assertContains(activo, 'chip-centros-activo')
        self.assertEqual(activo.context['centros_url'], reverse('buscador_pais', args=['peru']))

    def test_el_encabezado_nombra_a_los_centros_solo_si_los_hay(self):
        self.assertContains(self.buscar(), 'profesionales y centros especializados')
        Psicologo.objects.filter(pk=self.centro.pk).update(publicado_por_usuario=False)
        self.assertNotContains(self.buscar(), 'centros especializados, con matrícula o RUC')

    def test_el_perfil_de_un_centro_dice_que_se_consulta_con_el_centro(self):
        self.assertContains(self.client.get(self.centro.url_publica), 'directamente con el centro')
        self.assertContains(self.client.get(self.ana.url_publica), 'directamente con el profesional')

    def test_los_paises_sin_centros_no_muestran_el_filtro(self):
        Pais.objects.filter(pk=self.peru.pk).update(acepta_centros=False)
        self.assertNotContains(self.buscar(), 'name="tipo"')

    def test_el_perfil_publico_del_centro(self):
        resp = self.client.get(self.centro.url_publica)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Centro especializado')
        self.assertContains(resp, f'RUC: {RUC_VALIDO}')
        self.assertContains(resp, 'Av. Larco 123')
        self.assertContains(resp, 'Sobre el centro')
        self.assertContains(resp, '"@type": "MedicalClinic"')
        self.assertContains(resp, f'"taxID": "{RUC_VALIDO}"')
        self.assertNotContains(resp, 'hasCredential')
        self.assertNotContains(resp, 'RUC verificado')

    def test_el_sello_de_ruc_verificado_solo_si_lo_tildo_el_equipo(self):
        Psicologo.objects.filter(pk=self.centro.pk).update(ruc_verificado=True)
        self.assertContains(self.client.get(self.centro.url_publica), 'RUC verificado')

    def test_el_perfil_de_un_profesional_no_cambia(self):
        resp = self.client.get(self.ana.url_publica)
        self.assertContains(resp, 'Psicólogo/a')
        self.assertContains(resp, 'Sobre mí')
        self.assertContains(resp, '"@type": "Person"')
        self.assertContains(resp, 'hasCredential')
        self.assertContains(resp, 'perfil-eyebrow">Psicólogo/a')
        self.assertNotContains(resp, 'Sobre el centro')
        self.assertNotContains(resp, 'RUC:')


class AdminYMigracionTests(TestCase):
    def test_peru_viene_habilitado_por_la_migracion(self):
        self.assertTrue(Pais.objects.get(slug='peru').acepta_centros)
        self.assertFalse(Pais.objects.get(slug='chile').acepta_centros)

    def test_el_admin_muestra_tipo_ruc_y_el_permiso_por_pais(self):
        pais = _pais()
        admin = User.objects.create_superuser('admin@example.com', password='ClaveSegura123')
        self.client.force_login(admin)
        usuario = User.objects.create_user('c@example.com', password='ClaveSegura123')
        centro = Psicologo.objects.create(usuario=usuario, pais=pais, tipo='centro', nombre='Centro', ruc=RUC_VALIDO, whatsapp='5199')
        resp = self.client.get(reverse('admin:directorio_psicologo_change', args=[centro.pk]))
        self.assertEqual(resp.status_code, 200)
        for texto in ('ruc_verificado', 'id_ruc', 'id_direccion', 'id_tipo'):
            self.assertContains(resp, texto)
        self.assertEqual(self.client.get(reverse('admin:directorio_psicologo_changelist') + '?tipo=centro').status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:directorio_psicologo_changelist') + '?q=' + RUC_VALIDO).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:directorio_pais_changelist')).status_code, 200)
