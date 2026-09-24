import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from directorio.models import Orientacion, Pais, Psicologo, Publico
from turnos.models import DisponibilidadSemanal, Paciente, TipoSesion, Turno


class RegistroTests(TestCase):
    def setUp(self):
        # Aísla del país que la migración 0006 siembra para producción.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def test_registro_crea_cuenta_y_manda_a_checkout(self):
        resp = self.client.post(reverse('portal_registro', args=['peru']), {
            'nombre': 'Nueva Psicóloga',
            'email': 'nueva@example.com',
            'whatsapp': '51988888888',
            'password': 'ClaveSegura123',
        })
        self.assertRedirects(resp, reverse('portal_checkout'))
        self.assertTrue(User.objects.filter(username='nueva@example.com').exists())
        psicologo = Psicologo.objects.get(usuario__username='nueva@example.com')
        self.assertEqual(psicologo.pais, self.pais)
        self.assertFalse(psicologo.suscripcion_activa)

    def test_no_deja_registrar_email_repetido(self):
        User.objects.create_user('repetido@example.com', password='ClaveSegura123')
        resp = self.client.post(reverse('portal_registro', args=['peru']), {
            'nombre': 'Otra', 'email': 'repetido@example.com', 'whatsapp': '51988888888', 'password': 'ClaveSegura123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Psicologo.objects.filter(nombre='Otra').exists())


class SimularPagoTests(TestCase):
    def setUp(self):
        # Aísla del país que la migración 0006 siembra para producción.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.client.force_login(self.usuario)

    @override_settings(DEBUG=True)
    def test_simular_pago_activa_suscripcion_en_debug(self):
        resp = self.client.post(reverse('portal_simular_pago'))
        self.assertRedirects(resp, reverse('portal_dashboard'))
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.suscripcion_activa)
        self.assertIsNotNone(self.psicologo.fecha_pago_confirmado)

    @override_settings(DEBUG=False)
    def test_simular_pago_no_existe_fuera_de_debug(self):
        resp = self.client.post(reverse('portal_simular_pago'))
        self.assertEqual(resp.status_code, 404)


class PublicarDespublicarTests(TestCase):
    def setUp(self):
        # Aísla del país que la migración 0006 siembra para producción.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion = Orientacion.objects.create(nombre='Sistémica')
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519',
            bio='bio', foto='psicologos/test.jpg', suscripcion_activa=True,
        )
        self.psicologo.orientaciones.add(self.orientacion)
        self.client.force_login(self.usuario)

    def test_publicar_con_requisitos_completos_funciona(self):
        self.client.post(reverse('portal_publicar'))
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.publicado_por_usuario)
        self.assertTrue(self.psicologo.publicado)

    def test_publicar_sin_requisitos_no_publica(self):
        self.psicologo.suscripcion_activa = False
        self.psicologo.save()
        self.client.post(reverse('portal_publicar'))
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.publicado_por_usuario)

    def test_despublicar_apaga_el_perfil(self):
        self.psicologo.publicado_por_usuario = True
        self.psicologo.save()
        self.client.post(reverse('portal_despublicar'))
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.publicado_por_usuario)


