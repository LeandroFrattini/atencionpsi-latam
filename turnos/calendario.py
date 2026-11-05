"""Turnos como eventos de calendario (iCalendar / .ics): el archivo que se adjunta a los mails de
reserva, el calendario personal que el profesional suscribe en Google Calendar y el link de "Agregar
a Google Calendar".

Sobre la hora: el sistema guarda la hora de cada turno como "hora de pared" (la que el profesional
cargó en su disponibilidad y el paciente eligió) interpretada en la zona horaria del servidor
(settings.TIME_ZONE). Para que el evento caiga en el momento correcto en el calendario de quien lo
abre, esa hora de pared se vuelve a interpretar en la zona del PAÍS del profesional y recién ahí se
pasa a UTC. Así un turno "10:00" de Lima queda a las 10:00 de Lima en cualquier calendario.
"""
import datetime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

ZONAS_POR_PAIS = {
    'AR': 'America/Argentina/Buenos_Aires',
    'CL': 'America/Santiago',
    'CO': 'America/Bogota',
    'EC': 'America/Guayaquil',
    'MX': 'America/Mexico_City',
    'PE': 'America/Lima',
    'UY': 'America/Montevideo',
}

FORMATO_UTC = '%Y%m%dT%H%M%SZ'


def zona_del_pais(pais):
    nombre = ZONAS_POR_PAIS.get((getattr(pais, 'codigo_iso', '') or '').upper(), settings.TIME_ZONE)
    return ZoneInfo(nombre)


def inicio_y_fin_utc(turno):
    """(inicio, fin) del turno en UTC, según la zona horaria del país del profesional."""
    hora_de_pared = timezone.localtime(turno.fecha_hora).replace(tzinfo=None)
    inicio = hora_de_pared.replace(tzinfo=zona_del_pais(turno.psicologo.pais)).astimezone(datetime.timezone.utc)
    return inicio, inicio + datetime.timedelta(minutes=turno.tipo_sesion.duracion_min)


def _escapar(texto):
    """Escapado de valores de texto de iCalendar (RFC 5545 3.3.11)."""
    return (str(texto).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n'))


def _plegar(linea):
    """Las líneas de iCalendar no pasan de 75 bytes: se parten y la continuación empieza con un espacio."""
    datos = linea.encode('utf-8')
    if len(datos) <= 75:
        return linea
    partes, actual = [], b''
    limite = 75
    for caracter in linea:
        codificado = caracter.encode('utf-8')
        if len(actual) + len(codificado) > limite:
            partes.append(actual.decode('utf-8'))
            actual, limite = b'', 74       # la línea de continuación arranca con un espacio
        actual += codificado
    partes.append(actual.decode('utf-8'))
    return '\r\n '.join(partes)


def _titulo(turno, para_profesional):
    if para_profesional:
        return f'Sesión con {turno.nombre_completo}'
    return f'Sesión con {turno.psicologo.nombre}'


def _lugar(turno):
    return 'Online' if turno.modalidad == 'online' else 'Presencial (consultá la dirección con el profesional)'


def _descripcion(turno, para_profesional, con_motivo):
    lineas = [f'Tipo de sesión: {turno.tipo_sesion.nombre}', f'Modalidad: {turno.get_modalidad_display()}']
    if para_profesional:
        lineas.append(f'Paciente: {turno.nombre_completo}')
        if turno.telefono:
            lineas.append(f'Teléfono: {turno.telefono}')
        if turno.email:
            lineas.append(f'Email: {turno.email}')
        if con_motivo and turno.motivo_consulta:
            lineas.append(f'Motivo de consulta: {turno.motivo_consulta}')
    else:
        if turno.psicologo.whatsapp_limpio():
            lineas.append(f'WhatsApp del profesional: +{turno.psicologo.whatsapp_limpio()}')
    lineas.append('Reservado en Atención Psi.')
    return '\n'.join(lineas)


def _evento(turno, para_profesional, con_motivo, ahora):
    inicio, fin = inicio_y_fin_utc(turno)
    cancelado = turno.estado == 'cancelado'
    return [
        'BEGIN:VEVENT',
        f'UID:turno-{turno.pk}@atencionpsi',
        f'DTSTAMP:{ahora:{FORMATO_UTC}}',
        f'DTSTART:{inicio:{FORMATO_UTC}}',
        f'DTEND:{fin:{FORMATO_UTC}}',
        f'SUMMARY:{_escapar(_titulo(turno, para_profesional))}',
        f'DESCRIPTION:{_escapar(_descripcion(turno, para_profesional, con_motivo))}',
        f'LOCATION:{_escapar(_lugar(turno))}',
        f'STATUS:{"CANCELLED" if cancelado else "CONFIRMED"}',
        'END:VEVENT',
    ]


def generar_ics(turnos, nombre_calendario, para_profesional=True, con_motivo=False, metodo='PUBLISH'):
    """Texto de un archivo .ics con esos turnos.

    `con_motivo`: incluye el motivo de consulta en la descripción. Es un dato sensible y el
    calendario suscripto vive en los servidores de Google, así que por defecto NO va.
    """
    ahora = timezone.now().astimezone(datetime.timezone.utc)
    lineas = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Atencion Psi//Turnos//ES',
        'CALSCALE:GREGORIAN',
        f'METHOD:{metodo}',
        f'X-WR-CALNAME:{_escapar(nombre_calendario)}',
    ]
    for turno in turnos:
        lineas.extend(_evento(turno, para_profesional, con_motivo, ahora))
    lineas.append('END:VCALENDAR')
    return '\r\n'.join(_plegar(linea) for linea in lineas) + '\r\n'


def link_google_calendar(turno, para_profesional=False):
    """Link que abre Google Calendar con el evento listo para guardar."""
    inicio, fin = inicio_y_fin_utc(turno)
    consulta = urlencode({
        'action': 'TEMPLATE',
        'text': _titulo(turno, para_profesional),
        'dates': f'{inicio:{FORMATO_UTC}}/{fin:{FORMATO_UTC}}',
        'details': _descripcion(turno, para_profesional, con_motivo=False),
        'location': _lugar(turno),
    }, quote_via=quote)
    return f'https://calendar.google.com/calendar/render?{consulta}'
