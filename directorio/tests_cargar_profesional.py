"""Comando para cargar a mano a una profesional (usuario + perfil), por ejemplo una que ya pagó.
Todos los datos de acá son inventados: los reales nunca se escriben en el repositorio."""
import base64
import json
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from .models import Especialidad, Orientacion, Pais, Psicologo, Publico

EMAIL = 'ejemplo@example.com'


def _blob(**cambios):
    datos = {
        'email': 'Ejemplo@Example.com', 'nombre': 'Ana Ejemplo', 'pais': 'chile', 'matricula': '111111',
        'whatsapp': '+56911111111', 'bio': 'Soy psicóloga clínica y educacional.', 'plan': 'premium',
        'modalidad': 'online', 'orientaciones': ['cognitivo conductual (tcc)'], 'especialidades': ['Orientación vocacional'],
        'publicos': ['Adultos', 'Jóvenes', 'Orientación a padres'],
    }
    datos.update(cambios)
    datos = {k: v for k, v in datos.items() if v is not None}
    return base64.b64encode(json.dumps(datos).encode('utf-8')).decode('ascii')


def _correr(blob, *extra):
    salida = StringIO()
    call_command('cargar_profesional', '--datos', blob, *extra, stdout=salida)
    return salida.getvalue()


def _psi():
    return Psicologo.objects.get(usuario__username=EMAIL)


class CargarProfesionalTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.chile = Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True)
        for modelo, nombres in ((Orientacion, ['Cognitivo Conductual (TCC)', 'Gestalt']),
                                (Especialidad, ['Orientación vocacional']),
                                (Publico, ['Adultos', 'Jóvenes', 'Orientación a padres', 'Niños'])):
            for nombre in nombres:
                modelo.objects.get_or_create(nombre=nombre, defaults={'aprobado': True})
        patron = mock.patch('directorio.dlocal_go.conectado', return_value=False)
        patron.start()
        self.addCleanup(patron.stop)

    def test_crea_el_usuario_y_el_perfil_con_lo_que_corresponde(self):
        _correr(_blob())
        usuario = User.objects.get(username=EMAIL)
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.has_usable_password())   # la crea ella con el link del mail
        psi = usuario.psicologo
        self.assertEqual((psi.nombre, psi.matricula, psi.whatsapp, psi.plan, psi.modalidad),
                         ('Ana Ejemplo', '111111', '+56911111111', 'premium', 'online'))
        self.assertEqual(psi.pais, self.chile)
        self.assertEqual([o.nombre for o in psi.orientaciones.all()], ['Cognitivo Conductual (TCC)'])
        self.assertEqual([e.nombre for e in psi.especialidades.all()], ['Orientación vocacional'])
        self.assertCountEqual([p.nombre for p in psi.publicos.all()], ['Adultos', 'Jóvenes', 'Orientación a padres'])
        self.assertIsNotNone(psi.terminos_aceptados_en)

    def test_nace_sin_contrasena_y_no_se_muestra_ninguna(self):
        salida = _correr(_blob())
        self.assertFalse(User.objects.get(username=EMAIL).has_usable_password())
        self.assertNotIn('Contraseña temporal', salida)

    def test_sin_pago_encontrado_avisa_que_todavia_no_figura_activa(self):
        salida = _correr(_blob())
        self.assertFalse(_psi().suscripcion_activa)
        self.assertIn('NO figura activa', salida)

    def test_marcar_pagado_la_deja_activa_con_su_plan(self):
        _correr(_blob(), '--marcar-pagado')
        psi = _psi()
        self.assertTrue(psi.suscripcion_activa)
        self.assertEqual(psi.plan, 'premium')
        self.assertIsNotNone(psi.fecha_pago_confirmado)

    def test_si_dlocal_encuentra_su_pago_la_activa_sin_marcar_nada_a_mano(self):
        def activar(psicologo):
            psicologo.activar_suscripcion(dlocal_subscription_id='SUB-9', plan='premium')
            return 'activa'
        with mock.patch('directorio.dlocal_go.conectado', return_value=True), \
                mock.patch('directorio.suscripciones.sincronizar_psicologo', side_effect=activar):
            salida = _correr(_blob())
        psi = _psi()
        self.assertTrue(psi.suscripcion_activa)
        self.assertEqual(psi.dlocal_subscription_id, 'SUB-9')
        self.assertIn('Pago según dLocal Go: activa', salida)

    def test_sin_foto_avisa_que_falta_y_no_se_publica(self):
        salida = _correr(_blob(), '--marcar-pagado', '--publicar')
        psi = _psi()
        self.assertIn('foto', salida.lower())
        self.assertTrue(psi.publicado_por_usuario)
        self.assertFalse(psi.publicado)

    def test_con_la_foto_cargada_y_publicar_queda_publicada(self):
        _correr(_blob(), '--marcar-pagado', '--publicar')
        Psicologo.objects.filter(usuario__username=EMAIL).update(foto='psicologos/x.jpg')
        self.assertTrue(_psi().publicado)

    def test_ignora_mayusculas_y_tildes_al_buscar_los_nombres(self):
        _correr(_blob(publicos=['jovenes', 'ADULTOS'], especialidades=['orientacion VOCACIONAL']))
        self.assertCountEqual([p.nombre for p in _psi().publicos.all()], ['Jóvenes', 'Adultos'])

    def test_un_nombre_que_no_existe_aborta_sin_crear_nada_y_lista_las_opciones(self):
        with self.assertRaises(CommandError) as ctx:
            _correr(_blob(publicos=['Adultos', 'Marcianos']))
        self.assertIn('Marcianos', str(ctx.exception))
        self.assertIn('Niños', str(ctx.exception))
        self.assertFalse(User.objects.filter(username=EMAIL).exists())
        self.assertEqual(Psicologo.objects.count(), 0)

    def test_un_email_ya_usado_aborta_y_no_toca_la_cuenta_existente(self):
        User.objects.create_user(EMAIL, email=EMAIL, password='ClaveVieja123')
        with self.assertRaises(CommandError):
            _correr(_blob())
        self.assertTrue(User.objects.get(username=EMAIL).check_password('ClaveVieja123'))
        self.assertEqual(Psicologo.objects.count(), 0)

    def test_datos_ilegibles_o_incompletos_abortan(self):
        for malo in ('esto-no-es-base64!', base64.b64encode(b'no es json').decode(), _blob(matricula='')):
            with self.assertRaises(CommandError):
                _correr(malo)
        self.assertEqual(User.objects.count(), 0)

    def test_pais_plan_y_modalidad_invalidos_abortan(self):
        for cambio in ({'pais': 'narnia'}, {'plan': 'gold'}, {'modalidad': 'telepatia'}):
            with self.assertRaises(CommandError):
                _correr(_blob(**cambio))
        self.assertEqual(User.objects.count(), 0)

    def test_si_dlocal_falla_igual_se_crea_y_avisa(self):
        from directorio import dlocal_go
        with mock.patch('directorio.dlocal_go.conectado', return_value=True), \
                mock.patch('directorio.suscripciones.sincronizar_psicologo', side_effect=dlocal_go.DLocalError('caído')):
            salida = _correr(_blob(), '--marcar-pagado')
        self.assertIn('No pude consultar a dLocal Go', salida)
        self.assertTrue(_psi().suscripcion_activa)


