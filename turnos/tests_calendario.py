"""Extras del Plan Premium: link a la agenda externa, turnos como archivo de calendario (.ics) en los
mails, "Agregar a Google Calendar" y el calendario personal que se suscribe desde Google Calendar."""
import datetime
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from directorio.models import Orientacion, Pais, Psicologo
from portal.forms import PerfilForm

from . import calendario
from .models import DisponibilidadSemanal, TipoSesion, Turno


def _desplegar(texto):
    """Deshace el plegado de líneas largas de iCalendar (CRLF + espacio)."""
    return texto.replace('\r\n ', '')


def _proximo_lunes():
    hoy = timezone.localdate()
    return hoy + datetime.timedelta(days=(0 - hoy.weekday()) % 7 or 7)


class _Base(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.peru = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', simbolo_moneda='S/',
            precio_basico=49, precio_premium=85, activo=True, codigo_telefono='51',
        )

    def psi(self, email='ana@example.com', plan='premium', exento=True, **extra):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.peru, nombre='Ana Pérez', matricula='123', whatsapp='51999111222',
            bio='Mi bio', foto='psicologos/x.jpg', plan=plan, publicado_por_usuario=True, exento_de_pago=exento, **extra,
        )
        psi.orientaciones.add(Orientacion.objects.get_or_create(nombre='Gestalt', defaults={'aprobado': True})[0])
        return Psicologo.objects.get(pk=psi.pk)

    def turno(self, psi, hora=datetime.time(10, 0), estado='agendado', dias=None, **extra):
        tipo = psi.tipos_sesion.first() or TipoSesion.objects.create(psicologo=psi, nombre='Individual', duracion_min=50)
        fecha = _proximo_lunes() + datetime.timedelta(days=dias or 0)
        datos = dict(modalidad='online', nombres='Juan', apellidos='Gómez', telefono='51888',
                     email='juan@example.com', motivo_consulta='Ansiedad')
        datos.update(extra)
        return Turno.objects.create(
            psicologo=psi, tipo_sesion=tipo, fecha_hora=timezone.make_aware(datetime.datetime.combine(fecha, hora)),
            estado=estado, **datos,
        )


class LinkDeAgendaExternaTests(_Base):
    def form(self, psi, link, **extra):
        datos = {'nombre': psi.nombre, 'matricula': '123', 'whatsapp': '51999111222', 'modalidad': 'online',
                 'link_agenda_externa': link, **extra}
        return PerfilForm(datos, instance=psi, pais=self.peru)

    def test_el_campo_solo_aparece_para_premium(self):
        self.assertIn('link_agenda_externa', self.form(self.psi(), '').fields)
        self.assertNotIn('link_agenda_externa', self.form(self.psi('b@example.com', plan='basico'), '').fields)

    def test_un_basico_no_puede_cargarlo_aunque_mande_el_dato(self):
        psi = self.psi(plan='basico')
        form = self.form(psi, 'https://calendly.com/ana')
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        psi.refresh_from_db()
        self.assertEqual(psi.link_agenda_externa, '')

    def test_guarda_un_link_valido(self):
        psi = self.psi()
        form = self.form(psi, ' https://calendly.com/ana/consulta ')
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        psi.refresh_from_db()
        self.assertEqual(psi.link_agenda_externa, 'https://calendly.com/ana/consulta')

    def test_completa_el_https_si_lo_escribieron_sin_eso(self):
        form = self.form(self.psi(), 'calendly.com/ana')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['link_agenda_externa'], 'https://calendly.com/ana')

    def test_puede_quedar_vacio(self):
        form = self.form(self.psi(link_agenda_externa='https://calendly.com/ana'), '')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['link_agenda_externa'], '')

    def test_rechaza_lo_que_no_es_un_link_web(self):
        psi = self.psi()
        for malo in ('javascript:alert(1)', 'ftp://servidor.com/agenda', 'data:text/html,hola', 'mi agenda', 'https://', 'file:///etc/passwd'):
            form = self.form(psi, malo)
            self.assertFalse(form.is_valid(), malo)
            self.assertIn('link_agenda_externa', form.errors, malo)

    def test_el_perfil_publico_lleva_al_link_en_otra_pestana(self):
        psi = self.psi(link_agenda_externa='https://calendly.com/ana')
        resp = self.client.get(psi.url_publica)
        self.assertContains(resp, 'href="https://calendly.com/ana"')
        self.assertContains(resp, 'noopener noreferrer nofollow')
        self.assertNotContains(resp, reverse('reserva_tipo', args=['peru', psi.pk]))

    def test_la_tarjeta_del_buscador_tambien(self):
        psi = self.psi(link_agenda_externa='https://calendly.com/ana')
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, 'href="https://calendly.com/ana"')

    def test_si_baja_a_basico_el_link_deja_de_mostrarse(self):
        psi = self.psi(plan='basico', link_agenda_externa='https://calendly.com/ana')
        self.assertEqual(psi.agenda_externa, '')
        self.assertNotContains(self.client.get(psi.url_publica), 'calendly.com')

    def test_sin_link_sigue_la_agenda_de_atencion_psi(self):
        psi = self.psi()
        TipoSesion.objects.create(psicologo=psi, nombre='Individual', duracion_min=50)
        self.assertContains(self.client.get(psi.url_publica), reverse('reserva_tipo', args=['peru', psi.pk]))


