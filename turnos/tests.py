import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from directorio.models import Orientacion, Pais, Psicologo

from .disponibilidad import slot_disponible, slots_para_fecha
from .models import DiaNoAtiende, DisponibilidadSemanal, TipoSesion, Turno


def _proximo_dia_semana(dia_semana):
    """Próxima fecha (>= hoy) que caiga en ese día de la semana (0=lunes)."""
    hoy = timezone.localdate()
    delta = (dia_semana - hoy.weekday()) % 7
    return hoy + datetime.timedelta(days=delta or 7)


class DisponibilidadTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.lunes = _proximo_dia_semana(0)
        DisponibilidadSemanal.objects.create(
            psicologo=self.psicologo, dia_semana=0,
            hora_desde=datetime.time(9, 0), hora_hasta=datetime.time(11, 0),
        )

    def test_genera_slots_segun_duracion(self):
        slots = slots_para_fecha(self.psicologo, self.lunes, duracion_min=60)
        horas = [s['hora'] for s in slots]
        self.assertEqual(horas, [datetime.time(9, 0), datetime.time(10, 0)])

    def test_domingo_no_tiene_slots(self):
        domingo = self.lunes + datetime.timedelta(days=6)
        self.assertEqual(slots_para_fecha(self.psicologo, domingo, duracion_min=50), [])

    def test_dia_no_atiende_bloquea_el_dia(self):
        DiaNoAtiende.objects.create(psicologo=self.psicologo, fecha_desde=self.lunes, fecha_hasta=self.lunes)
        self.assertEqual(slots_para_fecha(self.psicologo, self.lunes, duracion_min=60), [])

    def test_turno_existente_marca_el_slot_tomado(self):
        tipo = TipoSesion.objects.create(psicologo=self.psicologo, nombre='Individual', duracion_min=60)
        fecha_hora = timezone.make_aware(datetime.datetime.combine(self.lunes, datetime.time(9, 0)))
        Turno.objects.create(
            psicologo=self.psicologo, tipo_sesion=tipo, fecha_hora=fecha_hora, modalidad='online',
            nombres='A', apellidos='B', telefono='1', email='a@example.com',
        )
        slots = slots_para_fecha(self.psicologo, self.lunes, duracion_min=60)
        tomado = next(s for s in slots if s['hora'] == datetime.time(9, 0))
        self.assertTrue(tomado['tomado'])

    def test_slot_disponible_puntual(self):
        self.assertTrue(slot_disponible(self.psicologo, self.lunes, datetime.time(9, 0), duracion_min=60))
        self.assertFalse(slot_disponible(self.psicologo, self.lunes, datetime.time(23, 0), duracion_min=60))


class WizardReservaTests(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion = Orientacion.objects.create(nombre='TCC')
        self.usuario = User.objects.create_user('psico@example.com', email='psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Psico Test', matricula='1', whatsapp='519',
            bio='bio', foto='psicologos/test.jpg', suscripcion_activa=True, publicado_por_usuario=True,
            modalidad='ambas',
        )
        self.psicologo.orientaciones.add(self.orientacion)
        self.tipo = TipoSesion.objects.create(psicologo=self.psicologo, nombre='Individual', duracion_min=50, precio=85)
        self.lunes = _proximo_dia_semana(0)
        DisponibilidadSemanal.objects.create(
            psicologo=self.psicologo, dia_semana=0,
            hora_desde=datetime.time(9, 0), hora_hasta=datetime.time(11, 0),
        )

    def _avanzar_hasta_horario(self):
        self.client.post(reverse('reserva_tipo', args=['peru', self.psicologo.pk]), {'tipo_sesion': self.tipo.pk})
        self.client.post(reverse('reserva_modalidad', args=['peru', self.psicologo.pk]), {'modalidad': 'online'})

    def test_wizard_completo_crea_el_turno(self):
        self._avanzar_hasta_horario()
        resp = self.client.post(reverse('reserva_horario', args=['peru', self.psicologo.pk]), {
            'fecha': self.lunes.isoformat(), 'hora': '09:00',
        })
        self.assertRedirects(resp, reverse('reserva_datos', args=['peru', self.psicologo.pk]))

        resp = self.client.post(reverse('reserva_datos', args=['peru', self.psicologo.pk]), {
            'nombres': 'Juan', 'apellidos': 'Pérez', 'telefono': '51999999999', 'email': 'juan@example.com',
        })
        self.assertRedirects(resp, reverse('reserva_confirmar', args=['peru', self.psicologo.pk]))

        resp = self.client.post(reverse('reserva_confirmar', args=['peru', self.psicologo.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Turno.objects.filter(email='juan@example.com').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('psico@example.com', mail.outbox[0].to)

    def test_no_puede_saltear_pasos(self):
        resp = self.client.get(reverse('reserva_datos', args=['peru', self.psicologo.pk]))
        # No sigue el 302 en cascada (horario -> modalidad -> tipo, porque
        # tampoco hay nada en sesión): solo importa que NO deje pasar directo.
        self.assertRedirects(resp, reverse('reserva_horario', args=['peru', self.psicologo.pk]),
                              fetch_redirect_response=False)

    def test_modalidad_se_salta_si_el_psicologo_es_fijo(self):
        self.psicologo.modalidad = 'online'
        self.psicologo.save()
        self.client.post(reverse('reserva_tipo', args=['peru', self.psicologo.pk]), {'tipo_sesion': self.tipo.pk})
        resp = self.client.get(reverse('reserva_modalidad', args=['peru', self.psicologo.pk]))
        self.assertRedirects(resp, reverse('reserva_horario', args=['peru', self.psicologo.pk]))

    def test_no_deja_reservar_un_horario_ya_tomado(self):
        fecha_hora = timezone.make_aware(datetime.datetime.combine(self.lunes, datetime.time(9, 0)))
        Turno.objects.create(
            psicologo=self.psicologo, tipo_sesion=self.tipo, fecha_hora=fecha_hora, modalidad='online',
            nombres='Otro', apellidos='Paciente', telefono='1', email='otro@example.com',
        )
        self._avanzar_hasta_horario()
        resp = self.client.post(reverse('reserva_horario', args=['peru', self.psicologo.pk]), {
            'fecha': self.lunes.isoformat(), 'hora': '09:00',
        }, follow=True)
        self.assertContains(resp, 'ya no está disponible')
