import datetime

from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from directorio.models import Pais, Psicologo

from .disponibilidad import fecha_larga, fechas_horizonte, slot_disponible, slots_para_fecha
from .forms import ReservaDatosForm
from .models import Paciente, TipoSesion, Turno

PASOS = [
    ('tipo', 'Tipo'), ('modalidad', 'Modalidad'), ('horario', 'Horario'),
    ('datos', 'Datos'), ('confirmar', 'Confirmar'),
]


def _psicologo_publicado(pais_slug, pk):
    pais = get_object_or_404(Pais, slug=pais_slug, activo=True)
    psicologo = get_object_or_404(Psicologo, pk=pk, pais=pais)
    if not psicologo.publicado:
        from django.http import Http404
        raise Http404('Perfil no disponible')
    return pais, psicologo


def _session_key(psicologo):
    return f'reserva_{psicologo.pk}'


def _get_reserva(request, psicologo):
    return request.session.get(_session_key(psicologo), {})


def _set_reserva(request, psicologo, **cambios):
    datos = _get_reserva(request, psicologo)
    datos.update(cambios)
    request.session[_session_key(psicologo)] = datos
    return datos


def _contexto_pasos(paso_actual):
    indice_actual = next(i for i, (key, _) in enumerate(PASOS) if key == paso_actual)
    pasos = [
        {'numero': i + 1, 'nombre': nombre, 'key': key,
         'completado': i < indice_actual, 'actual': i == indice_actual}
        for i, (key, nombre) in enumerate(PASOS)
    ]
    return {
        'pasos': pasos,
        'paso_actual': pasos[indice_actual],
        'porcentaje': round((indice_actual + 1) / len(PASOS) * 100),
    }


def _url_paso(paso, pais_slug, pk):
    return reverse(f'reserva_{paso}', args=[pais_slug, pk])


def paso_tipo(request, pais_slug, pk):
    pais, psicologo = _psicologo_publicado(pais_slug, pk)
    tipos = psicologo.tipos_sesion.all()

    if request.method == 'POST':
        tipo_id = request.POST.get('tipo_sesion')
        if tipos.filter(pk=tipo_id).exists():
            _set_reserva(request, psicologo, tipo_sesion_id=int(tipo_id))
            return redirect('reserva_modalidad', pais_slug, pk)
        messages.error(request, 'Elegí un tipo de sesión para continuar.')

    return render(request, 'turnos/paso_tipo.html', {
        'pais': pais, 'p': psicologo, 'tipos': tipos,
        **_contexto_pasos('tipo'), 'reserva': _get_reserva(request, psicologo),
    })


def paso_modalidad(request, pais_slug, pk):
    pais, psicologo = _psicologo_publicado(pais_slug, pk)
    if 'tipo_sesion_id' not in _get_reserva(request, psicologo):
        return redirect('reserva_tipo', pais_slug, pk)

    # Si el psicólogo solo atiende de una forma, no hace falta preguntar.
    if psicologo.modalidad != 'ambas':
        _set_reserva(request, psicologo, modalidad=psicologo.modalidad)
        return redirect('reserva_horario', pais_slug, pk)

    if request.method == 'POST':
        modalidad = request.POST.get('modalidad')
        if modalidad in ('online', 'presencial'):
            _set_reserva(request, psicologo, modalidad=modalidad)
            return redirect('reserva_horario', pais_slug, pk)
        messages.error(request, 'Elegí una modalidad para continuar.')

    return render(request, 'turnos/paso_modalidad.html', {
        'pais': pais, 'p': psicologo,
        **_contexto_pasos('modalidad'), 'reserva': _get_reserva(request, psicologo),
    })


NOMBRES_MES_CAP = [n.capitalize() for n in [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]]


def _grilla_mes(mes_ref, psicologo, tipo_sesion):
    """Semanas (lunes a domingo) del mes de `mes_ref`, cada día clasificado
    como disponible / no-disponible / fuera-de-rango (más allá de las 2
    semanas que se pueden reservar) / fuera-de-mes (relleno del mes
    anterior/siguiente, no clickeable)."""
    horizonte = set(fechas_horizonte())
    primer_dia = mes_ref.replace(day=1)
    inicio_grilla = primer_dia - datetime.timedelta(days=primer_dia.weekday())
    if mes_ref.month == 12:
        siguiente_mes = mes_ref.replace(year=mes_ref.year + 1, month=1, day=1)
    else:
        siguiente_mes = mes_ref.replace(month=mes_ref.month + 1, day=1)
    ultimo_dia = siguiente_mes - datetime.timedelta(days=1)
    fin_grilla = ultimo_dia + datetime.timedelta(days=(6 - ultimo_dia.weekday()))

    semanas, semana = [], []
    cursor = inicio_grilla
    while cursor <= fin_grilla:
        en_mes = cursor.month == mes_ref.month
        if not en_mes:
            estado = 'fuera-de-mes'
        elif cursor not in horizonte:
            estado = 'fuera-de-rango'
        elif slots_para_fecha(psicologo, cursor, tipo_sesion.duracion_min):
            estado = 'disponible'
        else:
            estado = 'no-disponible'
        semana.append({'fecha': cursor, 'en_mes': en_mes, 'estado': estado})
        if cursor.weekday() == 6:
            semanas.append(semana)
            semana = []
        cursor += datetime.timedelta(days=1)
    return semanas


