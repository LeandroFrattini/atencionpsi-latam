"""Receptor de los mensajes de WhatsApp (webhook de Meta) y respuestas automáticas.

Cuando alguien escribe al número de Atención Psi LATAM, Meta avisa acá. Si las respuestas están activas y a esa
persona no se le respondió en las últimas horas, se le mandan dos mensajes: una bienvenida y otro según su país
(detectado por el código del teléfono), con un archivo opcional.

Variables de entorno (en Render, nunca en el código): META_APP_SECRET (firma de Meta), WHATSAPP_TOKEN (para
enviar) y WHATSAPP_VERIFY_TOKEN (la frase que se carga también en el panel de Meta al configurar el webhook).
"""
import datetime
import hashlib
import hmac
import json
import logging
import os

import requests
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from directorio.models import Pais

from .models import ConfiguracionWhatsApp, ContactoWhatsApp, EventoWebhook, MensajeRecibido
from .views import GRAPH, PHONE_NUMBER_ID

logger = logging.getLogger(__name__)

EXTENSIONES_IMAGEN = ('.jpg', '.jpeg', '.png')
LIMITE_PIE = 1000   # WhatsApp admite hasta 1024 caracteres en el pie de un archivo
TIPOS_QUE_NO_ACTIVAN = {'reaction'}   # una reacción a un mensaje no es alguien que escribe


def _motivo_firma_invalida(cuerpo, cabecera):
    """None si la firma es válida; si no, el motivo en palabras (se anota en el registro de avisos)."""
    secreto = os.environ.get('META_APP_SECRET', '')
    if not secreto:
        return 'META_APP_SECRET no está configurado en el servidor'
    if not cabecera:
        return 'el aviso no trae la firma de Meta (X-Hub-Signature-256): no parece venir de Meta'
    if not cabecera.startswith('sha256='):
        return 'la firma tiene un formato desconocido'
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperada, cabecera[len('sha256='):]):
        return 'la firma no coincide: META_APP_SECRET no es el secreto de la app de Meta que manda los avisos'
    return None


def _firma_valida(cuerpo, cabecera):
    return _motivo_firma_invalida(cuerpo, cabecera) is None


MAX_EVENTOS = 500   # el registro de avisos guarda los últimos


def _anotar(request, resultado, detalle='', mensajes=0, numero_id=''):
    """Anota la llamada en el registro de avisos. Es solo para diagnosticar: si falla, nunca rompe la respuesta."""
    try:
        EventoWebhook.objects.create(
            metodo=request.method, resultado=resultado, detalle=detalle[:300], mensajes=mensajes,
            numero_id=str(numero_id)[:40], agente=request.headers.get('User-Agent', '')[:120],
        )
        if EventoWebhook.objects.count() > MAX_EVENTOS + 100:
            viejos = list(EventoWebhook.objects.order_by('-creado').values_list('pk', flat=True)[MAX_EVENTOS:])
            EventoWebhook.objects.filter(pk__in=viejos).delete()
    except Exception:
        logger.exception('No se pudo anotar el aviso del webhook de WhatsApp')


def pais_del_telefono(telefono):
    """El país cuyo código de teléfono (el más largo que coincida) abre este número, o None."""
    mejor = None
    for pais in Pais.objects.exclude(codigo_telefono=''):
        codigo = pais.codigo_telefono.lstrip('+')
        if codigo and telefono.startswith(codigo) and (mejor is None or len(codigo) > len(mejor[0])):
            mejor = (codigo, pais)
    return mejor[1] if mejor else None


def _enviar(token, telefono, contenido):
    """Manda un mensaje por la API. Devuelve (True, '') si Meta lo aceptó, o (False, motivo)."""
    r = requests.post(
        f'{GRAPH}/{PHONE_NUMBER_ID}/messages',
        headers={'Authorization': f'Bearer {token}'},
        json={'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': telefono, **contenido},
        timeout=15,
    )
    if not r.ok:
        logger.error('Meta rechazó un mensaje automático (%s): %s', r.status_code, r.text[:300])
        return False, f'{r.status_code}: {r.text}'[:300]
    return True, ''


def _contenido_con_archivo(request, respuesta):
    """Mensaje de WhatsApp para una RespuestaPais: texto solo, o archivo con el texto de pie."""
    texto = respuesta.texto.strip()
    if not respuesta.archivo:
        return [{'type': 'text', 'text': {'body': texto}}]
    url = respuesta.archivo.url
    if not url.startswith('http'):
        url = request.build_absolute_uri(url)
    nombre = os.path.basename(respuesta.archivo.name)
    es_imagen = nombre.lower().endswith(EXTENSIONES_IMAGEN)
    clave = 'image' if es_imagen else 'document'
    archivo = {'link': url}
    if not es_imagen:
        archivo['filename'] = nombre
    if len(texto) <= LIMITE_PIE:
        archivo['caption'] = texto
        return [{'type': clave, clave: archivo}]
    return [{'type': clave, clave: archivo}, {'type': 'text', 'text': {'body': texto}}]


