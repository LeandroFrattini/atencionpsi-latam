"""
Cálculo de horarios reservables a partir de la plantilla semanal
(DisponibilidadSemanal) de cada psicólogo, descontando los días que no
atiende (DiaNoAtiende) y los turnos ya ocupados ese día puntual.

Adaptado de la versión ya probada en atencionpsi.com.ar -- la diferencia
acá es que la duración del turno depende del TipoSesion elegido por el
paciente (Individual/Pareja/etc.), no de un único valor fijo por psicólogo.
"""
import datetime

from django.utils import timezone

from .models import DiaNoAtiende, Turno

HORIZONTE_SEMANAS = 2  # esta semana + la próxima, nada más allá

NOMBRES_DIA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
NOMBRES_MES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


def fecha_larga(fecha):
    return f'{NOMBRES_DIA[fecha.weekday()]} {fecha.day} de {NOMBRES_MES[fecha.month - 1]}'


def fechas_horizonte(hoy=None):
    """Lunes a sábado de esta semana y de la próxima (nunca domingo)."""
    hoy = hoy or timezone.localdate()
    lunes = hoy - datetime.timedelta(days=hoy.weekday())
    return [
        lunes + datetime.timedelta(weeks=semana, days=dia)
        for semana in range(HORIZONTE_SEMANAS)
        for dia in range(6)
    ]


def esta_en_dia_no_atiende(psico, fecha):
    return DiaNoAtiende.objects.filter(
        psicologo=psico, fecha_desde__lte=fecha, fecha_hasta__gte=fecha
    ).exists()


def _horas_ocupadas(psico, fecha):
    desde = fecha - datetime.timedelta(days=1)
    hasta = fecha + datetime.timedelta(days=1)
    turnos = Turno.objects.filter(
        psicologo=psico, fecha_hora__date__range=(desde, hasta)
    ).exclude(estado='cancelado')
    ocupadas = set()
    for turno in turnos:
        local = timezone.localtime(turno.fecha_hora)
        if local.date() == fecha:
            ocupadas.add(local.time().replace(second=0, microsecond=0))
    return ocupadas


def slots_para_fecha(psico, fecha, duracion_min):
    """
    Lista de horarios de ese día partidos según `duracion_min` (la del
    TipoSesion elegido): [{'hora': time, 'tomado': bool}, ...]. Vacía si el
    día ya pasó, cae en un período de "no atiende", o es domingo. Si el día
    es hoy, también se descartan los horarios que ya pasaron.
    """
    hoy = timezone.localdate()
    if fecha < hoy or fecha.weekday() == 6 or esta_en_dia_no_atiende(psico, fecha):
        return []

    paso = datetime.timedelta(minutes=duracion_min)
    ocupadas = _horas_ocupadas(psico, fecha)
    ahora = timezone.localtime().time() if fecha == hoy else None

    slots = []
    bloques = psico.disponibilidad_semanal.filter(dia_semana=fecha.weekday()).order_by('hora_desde')
    for bloque in bloques:
        cursor = datetime.datetime.combine(fecha, bloque.hora_desde)
        fin = datetime.datetime.combine(fecha, bloque.hora_hasta)
        while cursor + paso <= fin:
            hora = cursor.time()
            if ahora is None or hora > ahora:
                slots.append({'hora': hora, 'tomado': hora in ocupadas})
            cursor += paso
    slots.sort(key=lambda s: s['hora'])
    return slots


def slot_disponible(psico, fecha, hora, duracion_min):
    """Re-chequeo puntual (usado al confirmar) de que ese horario sigue libre."""
    for slot in slots_para_fecha(psico, fecha, duracion_min):
        if slot['hora'] == hora:
            return not slot['tomado']
    return False