def paso_horario(request, pais_slug, pk):
    pais, psicologo = _psicologo_publicado(pais_slug, pk)
    reserva = _get_reserva(request, psicologo)
    if 'modalidad' not in reserva:
        return redirect('reserva_modalidad', pais_slug, pk)

    tipo_sesion = get_object_or_404(TipoSesion, pk=reserva['tipo_sesion_id'], psicologo=psicologo)
    fechas = fechas_horizonte()

    mes_str = request.GET.get('mes')
    try:
        mes_ref = datetime.date.fromisoformat(f'{mes_str}-01') if mes_str else timezone.localdate().replace(day=1)
    except ValueError:
        mes_ref = timezone.localdate().replace(day=1)

    fecha_elegida_str = request.GET.get('fecha')
    fecha_elegida = None
    if fecha_elegida_str:
        try:
            candidata = datetime.date.fromisoformat(fecha_elegida_str)
            if candidata in fechas:
                fecha_elegida = candidata
        except ValueError:
            pass
    if fecha_elegida is None:
        fecha_elegida = next((f for f in fechas if f >= timezone.localdate()), fechas[0])

    if request.method == 'POST':
        hora_str = request.POST.get('hora')
        fecha_str = request.POST.get('fecha')
        try:
            fecha_p = datetime.date.fromisoformat(fecha_str)
            hora_p = datetime.time.fromisoformat(hora_str)
        except (TypeError, ValueError):
            messages.error(request, 'Elegí un horario para continuar.')
        else:
            if slot_disponible(psicologo, fecha_p, hora_p, tipo_sesion.duracion_min):
                _set_reserva(request, psicologo, fecha=fecha_p.isoformat(), hora=hora_p.isoformat())
                return redirect('reserva_datos', pais_slug, pk)
            messages.error(request, 'Ese horario ya no está disponible, elegí otro.')

    mes_anterior = (mes_ref - datetime.timedelta(days=1)).replace(day=1)
    if mes_ref.month == 12:
        mes_siguiente = mes_ref.replace(year=mes_ref.year + 1, month=1)
    else:
        mes_siguiente = mes_ref.replace(month=mes_ref.month + 1)

    semanas = _grilla_mes(mes_ref, psicologo, tipo_sesion)
    slots = slots_para_fecha(psicologo, fecha_elegida, tipo_sesion.duracion_min)

    return render(request, 'turnos/paso_horario.html', {
        'pais': pais, 'p': psicologo, 'tipo_sesion': tipo_sesion,
        'mes_ref': mes_ref, 'mes_nombre': f'{NOMBRES_MES_CAP[mes_ref.month - 1]} {mes_ref.year}',
        'mes_anterior': mes_anterior.strftime('%Y-%m'), 'mes_siguiente': mes_siguiente.strftime('%Y-%m'),
        'semanas': semanas, 'fecha_elegida': fecha_elegida,
        'fecha_elegida_larga': fecha_larga(fecha_elegida), 'slots': slots,
        **_contexto_pasos('horario'), 'reserva': reserva,
    })


def paso_datos(request, pais_slug, pk):
    pais, psicologo = _psicologo_publicado(pais_slug, pk)
    reserva = _get_reserva(request, psicologo)
    if 'hora' not in reserva:
        return redirect('reserva_horario', pais_slug, pk)

    if request.method == 'POST':
        form = ReservaDatosForm(request.POST)
        if form.is_valid():
            _set_reserva(request, psicologo, **form.cleaned_data)
            return redirect('reserva_confirmar', pais_slug, pk)
    else:
        form = ReservaDatosForm(initial=reserva)

    return render(request, 'turnos/paso_datos.html', {
        'pais': pais, 'p': psicologo, 'form': form,
        'resumen': _resumen(psicologo, reserva),
        **_contexto_pasos('datos'), 'reserva': reserva,
    })


