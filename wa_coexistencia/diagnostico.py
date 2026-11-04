"""Estado de la automatización de WhatsApp en palabras: qué está configurado, qué llegó de Meta y qué
conviene revisar primero. Se muestra arriba del registro de avisos en el admin (WhatsApp > Avisos de Meta).

No llama a Meta ni muestra secretos: solo dice si las variables están cargadas (sí/no)."""
import datetime
import os

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import ConfiguracionWhatsApp, ContactoWhatsApp, EventoWebhook

VARIABLES = (
    ('META_APP_SECRET', 'Secreto de la app de Meta (con él se comprueba que los avisos vienen de Meta)'),
    ('WHATSAPP_TOKEN', 'Token para enviar las respuestas'),
    ('WHATSAPP_VERIFY_TOKEN', 'Frase de verificación del webhook'),
)


def url_del_webhook():
    return settings.SITE_URL.rstrip('/') + reverse('wa_webhook')


def estado():
    ahora = timezone.now()
    hace_un_dia = ahora - datetime.timedelta(hours=24)
    config = ConfiguracionWhatsApp.obtener()
    eventos = EventoWebhook.objects.all()
    contactos = ContactoWhatsApp.objects.all()

    faltan = [nombre for nombre, _ in VARIABLES if not os.environ.get(nombre)]
    ultimo = eventos.first()
    verificado_alguna_vez = eventos.filter(resultado='verificacion_ok').exists()
    verificacion_rechazada = eventos.filter(resultado='verificacion_rechazada', creado__gte=hace_un_dia)
    firma_mala = eventos.filter(resultado='firma_invalida', creado__gte=hace_un_dia)
    recibidos = eventos.filter(resultado__in=('recibido', 'recibido_con_error'))
    con_mensajes = recibidos.filter(mensajes__gt=0)
    con_error = contactos.exclude(ultimo_error='')
    numero_distinto = eventos.filter(detalle__contains='NO es el configurado').first()

    chequeos = []
    for nombre, descripcion in VARIABLES:
        chequeos.append((descripcion, nombre not in faltan, f'{nombre} ' + ('cargada' if nombre not in faltan else 'FALTA en el servidor')))
    chequeos += [
        ('Respuestas automáticas', config.activa,
         'activas' if config.activa else 'APAGADAS (se encienden en WhatsApp > Respuestas automáticas)'),
        ('Mensajes por país cargados', config.por_pais.exists(), f'{config.por_pais.count()} país(es) con mensaje propio'),
        ('Meta verificó el webhook', verificado_alguna_vez,
         'sí' if verificado_alguna_vez else 'todavía no figura (solo se anota desde que existe este registro)'),
        ('Llegaron avisos de Meta', ultimo is not None,
         f'el último: {ultimo.creado:%d/%m/%Y %H:%M} ({ultimo.get_resultado_display()})' if ultimo else 'ninguno todavía'),
        ('Llegaron mensajes de personas', con_mensajes.exists(),
         f'{sum(e.mensajes for e in con_mensajes)} en total' if con_mensajes.exists() else 'ninguno todavía'),
        ('Avisos rechazados por firma (24 h)', not firma_mala.exists(), f'{firma_mala.count()}'),
        ('Contactos con error al responder', not con_error.exists(), f'{con_error.count()}'),
    ]

    pendientes = []
    if faltan:
        pendientes.append('Falta cargar en Render (Environment): ' + ', '.join(faltan)
                          + '. Después de cargarlas hay que hacer un Manual Deploy.')
    if ultimo is None:
        pendientes.append(
            'Desde que existe este registro, Meta NO llamó nunca a la dirección del webhook. Revisá en el panel de Meta '
            f'(app > WhatsApp > Configuración) que la URL sea exactamente {url_del_webhook()}, que figure como verificada, '
            'que esté suscrito el campo «messages» y que la app esté en modo Live. También que la cuenta de WhatsApp '
            'Business del número de LATAM esté suscrita a la app (lo hace la página de conexión).'
        )
    if verificacion_rechazada.exists() and not verificado_alguna_vez:
        pendientes.append(
            'Meta intentó verificar el webhook pero la frase no coincide: la «Verify token» del panel de Meta tiene que '
            'ser idéntica a WHATSAPP_VERIFY_TOKEN. ' + (verificacion_rechazada.first().detalle or '')
        )
    if firma_mala.exists():
        pendientes.append(
            f'Llegan avisos pero con la firma mala ({firma_mala.count()} en las últimas 24 h). '
            f'Último motivo: {firma_mala.first().detalle}. META_APP_SECRET tiene que ser el «Secreto de la aplicación» de '
            'la MISMA app de Meta a la que pertenece el número de LATAM (no el de otra app, como la de Argentina).'
        )
    if recibidos.exists() and not con_mensajes.exists() and not firma_mala.exists():
        pendientes.append(
            'Meta llama, pero solo con avisos de estado: ningún mensaje de persona. Revisá que esté suscrito el campo '
            '«messages» del webhook y probá escribiendo al número desde otro celular.'
        )
    if con_mensajes.exists() and not config.activa:
        pendientes.append('Los mensajes SÍ llegan, pero las respuestas automáticas están apagadas: activalas en '
                          'WhatsApp > Respuestas automáticas.')
    if con_error.exists():
        pendientes.append('Meta rechazó respuestas. Último error: ' + (con_error.order_by('-ultimo_mensaje').first().ultimo_error))
    if numero_distinto:
        pendientes.append('Llegaron mensajes a un número que no es el de LATAM (' + numero_distinto.detalle + ').')
    if not pendientes:
        pendientes.append('Todo en orden: llegan los avisos y no hay nada por corregir.')

    return {'chequeos': chequeos, 'pendientes': pendientes, 'url_webhook': url_del_webhook()}
