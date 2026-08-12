from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailCaseInsensitiveBackend(ModelBackend):
    """Copiado del backend probado en atencionpsi.com.ar: el login no debe
    fallar porque el email quedó guardado con mayúsculas distintas a como
    el profesional lo escribe."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
