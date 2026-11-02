"""Tarjeta de profesional (buscador, inicio de cada país, ciudades): tope de contenido para que
todas se vean parecidas, con "+N" para lo que no entra."""
import re

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Especialidad, Orientacion, Pais, Psicologo, Publico


class TarjetaConTopesTests(TestCase):
    def setUp(self):
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)

    def _psi(self, nombre, n_orient, n_motivos, n_publicos, email):
        usuario = User.objects.create_user(email, email=email, password='ClaveSegura123')
        psi = Psicologo.objects.create(
            usuario=usuario, pais=self.pais, nombre=nombre, matricula='1', whatsapp='51999999999', bio='bio',
            foto='psicologos/test.jpg', ciudad='Lima', suscripcion_activa=True, publicado_por_usuario=True,
        )
        for i in range(n_orient):
            psi.orientaciones.add(Orientacion.objects.get_or_create(nombre=f'Orientación {i}', defaults={'aprobado': True})[0])
        for i in range(n_motivos):
            psi.especialidades.add(Especialidad.objects.get_or_create(nombre=f'Motivo {i}', defaults={'aprobado': True})[0])
        for i in range(n_publicos):
            psi.publicos.add(Publico.objects.get_or_create(nombre=f'Público {i}', defaults={'aprobado': True})[0])
        return psi

    def _tarjeta(self, nombre):
        html = self.client.get(reverse('buscador_pais', args=['peru'])).content.decode()
        bloques = html.split('<div class="psicologo-card">')[1:]
        for b in bloques:
            if nombre in b:
                return b
        self.fail('no se encontró la tarjeta de ' + nombre)

    def test_con_mucho_contenido_muestra_solo_el_tope_y_el_resto_como_mas_n(self):
        self._psi('Muchas Cosas', n_orient=7, n_motivos=6, n_publicos=9, email='m@example.com')
        t = self._tarjeta('Muchas Cosas')
        # Orientaciones: 2 y "+5"
        self.assertEqual(len(re.findall(r'Orientación \d', t)), 2)
        self.assertRegex(t, r'<span class="psicologo-mas">\+5</span>')
        # Motivos de consulta: 3 chips verdes y "+3 más"
        self.assertEqual(t.count('psicologo-chip psicologo-chip-verde'), 3)
        self.assertIn('+3 más', t)
        # Públicos: 3 chips y "+6 más"
        self.assertEqual(len(re.findall(r'<span class="psicologo-chip">Público', t)), 3)
        self.assertIn('+6 más', t)

    def test_con_poco_contenido_no_aparece_nada_de_mas(self):
        self._psi('Pocas Cosas', n_orient=2, n_motivos=3, n_publicos=3, email='p@example.com')
        t = self._tarjeta('Pocas Cosas')
        self.assertNotIn('psicologo-mas', t)
        self.assertNotIn('psicologo-chip-mas', t)
        self.assertEqual(len(re.findall(r'Orientación \d', t)), 2)
        self.assertEqual(t.count('psicologo-chip psicologo-chip-verde'), 3)

    def test_justo_un_elemento_de_mas_dice_mas_uno(self):
        self._psi('Casi Justo', n_orient=3, n_motivos=4, n_publicos=4, email='c@example.com')
        t = self._tarjeta('Casi Justo')
        self.assertRegex(t, r'<span class="psicologo-mas">\+1</span>')
        self.assertEqual(t.count('+1 más'), 2)    # motivos y públicos

    def test_la_vista_previa_del_editor_usa_los_mismos_topes(self):
        """El JS de portal/editar_perfil.html dibuja su propia tarjeta: mismos números que la real."""
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'templates', 'portal', 'editar_perfil.html'), encoding='utf-8') as f:
            js = f.read()
        self.assertIn("tildadas('especialidades');", js)
        self.assertIn('motivosTodos.slice(0, 3)', js)
        self.assertIn('publicosTodos.slice(0, 3)', js)
        self.assertIn('orient.slice(0, 2)', js)
        self.assertIn('psicologo-chip-mas', js)
        self.assertIn('psicologo-mas', js)

    def test_el_css_alinea_los_botones_al_fondo_y_limita_las_orientaciones(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'static', 'css', 'base.css'), encoding='utf-8') as f:
            css = f.read()
        self.assertRegex(css, r'\.psicologo-card-botones \{[^}]*margin-top: auto')
        self.assertRegex(css, r'\.psicologo-orientacion \{[^}]*-webkit-line-clamp: 3')
        self.assertIn('.psicologo-chip-mas', css)
