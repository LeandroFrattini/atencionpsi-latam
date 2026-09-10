import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Formacion, Orientacion, Pais, Psicologo


class PsicologoPublicacionTests(TestCase):
    def setUp(self):
        # La migración 0006 siembra los países reales (incluido 'peru') para
        # que producción no arranque vacía -- acá se pisan para que cada test
        # arme su propio fixture aislado, sin depender de ese dato sembrado.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.orientacion = Orientacion.objects.create(nombre='Cognitivo Conductual (TCC)')
        self.usuario = User.objects.create_user('ana@example.com', password='ClaveSegura123')

    def _psicologo_completo(self, **overrides):
        datos = dict(
            usuario=self.usuario, pais=self.pais, nombre='Ana Test',
            matricula='12345', whatsapp='51999999999', bio='Trabajo con adultos.',
            foto='psicologos/test.jpg',
        )
        datos.update(overrides)
        p = Psicologo.objects.create(**datos)
        p.orientaciones.add(self.orientacion)
        return p

    def test_perfil_incompleto_sin_bio_no_puede_publicar(self):
        p = Psicologo.objects.create(usuario=self.usuario, pais=self.pais, nombre='Ana', matricula='1', whatsapp='51999999999')
        self.assertFalse(p.perfil_completo)
        self.assertFalse(p.puede_publicar)

    def test_perfil_completo_sin_pago_no_puede_publicar(self):
        p = self._psicologo_completo()
        self.assertTrue(p.perfil_completo)
        self.assertFalse(p.puede_publicar)

    def test_completo_y_pago_pero_sin_click_publicar_no_esta_publicado(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        self.assertTrue(p.puede_publicar)
        self.assertFalse(p.publicado)

    def test_publicado_por_usuario_mas_requisitos_publica(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        p.publicado_por_usuario = True
        p.save()
        self.assertTrue(p.publicado)

    def test_si_se_corta_la_suscripcion_se_despublica_solo(self):
        p = self._psicologo_completo()
        p.activar_suscripcion()
        p.publicado_por_usuario = True
        p.save()
        self.assertTrue(p.publicado)

        p.suscripcion_activa = False
        p.save()
        self.assertFalse(p.publicado)

    def test_exenta_de_pago_no_necesita_suscripcion(self):
        p = self._psicologo_completo(exento_de_pago=True)
        self.assertTrue(p.puede_publicar)
        self.assertIsNotNone(p.fecha_pago_confirmado)


class BuscadorYDetalleTests(TestCase):
    def setUp(self):
        # Ídem PsicologoPublicacionTests: aislar del país sembrado por la
        # migración 0006 para no chocar con el slug 'peru'.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(
            nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN',
            activo=True, etiqueta_matricula='N° de Colegiatura (CPsP)',
        )
        self.orientacion = Orientacion.objects.create(nombre='Sistémica')
        self.usuario_publicado = User.objects.create_user('pub@example.com', password='ClaveSegura123')
        self.usuario_sin_publicar = User.objects.create_user('nopub@example.com', password='ClaveSegura123')

        self.publicado = Psicologo.objects.create(
            usuario=self.usuario_publicado, pais=self.pais, nombre='Publicada Test',
            matricula='999', whatsapp='51999999999', bio='Bio', foto='psicologos/test.jpg',
            suscripcion_activa=True, publicado_por_usuario=True,
        )
        self.publicado.orientaciones.add(self.orientacion)
        Formacion.objects.create(psicologo=self.publicado, descripcion='Licenciada en Psicología. UNC', orden=0)

        self.sin_publicar = Psicologo.objects.create(
            usuario=self.usuario_sin_publicar, pais=self.pais, nombre='Sin Publicar Test',
            matricula='888', whatsapp='51999999998',
        )

    def test_buscador_solo_muestra_publicados(self):
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, 'Publicada Test')
        self.assertNotContains(resp, 'Sin Publicar Test')

    def test_pais_inactivo_da_404(self):
        Pais.objects.create(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱', moneda='CLP', activo=False)
        resp = self.client.get(reverse('buscador_pais', args=['chile']))
        self.assertEqual(resp.status_code, 404)

    def test_detalle_de_publicado_muestra_formacion_y_etiqueta_correcta(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.publicado.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Licenciada en Psicología. UNC')
        self.assertContains(resp, 'N° de Colegiatura (CPsP)')

    def test_detalle_de_no_publicado_da_404(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.sin_publicar.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_pais_externo_redirige_afuera_en_vez_de_mostrar_buscador_vacio(self):
        Pais.objects.create(
            nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS',
            activo=True, es_externo=True, url_externa='https://atencionpsi.com.ar',
        )
        resp = self.client.get(reverse('buscador_pais', args=['argentina']))
        self.assertRedirects(resp, 'https://atencionpsi.com.ar', fetch_redirect_response=False)

    def test_buscador_incluye_hreflang_de_todos_los_paises_activos(self):
        # El buscador de un país tiene que avisarle a los buscadores que hay
        # una versión equivalente por cada otro país activo -- incluyendo
        # Argentina (externa, apunta directo a atencionpsi.com.ar) -- para
        # que a alguien en Uruguay no le aparezca el resultado de Perú.
        Pais.objects.create(
            nombre='Uruguay', slug='uruguay', codigo_iso='UY', bandera_emoji='🇺🇾', moneda='UYU', activo=True,
        )
        Pais.objects.create(
            nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS',
            activo=True, es_externo=True, url_externa='https://atencionpsi.com.ar',
        )
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, '<link rel="alternate" hreflang="es-PE" href="http://testserver/peru/">')
        self.assertContains(resp, '<link rel="alternate" hreflang="es-UY" href="http://testserver/uruguay/">')
        self.assertContains(resp, '<link rel="alternate" hreflang="es-AR" href="https://atencionpsi.com.ar">')
        self.assertContains(resp, '<link rel="alternate" hreflang="x-default" href="http://testserver/">')

    def test_html_lang_usa_el_codigo_de_pais_en_el_buscador(self):
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, '<html lang="es-PE">')

    def test_ningun_comentario_de_django_se_filtra_al_html(self):
        # {# ... #} de una sola línea se recorta bien, pero si por error
        # alguien escribe uno que ocupe varias líneas, Django deja de
        # reconocerlo como comentario y lo manda tal cual al HTML -- eso
        # ya pasó una vez acá y le rompía el <head> entero al navegador
        # (cerraba <head> antes de tiempo al toparse con texto suelto),
        # tirando abajo el CSS, el canonical y los meta OG de esa página.
        # Usar siempre {% comment %}...{% endcomment %} para multilínea.
        for url in [reverse('hub'), reverse('buscador_pais', args=['peru']),
                    reverse('detalle_psicologo', args=['peru', self.publicado.pk])]:
            resp = self.client.get(url)
            self.assertNotIn(b'{#', resp.content)

    def test_seo_completo_en_el_perfil_no_se_corta_el_head(self):
        resp = self.client.get(reverse('detalle_psicologo', args=['peru', self.publicado.pk]))
        contenido = resp.content.decode()
        self.assertIn('<meta name="description"', contenido)
        self.assertIn('<link rel="canonical"', contenido)
        self.assertIn('<meta property="og:image" content="http://testserver/media/psicologos/test.jpg">', contenido)
        self.assertIn('application/ld+json', contenido)
        # Todo eso tiene que estar realmente adentro de <head>, no después
        # de que el navegador ya lo haya cerrado por error.
        self.assertLess(contenido.index('og:image'), contenido.index('</head>'))

    def test_html_lang_generico_fuera_de_un_pais(self):
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, '<html lang="es">')