class ArchivoDeCalendarioTests(_Base):
    def test_la_hora_se_interpreta_en_la_zona_del_pais(self):
        psi = self.psi()
        turno = self.turno(psi, hora=datetime.time(10, 0))
        inicio, fin = calendario.inicio_y_fin_utc(turno)
        self.assertEqual(inicio.hour, 15)                               # 10:00 de Lima (UTC-5) = 15:00 UTC
        self.assertEqual(fin - inicio, datetime.timedelta(minutes=50))

    def test_cada_pais_usa_su_zona(self):
        uruguay = Pais.objects.create(nombre='Uruguay', slug='uruguay', codigo_iso='UY', bandera_emoji='🇺🇾', moneda='UYU', activo=True)
        psi = Psicologo.objects.create(usuario=User.objects.create_user('u@example.com'), pais=uruguay, nombre='U', matricula='1', whatsapp='1', plan='premium')
        turno = self.turno(psi, hora=datetime.time(10, 0))
        self.assertEqual(calendario.inicio_y_fin_utc(turno)[0].hour, 13)  # Montevideo UTC-3

    def test_estructura_basica_del_ics(self):
        turno = self.turno(self.psi())
        texto = calendario.generar_ics([turno], 'Turnos')
        self.assertTrue(texto.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertTrue(texto.endswith('END:VCALENDAR\r\n'))
        for linea in ('VERSION:2.0', 'BEGIN:VEVENT', f'UID:turno-{turno.pk}@atencionpsi', 'DTSTART:', 'DTEND:', 'STATUS:CONFIRMED'):
            self.assertIn(linea, texto)
        self.assertEqual(texto.count('BEGIN:VEVENT'), texto.count('END:VEVENT'))
        self.assertNotIn('\n\n', texto.replace('\r\n', '\n'))

    def test_las_lineas_largas_se_pliegan_a_75_bytes(self):
        turno = self.turno(self.psi(), motivo_consulta='x' * 400)
        texto = calendario.generar_ics([turno], 'Turnos', con_motivo=True)
        for linea in texto.split('\r\n'):
            self.assertLessEqual(len(linea.encode('utf-8')), 75, linea)
        desplegado = texto.replace('\r\n ', '')
        self.assertIn('x' * 400, desplegado)

    def test_el_texto_con_caracteres_especiales_se_escapa(self):
        turno = self.turno(self.psi(), nombres='Ana, María', apellidos='O;Brien')
        texto = calendario.generar_ics([turno], 'Turnos').replace('\r\n ', '')
        self.assertIn('Ana\\, María O\\;Brien', texto)

    def test_el_motivo_de_consulta_no_va_salvo_que_se_pida(self):
        turno = self.turno(self.psi())
        self.assertNotIn('Ansiedad', _desplegar(calendario.generar_ics([turno], 'Turnos')))
        self.assertIn('Ansiedad', _desplegar(calendario.generar_ics([turno], 'Turnos', con_motivo=True)))

    def test_la_version_del_paciente_no_lleva_datos_de_otros(self):
        texto = calendario.generar_ics([self.turno(self.psi())], 'Sesión', para_profesional=False)
        self.assertIn('SUMMARY:Sesión con Ana Pérez', texto)
        self.assertNotIn('juan@example.com', texto)
        self.assertNotIn('Ansiedad', texto)

    def test_link_de_google_calendar(self):
        turno = self.turno(self.psi())
        enlace = urlparse(calendario.link_google_calendar(turno))
        self.assertEqual(enlace.netloc, 'calendar.google.com')
        datos = parse_qs(enlace.query)
        self.assertEqual(datos['action'], ['TEMPLATE'])
        self.assertEqual(datos['text'], ['Sesión con Ana Pérez'])
        inicio, fin = datos['dates'][0].split('/')
        self.assertTrue(inicio.endswith('Z') and fin.endswith('Z'))


class ReservaConPremiumTests(_Base):
    """Se reserva por el flujo real (con la sesión) y se mira qué mails salen."""

    def reservar(self, psi):
        tipo = TipoSesion.objects.create(psicologo=psi, nombre='Individual', duracion_min=60)
        DisponibilidadSemanal.objects.create(psicologo=psi, dia_semana=0, hora_desde=datetime.time(9, 0), hora_hasta=datetime.time(12, 0))
        lunes = _proximo_lunes()
        sesion = self.client.session
        sesion[f'reserva_{psi.pk}'] = {
            'tipo_sesion_id': tipo.pk, 'modalidad': 'online', 'fecha': lunes.isoformat(), 'hora': '10:00:00',
            'nombres': 'Juan', 'apellidos': 'Gómez', 'telefono': '51888', 'email': 'juan@example.com',
            'motivo_consulta': 'Ansiedad',
        }
        sesion.save()
        return self.client.post(reverse('reserva_confirmar', args=['peru', psi.pk]))

    def test_premium_el_profesional_recibe_el_turno_adjunto(self):
        psi = self.psi()
        resp = self.reservar(psi)
        self.assertEqual(resp.status_code, 200)
        al_profesional = [m for m in mail.outbox if m.to == ['ana@example.com']]
        self.assertEqual(len(al_profesional), 1)
        nombre, contenido, tipo = al_profesional[0].attachments[0]
        self.assertEqual(nombre, 'turno.ics')
        self.assertTrue(tipo.startswith('text/calendar'))
        self.assertIn('BEGIN:VEVENT', contenido)
        self.assertIn('Juan Gómez', contenido)

    def test_premium_el_paciente_recibe_confirmacion_con_el_turno(self):
        self.reservar(self.psi())
        al_paciente = [m for m in mail.outbox if m.to == ['juan@example.com']]
        self.assertEqual(len(al_paciente), 1)
        mensaje = al_paciente[0]
        self.assertIn('Ana Pérez', mensaje.subject)
        self.assertIn('calendar.google.com', mensaje.body)
        self.assertIn('+51999111222', mensaje.body)
        self.assertEqual(mensaje.attachments[0][0], 'turno.ics')
        self.assertNotIn('juan@example.com', mensaje.attachments[0][1])
        self.assertNotIn('Ansiedad', mensaje.attachments[0][1])

    def test_premium_la_pantalla_de_confirmacion_ofrece_agregar_al_calendario(self):
        resp = self.reservar(self.psi())
        self.assertContains(resp, 'Agregar a Google Calendar')
        self.assertContains(resp, 'data:text/calendar')

    def test_basico_profesional_y_paciente_reciben_mail_pero_sin_calendario(self):
        resp = self.reservar(self.psi(plan='basico'))
        self.assertEqual(resp.status_code, 200)
        self.assertCountEqual([m.to[0] for m in mail.outbox], ['ana@example.com', 'juan@example.com'])
        for mensaje in mail.outbox:
            self.assertEqual(mensaje.attachments, [])
            self.assertNotIn('calendar.google.com', mensaje.body)
        al_paciente = next(m for m in mail.outbox if m.to == ['juan@example.com'])
        self.assertIn('quedó confirmado', al_paciente.body)
        self.assertIn('+51999111222', al_paciente.body)
        self.assertNotContains(resp, 'Google Calendar')
        self.assertContains(resp, 'Te enviamos la confirmación a')

    def test_si_falla_el_mail_al_paciente_el_turno_igual_queda_y_la_pantalla_no_miente(self):
        from unittest import mock
        psi = self.psi()
        with mock.patch('turnos.views._confirmar_al_paciente', side_effect=Exception('SMTP caído')):
            resp = self.reservar(psi)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Turno.objects.filter(psicologo=psi).count(), 1)
        self.assertContains(resp, 'No pudimos enviarte el mail de confirmación')
        self.assertNotContains(resp, 'Te enviamos la confirmación a')

    def test_si_falla_el_aviso_al_profesional_el_paciente_igual_recibe_su_mail(self):
        from unittest import mock
        with mock.patch('turnos.views._avisar_por_mail', side_effect=Exception('SMTP caído')):
            resp = self.reservar(self.psi(plan='basico'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([m.to for m in mail.outbox], [['juan@example.com']])


class CalendarioPersonalTests(_Base):
    def url(self, psi):
        return reverse('calendario_personal', args=[psi.asegurar_token_calendario()])

    def test_devuelve_los_turnos_vigentes_como_ics(self):
        psi = self.psi()
        vigente = self.turno(psi)
        self.turno(psi, hora=datetime.time(11, 0), estado='cancelado')
        resp = self.client.get(self.url(psi))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['Content-Type'].startswith('text/calendar'))
        contenido = resp.content.decode()
        self.assertIn(f'UID:turno-{vigente.pk}@atencionpsi', contenido)
        self.assertEqual(contenido.count('BEGIN:VEVENT'), 1)
        self.assertIn('noindex', resp['X-Robots-Tag'])
        self.assertNotIn('Ansiedad', contenido)                          # el motivo de consulta no sale del sistema

    def test_no_incluye_turnos_viejos(self):
        psi = self.psi()
        viejo = self.turno(psi)
        Turno.objects.filter(pk=viejo.pk).update(fecha_hora=timezone.now() - datetime.timedelta(days=200))
        self.assertEqual(self.client.get(self.url(psi)).content.decode().count('BEGIN:VEVENT'), 0)

    def test_cada_profesional_ve_solo_lo_suyo(self):
        a, b = self.psi(), self.psi('b@example.com')
        self.turno(a)
        self.assertEqual(self.client.get(self.url(b)).content.decode().count('BEGIN:VEVENT'), 0)

    def test_una_clave_inventada_no_existe(self):
        self.psi().asegurar_token_calendario()
        self.assertEqual(self.client.get(reverse('calendario_personal', args=['clave-inventada'])).status_code, 404)

    def test_quien_no_es_premium_no_tiene_calendario(self):
        psi = self.psi(plan='basico')
        self.assertEqual(self.client.get(self.url(psi)).status_code, 404)

    def test_renovar_deja_sin_efecto_el_link_anterior(self):
        psi = self.psi()
        viejo = self.url(psi)
        self.client.force_login(psi.usuario)
        resp = self.client.post(reverse('portal_calendario_renovar'))
        self.assertRedirects(resp, reverse('portal_dashboard'))
        self.assertEqual(self.client.get(viejo).status_code, 404)
        psi.refresh_from_db()
        self.assertEqual(self.client.get(reverse('calendario_personal', args=[psi.token_calendario])).status_code, 200)

    def test_renovar_solo_por_post_y_solo_premium(self):
        psi = self.psi()
        self.client.force_login(psi.usuario)
        self.assertEqual(self.client.get(reverse('portal_calendario_renovar')).status_code, 405)
        basico = self.psi('b@example.com', plan='basico')
        self.client.force_login(basico.usuario)
        self.assertEqual(self.client.post(reverse('portal_calendario_renovar')).status_code, 404)

    def test_el_panel_muestra_el_link_solo_a_premium(self):
        psi = self.psi()
        self.client.force_login(psi.usuario)
        resp = self.client.get(reverse('portal_dashboard'))
        psi.refresh_from_db()
        self.assertContains(resp, f'/calendario/{psi.token_calendario}.ics')
        self.client.logout()
        basico = self.psi('b@example.com', plan='basico')
        self.client.force_login(basico.usuario)
        resp = self.client.get(reverse('portal_dashboard'))
        self.assertNotContains(resp, '.ics')
        self.assertContains(resp, 'Plan Premium')
        basico.refresh_from_db()
        self.assertEqual(basico.token_calendario, '')


class TextosDelPlanPremiumTests(_Base):
    """Las ventajas nuevas están escritas en todas las plantillas del Premium, en todos los países."""

    def test_registro_terminos_y_checkout_las_mencionan(self):
        self.assertContains(self.client.get(reverse('portal_registro', args=['peru'])), 'Google Calendar')
        self.assertContains(self.client.get(reverse('portal_registro', args=['peru'])), 'agenda externa')
        terminos = self.client.get(reverse('terminos')).content.decode()
        self.assertIn('Google Calendar', terminos)
        self.assertIn('agenda externa', terminos)
        psi = self.psi(plan='basico', exento=False)
        self.client.force_login(psi.usuario)
        checkout = self.client.get(reverse('portal_checkout'))
        self.assertContains(checkout, 'Google Calendar')
        self.assertContains(checkout, 'agenda externa')