def _responder(request, contacto, ahora):
    telefono = contacto.telefono
    config = ConfiguracionWhatsApp.obtener()
    if not config.activa:
        return
    token = os.environ.get('WHATSAPP_TOKEN')
    if not token:
        logger.error('No se puede responder por WhatsApp: falta WHATSAPP_TOKEN')
        contacto.ultimo_error = 'Falta configurar WHATSAPP_TOKEN en el servidor'
        contacto.save(update_fields=['ultimo_error'])
        return
    if contacto.ultima_respuesta and ahora - contacto.ultima_respuesta < datetime.timedelta(hours=config.horas_entre_respuestas):
        return

    mensajes = [{'type': 'text', 'text': {'body': config.texto_bienvenida.strip()}}]
    pais = pais_del_telefono(telefono)
    por_pais = config.por_pais.filter(pais=pais).first() if pais else None
    if por_pais:
        mensajes += _contenido_con_archivo(request, por_pais)
    elif config.texto_otro_pais.strip():
        mensajes.append({'type': 'text', 'text': {'body': config.texto_otro_pais.strip()}})

    # Se marca al contacto apenas se manda la bienvenida: si algo falla después no se le repite todo.
    contacto.ultimo_error = ''
    for i, contenido in enumerate(mensajes):
        ok, motivo = _enviar(token, telefono, contenido)
        if not ok:
            contacto.ultimo_error = motivo
            break
        if i == 0:
            contacto.ultima_respuesta = ahora
    contacto.save(update_fields=['ultima_respuesta', 'ultimo_error'])


@csrf_exempt
def recibir(request):
    if request.method == 'GET':
        # Verificación de Meta al configurar el webhook: devuelve el desafío si la frase coincide.
        esperado = os.environ.get('WHATSAPP_VERIFY_TOKEN', '')
        if esperado and request.GET.get('hub.mode') == 'subscribe' and \
                hmac.compare_digest(request.GET.get('hub.verify_token', ''), esperado):
            _anotar(request, 'verificacion_ok', 'Meta verificó el webhook correctamente')
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        if not esperado:
            motivo = 'WHATSAPP_VERIFY_TOKEN no está configurado en el servidor'
        elif request.GET.get('hub.mode') != 'subscribe':
            motivo = 'pedido sin hub.mode=subscribe (¿alguien abrió la dirección a mano?)'
        else:
            motivo = 'la frase de verificación no coincide con la que está cargada en el panel de Meta'
        _anotar(request, 'verificacion_rechazada', motivo)
        return HttpResponseForbidden()
    if request.method != 'POST':
        return HttpResponse(status=405)

    motivo = _motivo_firma_invalida(request.body, request.headers.get('X-Hub-Signature-256', ''))
    if motivo:
        _anotar(request, 'firma_invalida', motivo)
        return HttpResponseForbidden()
    try:
        datos = json.loads(request.body)
    except ValueError:
        _anotar(request, 'json_invalido', 'el cuerpo del aviso no es JSON')
        return HttpResponse(status=400)

    nuevos, fallos, numeros = 0, 0, set()
    for entrada in datos.get('entry') or []:
        for cambio in entrada.get('changes') or []:
            valor = cambio.get('value') or {}
            numero = (valor.get('metadata') or {}).get('phone_number_id')
            if numero:
                numeros.add(str(numero))
            for mensaje in valor.get('messages') or []:   # los "statuses" (entregado, leído) no traen "messages"
                nuevos += 1
                try:
                    _atender(request, mensaje)
                except Exception:
                    fallos += 1
                    logger.exception('Falló la respuesta automática de WhatsApp')

    if fallos:
        resultado, detalle = 'recibido_con_error', f'falló la respuesta a {fallos} de {nuevos} mensaje(s): mirá los logs'
    elif not nuevos:
        resultado, detalle = 'recibido', 'solo avisos de estado (entregado/leído) o de otro tipo, ningún mensaje nuevo'
    elif numeros and PHONE_NUMBER_ID not in numeros:
        resultado = 'recibido'
        detalle = (f'{nuevos} mensaje(s) llegaron al número {", ".join(sorted(numeros))}, que NO es el configurado '
                   f'({PHONE_NUMBER_ID}); se respondió igual desde el configurado')
    else:
        resultado, detalle = 'recibido', f'{nuevos} mensaje(s) nuevo(s)'
    _anotar(request, resultado, detalle, mensajes=nuevos, numero_id=', '.join(sorted(numeros)))
    # Siempre 200 si la firma es válida: si no, Meta reintenta y se acumulan avisos repetidos.
    return HttpResponse(status=200)


def _atender(request, mensaje):
    telefono = str(mensaje.get('from') or '')
    wa_id = str(mensaje.get('id') or '')
    if not telefono.isdigit() or not wa_id or mensaje.get('type') in TIPOS_QUE_NO_ACTIVAN:
        return
    _, nuevo = MensajeRecibido.objects.get_or_create(wa_id=wa_id)
    if not nuevo:
        return   # reintento de Meta: ya se atendió
    ahora = timezone.now()
    contacto, _ = ContactoWhatsApp.objects.get_or_create(telefono=telefono)
    contacto.ultimo_mensaje = ahora   # queda anotado aunque las respuestas estén apagadas: sirve para ver que llegan
    contacto.save(update_fields=['ultimo_mensaje'])
    _responder(request, contacto, ahora)
