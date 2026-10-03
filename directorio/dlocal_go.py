"""Cliente mínimo de la API de dLocal Go (suscripciones).

Documentación: https://docs.dlocalgo.com/integration-api/welcome-to-dlocal-go-api/subscriptions

Notas de lo que se confirmó contra la API real (2026-10-03):
- Autenticación: ``Authorization: Bearer <API_KEY>:<SECRET_KEY>``.
- Cloudflare bloquea con "error 1010" el User-Agent por defecto de urllib; con
  ``requests`` (y un User-Agent propio, como acá) responde bien.
- Las claves de producción y las de sandbox son distintas y cada entorno tiene
  su host (settings.DLOCAL_GO_API_BASE).
"""
import hashlib
import hmac
import re

import requests
from django.conf import settings

TIMEOUT = 20
USER_AGENT = 'AtencionPsiLatam/1.0 (+https://atencionpsi.lat)'
TAMANO_PAGINA = 100


class DLocalError(Exception):
    """Falló la comunicación con dLocal Go (red, credenciales, respuesta rara)."""

    def __init__(self, mensaje, status=None):
        super().__init__(mensaje)
        self.status = status


def conectado():
    return bool(settings.DLOCAL_GO_API_KEY and settings.DLOCAL_GO_SECRET_KEY)


def _request(metodo, ruta, **kwargs):
    if not conectado():
        raise DLocalError('Faltan DLOCAL_GO_API_KEY / DLOCAL_GO_SECRET_KEY.')
    headers = {
        'Authorization': f'Bearer {settings.DLOCAL_GO_API_KEY}:{settings.DLOCAL_GO_SECRET_KEY}',
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
    }
    try:
        resp = requests.request(
            metodo, settings.DLOCAL_GO_API_BASE.rstrip('/') + ruta, headers=headers, timeout=TIMEOUT, **kwargs,
        )
    except requests.RequestException as e:
        raise DLocalError(f'No se pudo hablar con dLocal Go: {e}') from e
    if resp.status_code >= 400:
        raise DLocalError(f'dLocal Go respondió {resp.status_code}: {resp.text[:300]}', status=resp.status_code)
    try:
        return resp.json()
    except ValueError as e:
        raise DLocalError(f'dLocal Go devolvió algo que no es JSON: {resp.text[:200]}') from e


def _paginar(ruta):
    """Recorre todas las páginas de un listado y devuelve los elementos."""
    pagina, resultados = 1, []
    while True:
        datos = _request('GET', ruta, params={'page': pagina, 'page_size': TAMANO_PAGINA})
        resultados.extend(datos.get('data', []))
        if pagina >= (datos.get('total_pages') or 0):
            return resultados
        pagina += 1


def crear_plan(*, nombre, descripcion, pais_iso, moneda, monto, success_url, error_url, back_url, notification_url):
    """POST /subscription/plan. Cobro mensual (frequency_type MONTHLY): sin
    day_of_month, así se cobra el mismo día en que el profesional se suscribe
    -- es lo que dicen los Términos."""
    return _request('POST', '/subscription/plan', json={
        'name': nombre,
        'description': descripcion,
        'country': pais_iso,
        'currency': moneda,
        'amount': monto,
        'frequency_type': 'MONTHLY',
        'frequency_value': 1,
        'success_url': success_url,
        'error_url': error_url,
        'back_url': back_url,
        'notification_url': notification_url,
    })


def listar_suscripciones(plan_id):
    return _paginar(f'/subscription/plan/{plan_id}/subscription/all')


def listar_ejecuciones(plan_id, subscription_id):
    return _paginar(f'/subscription/plan/{plan_id}/subscription/{subscription_id}/execution/all')


def desactivar_suscripcion(plan_id, subscription_id):
    return _request('PATCH', f'/subscription/plan/{plan_id}/subscription/{subscription_id}/deactivate')


def obtener_pago(payment_id):
    return _request('GET', f'/payments/{payment_id}')


def firma_valida(cuerpo, header_authorization):
    """Verifica la firma de una notificación. dLocal Go manda
    ``Authorization: V2-HMAC-SHA256, Signature: <hex>`` donde la firma es
    HMAC-SHA256 con la secret key sobre ``API_KEY + cuerpo`` (sin separador).
    `cuerpo` tiene que ser el body crudo, byte a byte, tal cual llegó."""
    if not (conectado() and header_authorization):
        return False
    m = re.search(r'Signature:\s*([0-9a-fA-F]+)', header_authorization)
    if not m:
        return False
    mensaje = settings.DLOCAL_GO_API_KEY.encode() + cuerpo
    esperada = hmac.new(settings.DLOCAL_GO_SECRET_KEY.encode(), mensaje, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada.lower(), m.group(1).lower())
