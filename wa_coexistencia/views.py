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
# Se muestra en la página y en las respuestas: sirve para saber qué versión está desplegada.
VERSION = 9
# Identificador del número de teléfono de LATAM (aparece en el Administrador de WhatsApp). Solo se usa para
# comprobar si el token llega a ver el número cuando no encuentra la cuenta.
PHONE_NUMBER_ID = "1228482323672734"
CAMPOS_NUMERO_DETALLE = "id,verified_name,status,platform_type,is_on_biz_app,code_verification_status,quality_rating"


@staff_member_required
@ensure_csrf_cookie
def coexistencia(request):
    # ensure_csrf_cookie: el botón hace un fetch con la cookie csrftoken y la página no tiene formulario.
    resp = render(request, "wa_coexistencia/coexistencia.html", {
        "app_id": APP_ID,
        "config_id": CONFIG_ID,
        "version": VERSION,
    })
    # Django manda por defecto "same-origin", que corta la comunicación con la ventana emergente de Meta
    # y el registro se cuelga. Solo para esta página: "same-origin-allow-popups".
    resp["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return resp


def _canjear_code(code, secreto, request):
    """Canjea el code por un token. Un code que sale del SDK de JavaScript de Facebook se canjea con
    redirect_uri VACÍO, pero Meta a veces pide otro: se prueban las alternativas razonables mientras el
    error sea de redirect_uri (36008) o de dominio (191). Devuelve (token, última_respuesta, redirect_uri_usado,
    intentos), donde `intentos` resume qué respondió Meta en cada prueba (sin datos sensibles)."""
    origen = f"{request.scheme}://{request.get_host()}"
    candidatas = [
        "",
        request.build_absolute_uri(request.path.replace("callback/", "")),
        origen + "/",
        origen,
        "https://www.facebook.com/connect/login_success.html",
    ]
    respuesta, intentos = {}, []
    for redirect_uri in candidatas:
        respuesta = requests.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": APP_ID,
            "client_secret": secreto,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=20).json()
        if respuesta.get("access_token"):
            intentos.append({"redirect_uri": redirect_uri or "(vacío)", "resultado": "ok"})
            return respuesta["access_token"], respuesta, redirect_uri, intentos
        error = respuesta.get("error") or {}
        intentos.append({
            "redirect_uri": redirect_uri or "(vacío)",
            "codigo": error.get("code"), "subcodigo": error.get("error_subcode"), "mensaje": error.get("message"),
        })
        if error.get("error_subcode") != 36008 and error.get("code") != 191:
            break   # otro error (code vencido, secreto mal...): probar otro redirect_uri no sirve
    return None, respuesta, None, intentos


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


def _diagnostico_del_token(token, secreto):
    """Qué sabe Meta de este token (permisos, activos, vencimiento) y si llega a ver el número de LATAM.
    Para entender por qué no aparece la cuenta. No incluye el token ni el secreto."""
    cabecera = {"Authorization": f"Bearer {token}"}
    d = requests.get(f"{GRAPH}/debug_token", params={
        "input_token": token, "access_token": f"{APP_ID}|{secreto}",
    }, timeout=20).json()
    datos = d.get("data") or {}
    numero = requests.get(f"{GRAPH}/{PHONE_NUMBER_ID}", headers=cabecera,
                          params={"fields": "id,verified_name,status"}, timeout=20)
    return {
        "debug_token": {
            "error": d.get("error"),
            "tipo": datos.get("type"), "valido": datos.get("is_valid"), "app_id": datos.get("app_id"),
            "vence": datos.get("expires_at"), "permisos": datos.get("scopes"),
            "activos_por_permiso": datos.get("granular_scopes"),
        },
        "ve_el_numero": {"http": numero.status_code, "respuesta": numero.json()},
    }


def _ids(cuerpo):
    """IDs numéricos de una respuesta de Meta con forma {"data": [{"id": ...}]}."""
    datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    if not isinstance(datos, list):
        return []
    return [str(x["id"]) for x in datos if isinstance(x, dict) and str(x.get("id", "")).isdigit()]


def _waba_del_numero(token, secreto):
    """Busca la cuenta de WhatsApp Business que contiene el número de LATAM. Los tokens de usuario del
    sistema no traen la lista de cuentas, así que se prueban varias formas de llegar a ella (el propio
    número, las cuentas asignadas al usuario, los negocios del usuario y de la app). Solo se devuelve la que
    tiene PHONE_NUMBER_ID: nunca otra, como la de Argentina.
    Devuelve ([waba_id] o [], pasos) con lo que respondió Meta en cada paso, para diagnosticar."""
    cabecera = {"Authorization": f"Bearer {token}"}
    pasos = []

    def sondear(nombre, url, params, con_token_de_app=False):
        if con_token_de_app:
            params = {**params, "access_token": f"{APP_ID}|{secreto}"}
        r = requests.get(url, headers={} if con_token_de_app else cabecera, params=params, timeout=20)
        cuerpo = r.json()
        pasos.append({"paso": nombre, "http": r.status_code, "respuesta": cuerpo})
        return cuerpo

    # 1) El propio número puede decir a qué cuenta pertenece (no hace falta verificarla: sale de él).
    cuerpo = sondear("numero", f"{GRAPH}/{PHONE_NUMBER_ID}", {"fields": "whatsapp_business_account"})
    directa = str((cuerpo.get("whatsapp_business_account") or {}).get("id") or "")
    if directa.isdigit():
        return [directa], pasos

    # 2) Cuentas asignadas al usuario del sistema.
    candidatas = _ids(sondear("asignadas", f"{GRAPH}/me/assigned_whatsapp_business_accounts", {"fields": "id,name"}))

    # 3) Negocios del usuario y de la app, y las cuentas de cada uno.
    negocios = _ids(sondear("negocios_del_usuario", f"{GRAPH}/me/businesses", {"fields": "id,name"}))
    app = sondear("negocio_de_la_app", f"{GRAPH}/{APP_ID}", {"fields": "id,business"}, con_token_de_app=True)
    negocio_app = str((app.get("business") or {}).get("id") or "")
    if negocio_app.isdigit() and negocio_app not in negocios:
        negocios.append(negocio_app)
    for negocio in negocios:
        for relacion in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
            candidatas += _ids(sondear(f"{relacion}_de_{negocio}", f"{GRAPH}/{negocio}/{relacion}",
                                       {"fields": "id,name", "limit": 50}))

    # Se verifica cada candidata: solo vale la que tiene el número de LATAM.
    vistas = []
    for waba in candidatas:
        if waba in vistas:
            continue
        vistas.append(waba)
        r = requests.get(f"{GRAPH}/{waba}/phone_numbers", headers=cabecera, params={"fields": "id"}, timeout=20)
        if r.ok and PHONE_NUMBER_ID in _ids(r.json()):
            return [waba], pasos
    return [], pasos