class BienvenidaPorMailTests(TestCase):
    """Le llega un mail con un link para crear su contraseña; entra y la elige ella."""

    def setUp(self):
        Pais.objects.all().delete()
        Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=True)
        for modelo, nombres in ((Orientacion, ['Cognitivo Conductual (TCC)']), (Especialidad, ['Orientación vocacional']),
                                (Publico, ['Adultos', 'Jóvenes', 'Orientación a padres'])):
            for nombre in nombres:
                modelo.objects.get_or_create(nombre=nombre, defaults={'aprobado': True})
        patron = mock.patch('directorio.dlocal_go.conectado', return_value=False)
        patron.start()
        self.addCleanup(patron.stop)

    def _link(self):
        import re
        mensaje = mail.outbox[0]
        return re.search(r'https://atencionpsi\.lat(/portal/contrasena/nueva/\S+/)', mensaje.body).group(1)

    def test_manda_un_mail_de_bienvenida_con_el_link_y_sin_contrasenas(self):
        salida = _correr(_blob(), '--marcar-pagado')
        self.assertEqual(len(mail.outbox), 1)
        mensaje = mail.outbox[0]
        self.assertEqual(mensaje.to, [EMAIL])
        self.assertIn('bienvenida', mensaje.subject)
        self.assertIn('Chile', mensaje.subject)
        self.assertIn('Hola Ana', mensaje.body)
        self.assertIn('/portal/contrasena/nueva/', mensaje.body)
        self.assertIn('vale 7 días', mensaje.body)
        self.assertIn('Le mandamos a', salida)

    def test_con_el_link_elige_su_contrasena_y_queda_adentro(self):
        _correr(_blob(), '--marcar-pagado')
        resp = self.client.get(self._link(), follow=True)
        self.assertContains(resp, 'Elegí tu contraseña')
        formulario = resp.redirect_chain[-1][0]
        resp = self.client.post(formulario, {'new_password1': 'UnaClaveMuyLarga2026', 'new_password2': 'UnaClaveMuyLarga2026'})
        self.assertRedirects(resp, reverse('portal_dashboard'), fetch_redirect_response=False)
        usuario = User.objects.get(username=EMAIL)
        self.assertTrue(usuario.check_password('UnaClaveMuyLarga2026'))
        self.assertEqual(str(self.client.session.get('_auth_user_id')), str(usuario.pk))

    def test_el_link_sirve_una_sola_vez(self):
        _correr(_blob(), '--marcar-pagado')
        link = self._link()
        resp = self.client.get(link, follow=True)
        self.client.post(resp.redirect_chain[-1][0], {'new_password1': 'UnaClaveMuyLarga2026', 'new_password2': 'UnaClaveMuyLarga2026'})
        self.client.logout()
        self.assertContains(self.client.get(link), 'Este link ya no es válido')

    def test_rechaza_una_contrasena_floja(self):
        _correr(_blob(), '--marcar-pagado')
        resp = self.client.get(self._link(), follow=True)
        resp = self.client.post(resp.redirect_chain[-1][0], {'new_password1': '12345678', 'new_password2': '12345678'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.get(username=EMAIL).has_usable_password())

    def test_sin_mail_no_manda_nada_y_explica_como_crearla(self):
        salida = _correr(_blob(), '--sin-mail')
        self.assertEqual(mail.outbox, [])
        self.assertIn('¿Olvidaste tu contraseña?', salida)

    def test_si_falla_el_mail_la_cuenta_igual_queda_y_avisa_que_hacer(self):
        with mock.patch('portal.contrasenas.enviar_bienvenida', side_effect=Exception('SMTP caído')):
            salida = _correr(_blob())
        self.assertTrue(User.objects.filter(username=EMAIL).exists())
        self.assertIn('No se pudo mandar el mail de bienvenida', salida)
        self.assertIn('¿Olvidaste tu contraseña?', salida)

    def test_si_el_link_vencio_el_olvide_tambien_le_sirve_aunque_no_tenga_contrasena(self):
        _correr(_blob(), '--marcar-pagado')
        mail.outbox.clear()
        resp = self.client.post(reverse('portal_contrasena_olvide'), {'email': EMAIL.upper()})
        self.assertRedirects(resp, reverse('portal_contrasena_enviada'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/portal/contrasena/nueva/', mail.outbox[0].body)

    def test_el_olvide_no_delata_si_un_email_existe(self):
        resp = self.client.post(reverse('portal_contrasena_olvide'), {'email': 'nadie@example.com'})
        self.assertRedirects(resp, reverse('portal_contrasena_enviada'))
        self.assertEqual(mail.outbox, [])

    def test_la_pantalla_de_ingreso_tiene_el_link_del_olvide(self):
        self.assertContains(self.client.get(reverse('portal_login')), reverse('portal_contrasena_olvide'))
