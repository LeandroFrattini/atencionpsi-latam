"""Agenda: una fila por día (lunes a sábado) para quien empieza, y botón para agregar más filas."""
import re

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from directorio.models import Pais, Psicologo
from turnos.models import DisponibilidadSemanal


class AgendaFilasTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psi = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.client.force_login(self.usuario)

    def _payload_semana(self, **horarios):
        """6 filas como las manda el navegador: el día elegido y las horas que se completen."""
        data = {
            'tipos-TOTAL_FORMS': '1', 'tipos-INITIAL_FORMS': '0', 'tipos-MIN_NUM_FORMS': '0', 'tipos-MAX_NUM_FORMS': '1000',
            'tipos-0-nombre': '', 'tipos-0-duracion_min': '50', 'tipos-0-precio': '', 'tipos-0-orden': '0',  # los valores por defecto, como en el navegador
            'disp-TOTAL_FORMS': '6', 'disp-INITIAL_FORMS': '0', 'disp-MIN_NUM_FORMS': '0', 'disp-MAX_NUM_FORMS': '1000',
            'libres-TOTAL_FORMS': '1', 'libres-INITIAL_FORMS': '0', 'libres-MIN_NUM_FORMS': '0', 'libres-MAX_NUM_FORMS': '1000',
            'libres-0-fecha_desde': '', 'libres-0-fecha_hasta': '', 'libres-0-motivo': '',
        }
        for dia in range(6):
            desde, hasta = horarios.get(str(dia), ('', ''))
            data[f'disp-{dia}-dia_semana'] = str(dia)
            data[f'disp-{dia}-hora_desde'] = desde
            data[f'disp-{dia}-hora_hasta'] = hasta
        return data

    def test_quien_empieza_ve_una_fila_por_dia_con_el_dia_elegido(self):
        resp = self.client.get(reverse('portal_agenda'))
        self.assertEqual(resp.context['fs_disp'].total_form_count(), 6)
        html = resp.content.decode()
        elegidos = re.findall(r'name="disp-(\d)-dia_semana".*?<option value="(\d)" selected', html, re.S)
        self.assertEqual([(a, b) for a, b in elegidos], [(str(i), str(i)) for i in range(6)])

    def test_se_cargan_varios_dias_de_una_sola_vez(self):
        resp = self.client.post(reverse('portal_agenda'), self._payload_semana(**{
            '0': ('09:00', '13:00'), '2': ('14:00', '18:00'), '5': ('09:00', '12:00'),
        }))
        self.assertRedirects(resp, reverse('portal_agenda'))
        self.assertEqual(
            sorted(self.psi.disponibilidad_semanal.values_list('dia_semana', flat=True)), [0, 2, 5],
        )

    def test_las_filas_con_solo_el_dia_se_ignoran(self):
        resp = self.client.post(reverse('portal_agenda'), self._payload_semana())
        self.assertRedirects(resp, reverse('portal_agenda'))
        self.assertEqual(self.psi.disponibilidad_semanal.count(), 0)

    def test_con_horarios_ya_cargados_vuelve_a_haber_pocas_filas_vacias(self):
        DisponibilidadSemanal.objects.create(psicologo=self.psi, dia_semana=0, hora_desde='09:00', hora_hasta='13:00')
        resp = self.client.get(reverse('portal_agenda'))
        self.assertEqual(resp.context['fs_disp'].total_form_count(), 1 + 2)

    def test_la_pagina_trae_el_boton_y_la_plantilla_para_agregar_filas(self):
        html = self.client.get(reverse('portal_agenda')).content.decode()
        for prefijo in ('tipos', 'disp', 'libres'):
            self.assertIn(f'data-prefijo="{prefijo}"', html)
            self.assertIn(f'id="vacia-{prefijo}"', html)
        self.assertIn('__prefix__', html)
        self.assertIn('+ Agregar otro horario', html)

    def test_una_fila_agregada_con_el_boton_se_guarda(self):
        DisponibilidadSemanal.objects.create(psicologo=self.psi, dia_semana=0, hora_desde='09:00', hora_hasta='13:00')
        existente = DisponibilidadSemanal.objects.get(psicologo=self.psi)
        data = {
            'tipos-TOTAL_FORMS': '0', 'tipos-INITIAL_FORMS': '0', 'tipos-MIN_NUM_FORMS': '0', 'tipos-MAX_NUM_FORMS': '1000',
            'libres-TOTAL_FORMS': '0', 'libres-INITIAL_FORMS': '0', 'libres-MIN_NUM_FORMS': '0', 'libres-MAX_NUM_FORMS': '1000',
            'disp-TOTAL_FORMS': '4', 'disp-INITIAL_FORMS': '1', 'disp-MIN_NUM_FORMS': '0', 'disp-MAX_NUM_FORMS': '1000',
            'disp-0-id': str(existente.pk), 'disp-0-dia_semana': '0', 'disp-0-hora_desde': '09:00', 'disp-0-hora_hasta': '13:00',
            'disp-1-dia_semana': '', 'disp-1-hora_desde': '', 'disp-1-hora_hasta': '',
            'disp-2-dia_semana': '', 'disp-2-hora_desde': '', 'disp-2-hora_hasta': '',
            # fila sumada con el botón (la tercera extra)
            'disp-3-dia_semana': '0', 'disp-3-hora_desde': '15:00', 'disp-3-hora_hasta': '19:00',
        }
        resp = self.client.post(reverse('portal_agenda'), data)
        self.assertRedirects(resp, reverse('portal_agenda'))
        self.assertEqual(self.psi.disponibilidad_semanal.count(), 2)
