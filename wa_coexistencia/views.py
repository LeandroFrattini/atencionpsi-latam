"""Conecta el número de WhatsApp Business de Atención Psi LATAM a la API de WhatsApp (coexistencia: el
número sigue funcionando en la app del celular). Es una página para el staff, que se usa una vez.

El secreto de la app de Meta va SOLO en la variable de entorno META_APP_SECRET (en Render), nunca en el código.
El token que devuelve Meta se usa para suscribir la app a la cuenta y no se guarda ni se muestra.
"""
import json
import logging
import os

import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v25.0"
# Identificadores públicos de la app de Meta y de la configuración de registro (no son secretos).
APP_ID = "895833073525544"
CONFIG_ID = "2165478444074323"


@staff_member_required
@ensure_csrf_cookie
def coexistencia(request):
    # ensure_csrf_cookie: el botón hace un fetch con la cookie csrftoken y la página no tiene formulario.
    resp = render(request, "wa_coexistencia/coexistencia.html", {
        "app_id": APP_ID,
        "config_id": CONFIG_ID,
    })
    # Django manda por defecto "same-origin", que corta la comunicación con la ventana emergente de Meta
    # y el registro se cuelga. Solo para esta página: "same-origin-allow-popups".
    resp["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return resp


@staff_member_required
@require_POST
def coexistencia_callback(request):
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Datos inválidos"}, status=400)
    code = data.get("code")
    waba_id = str(data.get("waba_id") or "")
    phone_number_id = data.get("phone_number_id")
    if not code or not waba_id:
        return JsonResponse({"ok": False, "error": "Falta code o waba_id"}, status=400)
    if not waba_id.isdigit():   # va dentro de la URL de la API
        return JsonResponse({"ok": False, "error": "waba_id inválido"}, status=400)

    secreto = os.environ.get("META_APP_SECRET")
    if not secreto:
        return JsonResponse({"ok": False, "error": "Falta configurar META_APP_SECRET en el servidor"}, status=500)

    try:
        # 1) Canjear el code por un token (el code vence en ~30 segundos)
        r = requests.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": APP_ID,
            "client_secret": secreto,
            "code": code,
        }, timeout=20)
        tok = r.json()
        token = tok.get("access_token")
        if not token:
            return JsonResponse({"ok": False, "paso": "canje", "respuesta": tok}, status=400)

        # 2) Suscribir la app a la cuenta de WhatsApp (para recibir webhooks)
        s = requests.post(f"{GRAPH}/{waba_id}/subscribed_apps",
                          headers={"Authorization": f"Bearer {token}"}, timeout=20)
        suscripcion = s.json()
    except (requests.RequestException, ValueError):
        logger.exception("Falló la conexión con la API de Meta al conectar WhatsApp (waba %s)", waba_id)
        return JsonResponse({"ok": False, "error": "No se pudo hablar con Meta. Probá de nuevo en un momento."}, status=502)

    # En coexistencia NO se llama a /register: el número ya está registrado.
    return JsonResponse({
        "ok": s.ok,
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "suscripcion": suscripcion,
    })
