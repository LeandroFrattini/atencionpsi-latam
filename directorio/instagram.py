import re

_USUARIO = re.compile(r'^[a-z0-9._]{1,30}$')
_URL = re.compile(r'^(?:https?://)?(?:www\.)?instagram\.com/([^/?#\s]+)', re.I)


def normalizar_instagram(texto):
    """Deja solo el usuario, en minúsculas y sin arroba: acepta "@usuario",
    "usuario" o el link del perfil. Devuelve '' si viene vacío y lanza
    ValueError si no parece un usuario de Instagram válido."""
    t = (texto or '').strip()
    if not t:
        return ''
    m = _URL.match(t)
    if m:
        t = m.group(1)
    t = t.lstrip('@').strip().lower()
    if not _USUARIO.match(t):
        raise ValueError(t)
    return t