class SEOTecnicoTests(TestCase):
    def setUp(self):
        # Ídem PsicologoPublicacionTests: aislar del país sembrado por la
        # migración 0006 para no chocar con el slug 'peru'.
        Pais.objects.all().delete()
        self.pais = Pais.objects.create(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪', moneda='PEN', activo=True)
        self.usuario_publicado = User.objects.create_user('pub2@example.com', password='ClaveSegura123')
        self.usuario_sin_publicar = User.objects.create_user('nopub2@example.com', password='ClaveSegura123')
        self.orientacion = Orientacion.objects.create(nombre='Sistémica')

        self.publicado = Psicologo.objects.create(
            usuario=self.usuario_publicado, pais=self.pais, nombre='Publicada SEO',
            matricula='1', whatsapp='51999999999', bio='Bio', foto='psicologos/test.jpg',
            suscripcion_activa=True, publicado_por_usuario=True, sesiones_atendidas=1000,
        )
        self.publicado.orientaciones.add(self.orientacion)

        self.sin_publicar = Psicologo.objects.create(
            usuario=self.usuario_sin_publicar, pais=self.pais, nombre='Sin Publicar SEO',
            matricula='2', whatsapp='51999999998', sesiones_atendidas=2000,
        )

    def test_robots_txt_bloquea_lo_privado_y_apunta_al_sitemap(self):
        resp = self.client.get('/robots.txt')
        contenido = resp.content.decode()
        self.assertIn('Disallow: /admin/', contenido)
        self.assertIn('Disallow: /portal/', contenido)
        self.assertIn('Sitemap: http://testserver/sitemap.xml', contenido)

    def test_sitemap_solo_lista_publicados(self):
        resp = self.client.get('/sitemap.xml')
        contenido = resp.content.decode()
        self.assertIn(f'/peru/p/{self.publicado.pk}/', contenido)
        self.assertNotIn(f'/peru/p/{self.sin_publicar.pk}/', contenido)
        # El hub y el buscador de cada país activo también tienen que estar.
        self.assertIn('<loc>http://testserver/</loc>', contenido)
        self.assertIn('<loc>http://testserver/peru/</loc>', contenido)

    def test_total_de_sesiones_solo_suma_publicados(self):
        # El sin publicar declaró 2000 pero no debería contar -- todavía no
        # pagó ni completó el perfil, no es un profesional real y visible.
        resp = self.client.get(reverse('buscador_pais', args=['peru']))
        self.assertContains(resp, 'Más de 1000 sesiones atendidas en Latinoamérica')


@override_settings(CONTACTO_EMAIL='hola@atencionpsi.lat')
class ContactoTests(TestCase):
    def test_formulario_valido_manda_el_mail(self):
        resp = self.client.post(reverse('contacto'), {
            'nombre': 'Ana', 'email': 'ana@example.com', 'mensaje': 'Hola, tengo una consulta.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        self.assertEqual(enviado.to, ['hola@atencionpsi.lat'])
        self.assertEqual(enviado.reply_to, ['ana@example.com'])
        self.assertIn('Ana', enviado.subject)
        self.assertIn('Hola, tengo una consulta.', enviado.body)

    def test_formulario_invalido_no_manda_nada(self):
        resp = self.client.post(reverse('contacto'), {'nombre': '', 'email': 'no-es-un-mail', 'mensaje': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


class TerminosYFooterTests(TestCase):
    def test_terminos_muestra_el_dato_legal_real(self):
        resp = self.client.get(reverse('terminos'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'CUIL')
        self.assertNotContains(resp, 'Completar')

    def test_terminos_muestra_los_dos_planes_de_cada_pais_activo(self):
        # Los países sembrados por la migración 0006/0008 (Perú, Uruguay,
        # Chile activos y con precio) tienen que aparecer cada uno con sus
        # dos planes -- Argentina (externa) y los inactivos, no.
        resp = self.client.get(reverse('terminos'))
        contenido = resp.content.decode()
        self.assertIn('Plan Básico', contenido)
        self.assertIn('Plan Premium', contenido)
        for nombre in ['Perú', 'Uruguay', 'Chile']:
            self.assertIn(nombre, contenido)
        self.assertNotIn('Colombia', contenido)
        self.assertNotIn('México', contenido)

    def test_footer_tiene_los_links_legales_en_cualquier_pagina(self):
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, reverse('terminos'))
        self.assertContains(resp, reverse('faq'))
        self.assertContains(resp, reverse('contacto'))

    @override_settings(INSTAGRAM_URL='', FACEBOOK_URL='')
    def test_sin_redes_configuradas_no_muestra_iconos_genericos(self):
        resp = self.client.get(reverse('hub'))
        self.assertNotContains(resp, 'footer-redes')

    @override_settings(INSTAGRAM_URL='https://instagram.com/atencionpsi')
    def test_con_instagram_configurado_muestra_el_link_real(self):
        resp = self.client.get(reverse('hub'))
        self.assertContains(resp, 'https://instagram.com/atencionpsi')