class EditarPerfilPublicoNuevoTests(TestCase):
    def setUp(self):
        # Aísla del país que la migración 0006 siembra para producción.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(
            usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519',
        )
        self.client.force_login(self.usuario)

    def _post_perfil(self, **extra):
        data = dict(
            nombre='Psico', matricula='1', whatsapp='519', ciudad='', modalidad='online',
            bio='', docencia='',
            **{'formaciones-TOTAL_FORMS': '0', 'formaciones-INITIAL_FORMS': '0',
               'formaciones-MIN_NUM_FORMS': '0', 'formaciones-MAX_NUM_FORMS': '1000'},
        )
        data.update(extra)
        return self.client.post(reverse('portal_editar_perfil'), data)

    def test_publico_nuevo_crea_y_asocia(self):
        self._post_perfil(publico_nuevo='Deportistas')
        self.assertTrue(Publico.objects.filter(nombre='Deportistas').exists())
        self.psicologo.refresh_from_db()
        self.assertIn('Deportistas', [p.nombre for p in self.psicologo.publicos.all()])

    def test_publico_nuevo_reusa_uno_existente_sin_duplicar(self):
        Publico.objects.create(nombre='Deportistas')
        self._post_perfil(publico_nuevo='deportistas')  # distinta capitalización a propósito
        self.assertEqual(Publico.objects.filter(nombre__iexact='Deportistas').count(), 1)

    def test_orientacion_nueva_crea_y_asocia(self):
        self._post_perfil(orientacion_nueva='Gestalt')
        self.assertTrue(Orientacion.objects.filter(nombre='Gestalt').exists())
        self.psicologo.refresh_from_db()
        self.assertIn('Gestalt', [o.nombre for o in self.psicologo.orientaciones.all()])

    def test_orientacion_nueva_reusa_una_existente_sin_duplicar(self):
        Orientacion.objects.create(nombre='Gestalt')
        self._post_perfil(orientacion_nueva='gestalt')  # distinta capitalización a propósito
        self.assertEqual(Orientacion.objects.filter(nombre__iexact='Gestalt').count(), 1)

    def test_sesiones_atendidas_es_opcional_y_se_guarda(self):
        self._post_perfil(sesiones_atendidas='1000')
        self.psicologo.refresh_from_db()
        self.assertEqual(self.psicologo.sesiones_atendidas, 1000)

    def test_sesiones_atendidas_sin_elegir_no_bloquea_el_guardado(self):
        resp = self._post_perfil()
        self.assertEqual(resp.status_code, 302)
        self.psicologo.refresh_from_db()
        self.assertIsNone(self.psicologo.sesiones_atendidas)

    def test_opcion_en_blanco_del_select_esta_en_español(self):
        resp = self.client.get(reverse('portal_editar_perfil'))
        self.assertContains(resp, 'Preferís no decir por ahora')
        self.assertNotContains(resp, 'Select an option')

    def test_sin_publico_nuevo_no_pasa_nada(self):
        antes = Publico.objects.count()
        self._post_perfil()
        self.assertEqual(Publico.objects.count(), antes)


class AgendaPortalTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.client.force_login(self.usuario)

    def _payload(self, **extra):
        data = {
            'tipos-TOTAL_FORMS': '1', 'tipos-INITIAL_FORMS': '0',
            'tipos-MIN_NUM_FORMS': '0', 'tipos-MAX_NUM_FORMS': '1000',
            'tipos-0-nombre': '', 'tipos-0-duracion_min': '', 'tipos-0-precio': '', 'tipos-0-orden': '',
            'disp-TOTAL_FORMS': '2', 'disp-INITIAL_FORMS': '0',
            'disp-MIN_NUM_FORMS': '0', 'disp-MAX_NUM_FORMS': '1000',
            'disp-0-dia_semana': '', 'disp-0-hora_desde': '', 'disp-0-hora_hasta': '',
            'disp-1-dia_semana': '', 'disp-1-hora_desde': '', 'disp-1-hora_hasta': '',
            'libres-TOTAL_FORMS': '1', 'libres-INITIAL_FORMS': '0',
            'libres-MIN_NUM_FORMS': '0', 'libres-MAX_NUM_FORMS': '1000',
            'libres-0-fecha_desde': '', 'libres-0-fecha_hasta': '', 'libres-0-motivo': '',
        }
        data.update(extra)
        return data

    def test_carga_tipo_de_sesion_y_disponibilidad(self):
        resp = self.client.post(reverse('portal_agenda'), self._payload(**{
            'tipos-0-nombre': 'Individual', 'tipos-0-duracion_min': '50', 'tipos-0-orden': '0',
            'disp-0-dia_semana': '0', 'disp-0-hora_desde': '09:00', 'disp-0-hora_hasta': '13:00',
        }))
        self.assertRedirects(resp, reverse('portal_agenda'))
        self.assertEqual(self.psicologo.tipos_sesion.count(), 1)
        self.assertEqual(self.psicologo.disponibilidad_semanal.count(), 1)

    def test_rechaza_bloque_con_horario_invertido(self):
        resp = self.client.post(reverse('portal_agenda'), self._payload(**{
            'disp-0-dia_semana': '0', 'disp-0-hora_desde': '18:00', 'disp-0-hora_hasta': '09:00',
        }))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.psicologo.disponibilidad_semanal.count(), 0)

    def test_agenda_es_privada_por_login(self):
        self.client.logout()
        resp = self.client.get(reverse('portal_agenda'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('portal_login'), resp['Location'])


class TurnosPortalTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.otro = Psicologo.objects.create(
            usuario=User.objects.create_user('otro@example.com', password='ClaveSegura123'),
            pais=self.pais, nombre='Otro', matricula='2', whatsapp='520',
        )
        self.tipo = TipoSesion.objects.create(psicologo=self.psicologo, nombre='Individual', duracion_min=50)
        self.turno = Turno.objects.create(
            psicologo=self.psicologo, tipo_sesion=self.tipo,
            fecha_hora=timezone.now() - datetime.timedelta(days=1), modalidad='online',
            nombres='Ana', apellidos='Paciente', telefono='1', email='ana@example.com',
        )
        self.client.force_login(self.usuario)

    def test_marcar_realizado(self):
        resp = self.client.post(reverse('portal_turno_accion', args=[self.turno.pk]), {'accion': 'realizado'})
        self.assertRedirects(resp, reverse('portal_turnos'))
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, 'realizado')

    def test_cancelar_y_reactivar(self):
        self.client.post(reverse('portal_turno_accion', args=[self.turno.pk]), {'accion': 'cancelado'})
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, 'cancelado')
        self.client.post(reverse('portal_turno_accion', args=[self.turno.pk]), {'accion': 'reactivar'})
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, 'agendado')

    def test_no_puede_tocar_turno_de_otro_psicologo(self):
        ajeno = Turno.objects.create(
            psicologo=self.otro, tipo_sesion=TipoSesion.objects.create(psicologo=self.otro, nombre='X'),
            fecha_hora=timezone.now(), modalidad='online',
            nombres='B', apellidos='C', telefono='1', email='b@example.com',
        )
        resp = self.client.post(reverse('portal_turno_accion', args=[ajeno.pk]), {'accion': 'cancelado'})
        self.assertEqual(resp.status_code, 404)

    def test_guardar_notas_de_sesion(self):
        self.client.post(reverse('portal_turno_detalle', args=[self.turno.pk]), {'notas_profesional': 'Trabajamos respiración.'})
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.notas_profesional, 'Trabajamos respiración.')


class PacientesPortalTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario = User.objects.create_user('psico@example.com', password='ClaveSegura123')
        self.psicologo = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Psico', matricula='1', whatsapp='519')
        self.otro = Psicologo.objects.create(
            usuario=User.objects.create_user('otro@example.com', password='ClaveSegura123'),
            pais=self.pais, nombre='Otro', matricula='2', whatsapp='520',
        )
        self.client.force_login(self.usuario)

    def test_alta_manual_de_paciente(self):
        resp = self.client.post(reverse('portal_paciente_nuevo'), {
            'nombres': 'Juan', 'apellidos': 'Pérez', 'telefono': '555', 'email': 'juan@example.com',
            'edad': '30', 'notas': 'Viene por recomendación.',
        })
        paciente = Paciente.objects.get(email='juan@example.com')
        self.assertEqual(paciente.psicologo, self.psicologo)
        self.assertRedirects(resp, reverse('portal_paciente_detalle', args=[paciente.pk]))

    def test_no_deja_email_duplicado_en_la_misma_cartera(self):
        Paciente.objects.create(psicologo=self.psicologo, nombres='A', apellidos='B', email='dup@example.com')
        resp = self.client.post(reverse('portal_paciente_nuevo'), {
            'nombres': 'C', 'apellidos': 'D', 'telefono': '', 'email': 'dup@example.com', 'edad': '', 'notas': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Paciente.objects.filter(email='dup@example.com').count(), 1)

    def test_lista_solo_muestra_pacientes_propios(self):
        Paciente.objects.create(psicologo=self.psicologo, nombres='Mío', apellidos='Uno')
        Paciente.objects.create(psicologo=self.otro, nombres='Ajeno', apellidos='Dos')
        resp = self.client.get(reverse('portal_pacientes'))
        self.assertContains(resp, 'Mío')
        self.assertNotContains(resp, 'Ajeno')

    def test_no_puede_ver_ficha_de_otro_psicologo(self):
        ajeno = Paciente.objects.create(psicologo=self.otro, nombres='Ajeno', apellidos='Dos')
        resp = self.client.get(reverse('portal_paciente_detalle', args=[ajeno.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_eliminar_ficha_conserva_los_turnos(self):
        paciente = Paciente.objects.create(psicologo=self.psicologo, nombres='Con', apellidos='Turnos', email='ct@example.com')
        tipo = TipoSesion.objects.create(psicologo=self.psicologo, nombre='Individual', duracion_min=50)
        turno = Turno.objects.create(
            psicologo=self.psicologo, paciente=paciente, tipo_sesion=tipo,
            fecha_hora=timezone.now(), modalidad='online',
            nombres='Con', apellidos='Turnos', telefono='1', email='ct@example.com',
        )
        self.client.post(reverse('portal_paciente_eliminar', args=[paciente.pk]))
        self.assertFalse(Paciente.objects.filter(pk=paciente.pk).exists())
        turno.refresh_from_db()
        self.assertIsNone(turno.paciente)
        self.assertEqual(turno.nombres, 'Con')


class RecordatoriosCommandTests(TestCase):
    def setUp(self):
        # Aísla del país que la migración 0006 siembra para producción.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def _psicologo(self, email, **overrides):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        datos = dict(usuario=usuario, pais=self.pais, nombre='Test', matricula='1', whatsapp='519')
        datos.update(overrides)
        return Psicologo.objects.create(**datos)

    def test_recordatorio_de_pago_solo_a_los_que_pasaron_24hs_sin_pagar(self):
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        p_viejo = self._psicologo('viejo@example.com')
        Psicologo.objects.filter(pk=p_viejo.pk).update(fecha_alta=hace_2_dias)

        self._psicologo('reciente@example.com')  # se registró ahora, no le toca todavía

        from django.core.management import call_command
        call_command('enviar_recordatorios', '--apply')

        p_viejo.refresh_from_db()
        self.assertTrue(p_viejo.recordatorio_pago_enviado)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('viejo@example.com', mail.outbox[0].to)

    def test_dry_run_no_manda_nada(self):
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        p = self._psicologo('viejo@example.com')
        Psicologo.objects.filter(pk=p.pk).update(fecha_alta=hace_2_dias)

        from django.core.management import call_command
        call_command('enviar_recordatorios')

        p.refresh_from_db()
        self.assertFalse(p.recordatorio_pago_enviado)
        self.assertEqual(len(mail.outbox), 0)

    def test_recordatorio_de_perfil_a_pagos_sin_publicar(self):
        p = self._psicologo('pagado@example.com', suscripcion_activa=True)
        hace_2_dias = timezone.now() - datetime.timedelta(days=2)
        Psicologo.objects.filter(pk=p.pk).update(fecha_pago_confirmado=hace_2_dias)

        from django.core.management import call_command
        call_command('enviar_recordatorios', '--apply')

        p.refresh_from_db()
        self.assertTrue(p.recordatorio_perfil_enviado)
        self.assertEqual(len(mail.outbox), 1)
