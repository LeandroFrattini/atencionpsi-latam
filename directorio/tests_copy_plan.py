"""El Plan Básico dice que el perfil se encuentra buscando "psicólogo en tu ciudad";
la ciudad del país (Lima, Santiago...) va solo como ejemplo. Si el texto nombrara
una ciudad sin más, se entendería que el plan sirve solo para esa ciudad."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Pais, Psicologo

VIEJO = 'te van a encontrar buscando'
NUEVO = 'psicólogo en tu ciudad'


class CopyDelPlanBasicoTests(TestCase):
    def _ejemplo(self, pais):
        return f'(por ejemplo, "psicólogo en {pais.ciudad_ejemplo}")'

    def test_terminos_lo_aclara_en_cada_pais_activo(self):
        contenido = self.client.get(reverse('terminos')).content.decode()
        self.assertNotIn(VIEJO, contenido)
        paises = Pais.objects.filter(activo=True, es_externo=False)
        self.assertGreaterEqual(paises.count(), 4)
        for pais in paises:
            self.assertIn(self._ejemplo(pais), contenido, pais.nombre)
        self.assertGreaterEqual(contenido.count(NUEVO), paises.count())

    def test_el_registro_lo_aclara(self):
        for slug in ('peru', 'uruguay', 'chile', 'mexico'):
            pais = Pais.objects.get(slug=slug)
            resp = self.client.get(reverse('portal_registro', args=[slug]))
            self.assertContains(resp, NUEVO, msg_prefix=slug)
            self.assertContains(resp, self._ejemplo(pais), msg_prefix=slug)
            self.assertNotContains(resp, VIEJO, msg_prefix=slug)

    def test_el_checkout_lo_aclara(self):
        for slug in ('peru', 'chile', 'mexico'):
            pais = Pais.objects.get(slug=slug)
            usuario = User.objects.create_user(f'{slug}@example.com', password='ClaveSegura123')
            Psicologo.objects.create(usuario=usuario, pais=pais, nombre='Ana Test', matricula='1', whatsapp='1')
            self.client.force_login(usuario)
            resp = self.client.get(reverse('portal_checkout'))
            self.assertContains(resp, NUEVO, msg_prefix=slug)
            self.assertContains(resp, self._ejemplo(pais), msg_prefix=slug)
            self.assertNotContains(resp, VIEJO, msg_prefix=slug)
            self.client.logout()
