"""Crear o recuperar la contraseña con un link que llega por mail (sin conocer la anterior).

Sirve para dos cosas:
* "Olvidé mi contraseña" en la pantalla de ingreso;
* la bienvenida de una profesional cargada a mano (comando `cargar_profesional`): nace sin contraseña y
  recibe un link para crear la suya, así nunca circula una contraseña por mail ni por chat.
"""
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def dias_de_validez():
    return settings.PASSWORD_RESET_TIMEOUT // 86400


def contexto_de_mail():
    return {
        'sitio': settings.SITE_URL.rstrip('/'),
        'contacto_email': settings.CONTACTO_EMAIL,
        'dias': dias_de_validez(),
    }


class OlvideContrasenaForm(PasswordResetForm):
    """Como el de Django, pero también le manda el link a las cuentas que todavía no tienen contraseña
    (las cargadas a mano): el de Django las ignora, y justamente ellas la necesitan."""

    def get_users(self, email):
        return User.objects.filter(email__iexact=email, is_active=True)


class OlvideContrasenaView(auth_views.PasswordResetView):
    form_class = OlvideContrasenaForm
    template_name = 'portal/contrasena_olvide.html'
    email_template_name = 'portal/email/contrasena_olvide.txt'
    subject_template_name = 'portal/email/contrasena_olvide_asunto.txt'
    success_url = reverse_lazy('portal_contrasena_enviada')

    @property
    def extra_email_context(self):
        return contexto_de_mail()


class NuevaContrasenaView(auth_views.PasswordResetConfirmView):
    """Pantalla donde se elige la contraseña nueva. Al terminar deja la sesión iniciada."""
    template_name = 'portal/contrasena_nueva.html'
    success_url = reverse_lazy('portal_dashboard')
    post_reset_login = True
    post_reset_login_backend = 'directorio.auth_backends.EmailCaseInsensitiveBackend'


def enlace_para_crear_contrasena(usuario):
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    return settings.SITE_URL.rstrip('/') + reverse('portal_contrasena_nueva', args=[uid, token])


def enviar_bienvenida(psicologo):
    """Mail de bienvenida a una profesional cargada a mano, con el link para crear su contraseña."""
    contexto = {
        **contexto_de_mail(),
        'nombre': psicologo.nombre_corto or psicologo.nombre,
        'pais': psicologo.pais.nombre,
        'email': psicologo.usuario.email,
        'enlace': enlace_para_crear_contrasena(psicologo.usuario),
    }
    EmailMessage(
        subject=f'Te damos la bienvenida a Atención Psi {psicologo.pais.nombre}',
        body=render_to_string('portal/email/bienvenida_profesional.txt', contexto),
        from_email=None,
        to=[psicologo.usuario.email],
    ).send()
