from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailCaseInsensitiveBackend(ModelBackend):
    """Copiado del backend probado en atencionpsi.com.ar: el login no debe
    fallar porque el email quedó guardado con mayúsculas distintas a como
    el profesional lo escribe.

    A propósito NO llama a self.user_can_authenticate(user) (que rechaza
    is_active=False): se devuelve el user igual con la contraseña correcta
    y es AuthenticationForm.confirm_login_allowed() quien lo frena -- así
    LoginForm puede mostrar "todavía no confirmaste tu email" en vez del
    genérico "usuario o contraseña incorrectos" que da el rechazo acá. El
    login en sí sigue bloqueado: confirm_login_allowed sigue rechazando la
    cuenta antes de que llegue a loguearse."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return None
        if user.check_password(password):
            return user
        return None