def _wabas_configuradas():
    """IDs de cuenta fijados en WHATSAPP_WABA_ID (separados por coma), o [] si no está. Con esto no hace
    falta buscar y se evita tocar cualquier otra cuenta a la que el token tenga acceso."""
    ids = [w.strip() for w in os.environ.get("WHATSAPP_WABA_ID", "").split(",") if w.strip()]
    return [w for w in ids if w.isdigit()]


def _conectar_cuenta(waba_id, token):
    """Suscribe la app a la cuenta (para recibir webhooks) y lista sus números. Sin datos sensibles."""
    cabecera = {"Authorization": f"Bearer {token}"}
    s = requests.post(f"{GRAPH}/{waba_id}/subscribed_apps", headers=cabecera, timeout=20)
    # Primero con el detalle del estado (tipo de plataforma, si sigue en la app del celular...). Si Meta
    # rechaza algún campo, se reintenta con los básicos para no perder la lista.
    for campos in (CAMPOS_NUMERO_DETALLE, "id,verified_name,status"):
        n = requests.get(f"{GRAPH}/{waba_id}/phone_numbers", headers=cabecera, params={"fields": campos}, timeout=20)
        if n.ok:
            break
    numeros = n.json().get("data") if n.ok else None
    return {
        "waba_id": waba_id,
        "suscripcion_ok": s.ok,
        "suscripcion": s.json(),
        "numeros": numeros,
    }


@staff_member_required
@require_POST
def coexistencia_con_token(request):
    """Camino alternativo, sin el code de Meta: usa un token de usuario del sistema del Business Manager
    (variable de entorno WHATSAPP_TOKEN, nunca en el código). Busca las cuentas de WhatsApp Business a las que
    ese token tiene acceso, suscribe la app a cada una y lista sus números. No devuelve el token."""
    token = os.environ.get("WHATSAPP_TOKEN")
    secreto = os.environ.get("META_APP_SECRET")
    if not token or not secreto:
        faltan = [n for n, v in (("WHATSAPP_TOKEN", token), ("META_APP_SECRET", secreto)) if not v]
        return JsonResponse({"ok": False, "version": VERSION,
                             "error": "Falta configurar en el servidor: " + ", ".join(faltan)}, status=500)
    try:
        busqueda = []
        origen = "token del sistema"
        wabas = _wabas_configuradas() or _cuentas_del_token(token, secreto)
        if not wabas:
            wabas, busqueda = _waba_del_numero(token, secreto)
            origen = "cuenta buscada por el número de LATAM"
        if not wabas:
            return JsonResponse({
                "ok": False, "version": VERSION, "paso": "cuentas",
                "error": "El token no lista ninguna cuenta de WhatsApp Business. Revisá que el usuario del sistema "
                         "tenga la cuenta asignada (control total) y la app, y que el token se haya generado con los "
                         "permisos whatsapp_business_management y whatsapp_business_messaging. Si ya está así, "
                         "cargá el ID de la cuenta en la variable WHATSAPP_WABA_ID.",
                "diagnostico": {**_diagnostico_del_token(token, secreto), "busqueda_por_negocio": busqueda},
            }, status=400)
        cuentas = [_conectar_cuenta(w, token) for w in wabas]
    except (requests.RequestException, ValueError):
        logger.exception("Falló la conexión con la API de Meta al usar el token del sistema")
        return JsonResponse({"ok": False, "error": "No se pudo hablar con Meta. Probá de nuevo en un momento."}, status=502)
    return JsonResponse({
        "ok": all(c["suscripcion_ok"] for c in cuentas),
        "version": VERSION,
        "origen_waba": origen,
        "cuentas": cuentas,
    })


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
        token, tok, redirect_uri, intentos = _canjear_code(code, secreto, request)
        if not token:
            return JsonResponse({"ok": False, "version": VERSION, "paso": "canje", "intentos": intentos}, status=400)

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
        "version": VERSION,
        "origen_waba": "navegador" if waba_id else "token",
        "redirect_uri": redirect_uri or "(vacío)",
        "phone_number_id": phone_number_id,
        "cuentas": cuentas,
    })