def paso_confirmar(request, pais_slug, pk):
    pais, psicologo = _psicologo_publicado(pais_slug, pk)
    reserva = _get_reserva(request, psicologo)
    if 'email' not in reserva:
        return redirect('reserva_datos', pais_slug, pk)

    resumen = _resumen(psicologo, reserva)

    if request.method == 'POST':
        tipo_sesion = get_object_or_404(TipoSesion, pk=reserva['tipo_sesion_id'], psicologo=psicologo)
        fecha = datetime.date.fromisoformat(reserva['fecha'])
        hora = datetime.time.fromisoformat(reserva['hora'])

        if not slot_disponible(psicologo, fecha, hora, tipo_sesion.duracion_min):
            messages.error(request, 'Uy, justo se ocupó ese horario. Elegí otro.')
            return redirect('reserva_horario', pais_slug, pk)

        with transaction.atomic():
            fecha_hora = timezone.make_aware(datetime.datetime.combine(fecha, hora))
            ya_ocupado = Turno.objects.select_for_update().filter(
                psicologo=psicologo, fecha_hora=fecha_hora
            ).exclude(estado='cancelado').exists()
            if ya_ocupado:
                messages.error(request, 'Uy, justo se ocupó ese horario. Elegí otro.')
                return redirect('reserva_horario', pais_slug, pk)

            paciente = _upsert_paciente(psicologo, reserva)
            turno = Turno.objects.create(
                psicologo=psicologo, paciente=paciente, tipo_sesion=tipo_sesion, fecha_hora=fecha_hora,
                modalidad=reserva['modalidad'], nombres=reserva['nombres'], apellidos=reserva['apellidos'],
                telefono=reserva['telefono'], email=reserva['email'], edad=reserva.get('edad') or None,
                motivo_consulta=reserva.get('motivo_consulta', ''),
            )

        del request.session[_session_key(psicologo)]
        _avisar_por_mail(turno)
        return render(request, 'turnos/confirmado.html', {'pais': pais, 'p': psicologo, 'turno': turno})

    return render(request, 'turnos/paso_confirmar.html', {
        'pais': pais, 'p': psicologo, 'resumen': resumen,
        **_contexto_pasos('confirmar'), 'reserva': reserva,
    })


def _resumen(psicologo, reserva):
    if 'tipo_sesion_id' not in reserva:
        return None
    tipo_sesion = TipoSesion.objects.filter(pk=reserva['tipo_sesion_id']).first()
    fecha = datetime.date.fromisoformat(reserva['fecha']) if 'fecha' in reserva else None
    hora = datetime.time.fromisoformat(reserva['hora']) if 'hora' in reserva else None
    return {
        'tipo_sesion': tipo_sesion,
        'modalidad': reserva.get('modalidad'),
        'fecha': fecha,
        'fecha_larga': fecha_larga(fecha) if fecha else None,
        'hora': hora,
    }


def _upsert_paciente(psicologo, reserva):
    """Al confirmar una reserva, busca (o crea) la ficha de paciente de esa
    persona dentro de la cartera del psicólogo, agrupando por email. Si ya
    existía, completa los datos que estuvieran vacíos pero no pisa lo que el
    profesional haya editado a mano en la ficha."""
    email = (reserva.get('email') or '').strip().lower()
    nombres = reserva.get('nombres', '').strip()
    apellidos = reserva.get('apellidos', '').strip()
    telefono = reserva.get('telefono', '').strip()
    edad = reserva.get('edad') or None

    paciente = None
    if email:
        paciente = Paciente.objects.filter(psicologo=psicologo, email=email).first()

    if paciente is None:
        return Paciente.objects.create(
            psicologo=psicologo, nombres=nombres, apellidos=apellidos,
            telefono=telefono, email=email, edad=edad,
        )

    cambios = []
    if not paciente.telefono and telefono:
        paciente.telefono = telefono
        cambios.append('telefono')
    if paciente.edad is None and edad is not None:
        paciente.edad = edad
        cambios.append('edad')
    if cambios:
        paciente.save(update_fields=cambios)
    return paciente


def _avisar_por_mail(turno):
    send_mail(
        subject=f'Nueva reserva: {turno.nombres} {turno.apellidos}',
        message=(
            f'{turno.nombres} {turno.apellidos} reservó un turno con vos.\n\n'
            f'Fecha: {turno.fecha_hora:%d/%m/%Y %H:%M}\n'
            f'Tipo de sesión: {turno.tipo_sesion.nombre}\n'
            f'Modalidad: {turno.get_modalidad_display()}\n'
            f'Teléfono: {turno.telefono}\n'
            f'Email: {turno.email}\n'
            f'Motivo de consulta: {turno.motivo_consulta or "(no especificado)"}\n'
        ),
        from_email=None,
        recipient_list=[turno.psicologo.usuario.email],
    )
