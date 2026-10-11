"""El teléfono/WhatsApp de contacto de la plataforma aparece en todos lados."""
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Pais, Psicologo

TEL = '+54 9 291 578 7311'
WA = 'https://wa.me/5492915787311'


class TelefonoDeContactoTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def test_el_footer_lo_muestra_en_todas_las_paginas(self):
        for url in (reverse('hub'), reverse('faq'), reverse('pais_home', args=['peru'])):
            resp = self.client.get(url)
            self.assertContains(resp, WA, msg_prefix=url)
            self.assertContains(resp, TEL, msg_prefix=url)

    def test_contacto_terminos_y_privacidad_lo_muestran(self):
        for nombre in ('contacto', 'terminos', 'privacidad'):
            resp = self.client.get(reverse(nombre))
            self.assertContains(resp, WA, msg_prefix=nombre)
            self.assertContains(resp, TEL, msg_prefix=nombre)

    def test_el_mail_de_verificacion_lo_trae(self):
        self.client.post(reverse('portal_registro', args=['peru']), dict(
            nombre='Nueva', email='nueva@example.com', whatsapp='51999999999',
            password='ClaveSegura123', acepto_terminos='on',
        ))
        enviado = mail.outbox[0]
        self.assertIn(TEL, enviado.body)
        self.assertIn(WA, enviado.alternatives[0][0])

    def test_los_recordatorios_cierran_con_el_whatsapp(self):
        usuario = User.objects.create_user('p@example.com', email='p@example.com', password='ClaveSegura123')
        psi = Psicologo.objects.create(usuario=usuario, pais=self.pais, nombre='Psi', matricula='1', whatsapp='1')
        Psicologo.objects.filter(pk=psi.pk).update(fecha_alta=timezone.now() - timezone.timedelta(days=3))
        call_command('enviar_recordatorios', '--apply', stdout=StringIO())
        self.assertTrue(mail.outbox)
        self.assertIn(TEL, mail.outbox[0].body)
