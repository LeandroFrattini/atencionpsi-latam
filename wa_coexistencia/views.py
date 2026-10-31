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


def _canjear_code(code, secreto, request):
    """Canjea el code por un token. Un code que sale del SDK de JavaScript de Facebook se canjea con
    redirect_uri VACÍO; si Meta responde 36008 ("redirect_uri distinto") se prueban las alternativas
    razonables. Devuelve (token, respuesta_de_meta, redirect_uri_usado)."""
    candidatas = ["", request.build_absolute_uri(request.path.replace("callback/", "")), f"{request.scheme}://{request.get_host()}/"]
    respuesta = {}
    for redirect_uri in candidatas:
        respuesta = requests.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": APP_ID,
            "client_secret": secreto,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=20).json()
        if respuesta.get("access_token"):
            return respuesta["access_token"], respuesta, redirect_uri
        if (respuesta.get("error") or {}).get("error_subcode") != 36008:
            break   # otro error (code vencido, secreto mal...): probar otro redirect_uri no sirve
    return None, respuesta, None


def _cuentas_del_token(token, secreto):
    """IDs de las cuentas de WhatsApp Business (WABA) a las que el token da acceso. Sirve cuando el
    navegador no recibió el evento de Meta con el waba_id: el token sabe a qué cuentas se le dio permiso."""
    r = requests.get(f"{GRAPH}/debug_token", params={
        "input_token": token,
        "access_token": f"{APP_ID}|{secreto}",
    }, timeout=20)
    ids = []
    for permiso in (r.json().get("data") or {}).get("granular_scopes") or []:
        if permiso.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging"):
            for waba in permiso.get("target_ids") or []:
                if str(waba).isdigit() and str(waba) not in ids:
                    ids.append(str(waba))
    return ids


def _conectar_cuenta(waba_id, token):
    """Suscribe la app a la cuenta (para recibir webhooks) y lista sus números. Sin datos sensibles."""
    cabecera = {"Authorization": f"Bearer {token}"}
    s = requests.post(f"{GRAPH}/{waba_id}/subscribed_apps", headers=cabecera, timeout=20)
    n = requests.get(f"{GRAPH}/{waba_id}/phone_numbers", headers=cabecera,
                     params={"fields": "id,verified_name,status"}, timeout=20)
    numeros = n.json().get("data") if n.ok else None
    return {
        "waba_id": waba_id,
        "suscripcion_ok": s.ok,
        "suscripcion": s.json(),
        "numeros": numeros,
    }


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
    if not code:
        return JsonResponse({"ok": False, "error": "Falta el code"}, status=400)
    if waba_id and not waba_id.isdigit():   # va dentro de la URL de la API
        return JsonResponse({"ok": False, "error": "waba_id inválido"}, status=400)

    secreto = os.environ.get("META_APP_SECRET")
    if not secreto:
        return JsonResponse({"ok": False, "error": "Falta configurar META_APP_SECRET en el servidor"}, status=500)

    try:
        # 1) Canjear el code por un token (el code vence en ~30 segundos)
        token, tok, redirect_uri = _canjear_code(code, secreto, request)
        if not token:
            return JsonResponse({"ok": False, "paso": "canje", "respuesta": tok}, status=400)

        # 2) Cuentas a conectar: la que mandó el navegador o, si no llegó el evento de Meta, las que
        #    figuran en el token.
        wabas = [waba_id] if waba_id else _cuentas_del_token(token, secreto)
        if not wabas:
            return JsonResponse({
                "ok": False, "paso": "cuentas",
                "error": "El token no trae ninguna cuenta de WhatsApp Business: el registro de Meta no se completó.",
            }, status=400)

        # 3) Suscribir la app a cada cuenta y listar sus números.
        cuentas = [_conectar_cuenta(w, token) for w in wabas]
    except (requests.RequestException, ValueError):
        logger.exception("Falló la conexión con la API de Meta al conectar WhatsApp (waba %s)", waba_id or "?")
        return JsonResponse({"ok": False, "error": "No se pudo hablar con Meta. Probá de nuevo en un momento."}, status=502)

    # En coexistencia NO se llama a /register: el número ya está registrado.
    return JsonResponse({
        "ok": all(c["suscripcion_ok"] for c in cuentas),
        "origen_waba": "navegador" if waba_id else "token",
        "redirect_uri": redirect_uri or "(vacío)",
        "phone_number_id": phone_number_id,
        "cuentas": cuentas,
    })
