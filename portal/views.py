from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Max
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from directorio.models import Orientacion, Pais, Psicologo, Publico
from turnos.models import Paciente, Turno

from .forms import (
    DiaNoAtiendeFormSet,
    DisponibilidadFormSet,
    FormacionFormSet,
    PacienteForm,
    PerfilForm,
    RegistroForm,
    TipoSesionFormSet,
)


def registro(request, pais_slug):
    pais = get_object_or_404(Pais, slug=pais_slug, activo=True)

    if request.user.is_authenticated:
        return redirect('portal_dashboard')

    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            usuario = User.objects.create_user(
                username=form.cleaned_data['email'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
            )
            Psicologo.objects.create(
                usuario=usuario,
                pais=pais,
                nombre=form.cleaned_data['nombre'],
                whatsapp=form.cleaned_data['whatsapp'],
                matricula='',
            )
            # Se crea el usuario directo (sin pasar por authenticate()), así
            # que hay que decirle a login() qué backend usar explícitamente
            # -- si no, falla porque hay dos backends configurados (axes +
            # el de email case-insensitive).
            login(request, usuario, backend='directorio.auth_backends.EmailCaseInsensitiveBackend')
            return redirect('portal_checkout')
    else:
        form = RegistroForm()

    return render(request, 'portal/registro.html', {'pais': pais, 'form': form})


@login_required
def checkout(request):
    psicologo = request.user.psicologo
    if psicologo.suscripcion_activa or psicologo.exento_de_pago:
        return redirect('portal_dashboard')
    # TODO: acá va la integración real con dLocal Go -- crear la suscripción
    # vía su API y redirigir a request a la URL de pago que devuelva, con un
    # return_url que apunte de vuelta a esta misma vista. Bloqueado hasta
    # tener la API key/secret. Mientras tanto, en DEBUG se puede simular el
    # pago para probar el resto del flujo end to end.
    return render(request, 'portal/checkout.html', {'psicologo': psicologo, 'debug': settings.DEBUG})


@login_required
def simular_pago(request):
    if not settings.DEBUG:
        raise Http404()
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    request.user.psicologo.activar_suscripcion(dlocal_subscription_id='SIMULADO-DEV')
    messages.success(request, 'Pago simulado con éxito (solo disponible en desarrollo).')
    return redirect('portal_dashboard')


@login_required
def dashboard(request):
    psicologo = request.user.psicologo
    ahora = timezone.now()
    proximos = (psicologo.turnos.filter(fecha_hora__gte=ahora, estado='agendado')
                .select_related('tipo_sesion').order_by('fecha_hora')[:5])
    return render(request, 'portal/dashboard.html', {
        'p': psicologo,
        'proximos_turnos': proximos,
        'turnos_por_confirmar': psicologo.turnos.filter(fecha_hora__lt=ahora, estado='agendado').count(),
        'total_pacientes': psicologo.pacientes.count(),
        'agenda_lista': psicologo.tipos_sesion.exists() and psicologo.disponibilidad_semanal.exists(),
    })


@login_required
def editar_perfil(request):
    psicologo = request.user.psicologo
    if request.method == 'POST':
        form = PerfilForm(request.POST, request.FILES, instance=psicologo, pais=psicologo.pais)
        formset = FormacionFormSet(request.POST, instance=psicologo)
        if form.is_valid() and formset.is_valid():
            psicologo = form.save()
            formset.save()

            nombre_nuevo = form.cleaned_data.get('publico_nuevo', '').strip()
            if nombre_nuevo:
                publico, _creado = Publico.objects.get_or_create(
                    nombre__iexact=nombre_nuevo,
                    defaults={'nombre': nombre_nuevo},
                )
                psicologo.publicos.add(publico)

            orientacion_nueva = form.cleaned_data.get('orientacion_nueva', '').strip()
            if orientacion_nueva:
                orientacion, _creada = Orientacion.objects.get_or_create(
                    nombre__iexact=orientacion_nueva,
                    defaults={'nombre': orientacion_nueva},
                )
                psicologo.orientaciones.add(orientacion)

            messages.success(request, 'Perfil actualizado.')
            return redirect('portal_dashboard')
    else:
        form = PerfilForm(instance=psicologo, pais=psicologo.pais)
        formset = FormacionFormSet(instance=psicologo)

    return render(request, 'portal/editar_perfil.html', {'p': psicologo, 'form': form, 'formset': formset})


@login_required
def publicar(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    psicologo = request.user.psicologo
    if psicologo.puede_publicar:
        psicologo.publicado_por_usuario = True
        psicologo.save()
        messages.success(request, '¡Tu perfil ya está publicado y visible en el buscador!')
    else:
        messages.error(request, 'Todavía no cumplís los requisitos para publicar (perfil completo + suscripción activa).')
    return redirect('portal_dashboard')


@login_required
def despublicar(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    psicologo = request.user.psicologo
    psicologo.publicado_por_usuario = False
    psicologo.save()
    messages.success(request, 'Tu perfil dejó de mostrarse en el buscador.')
    return redirect('portal_dashboard')


# =========================================================================
# AGENDA -- tipos de sesión, disponibilidad semanal y días que no atiende.
# Las tres cosas se editan en una sola página con un solo "Guardar".
# =========================================================================
@login_required
def agenda(request):
    psicologo = request.user.psicologo

    def armar(data=None):
        return (
            TipoSesionFormSet(data, instance=psicologo, prefix='tipos'),
            DisponibilidadFormSet(data, instance=psicologo, prefix='disp'),
            DiaNoAtiendeFormSet(data, instance=psicologo, prefix='libres'),
        )

    if request.method == 'POST':
        fs_tipos, fs_disp, fs_libres = armar(request.POST)
        if fs_tipos.is_valid() and fs_disp.is_valid() and fs_libres.is_valid():
            fs_tipos.save()
            fs_disp.save()
            fs_libres.save()
            messages.success(request, 'Agenda actualizada.')
            return redirect('portal_agenda')
    else:
        fs_tipos, fs_disp, fs_libres = armar()

    return render(request, 'portal/agenda.html', {
        'p': psicologo,
        'fs_tipos': fs_tipos,
        'fs_disp': fs_disp,
        'fs_libres': fs_libres,
    })


# =========================================================================
# TURNOS
# =========================================================================
_ACCIONES_TURNO = {
    'realizado': ('realizado', 'Turno marcado como realizado.'),
    'ausente': ('ausente', 'Turno marcado como "no asistió".'),
    'cancelado': ('cancelado', 'Turno cancelado.'),
    'reactivar': ('agendado', 'Turno reactivado.'),
}


@login_required
def turnos_lista(request):
    psicologo = request.user.psicologo
    ahora = timezone.now()
    base = psicologo.turnos.select_related('tipo_sesion', 'paciente')
    return render(request, 'portal/turnos.html', {
        'p': psicologo,
        'proximos': base.filter(fecha_hora__gte=ahora).exclude(estado='cancelado').order_by('fecha_hora'),
        'pasados': base.filter(fecha_hora__lt=ahora).order_by('-fecha_hora')[:100],
        'cancelados': base.filter(estado='cancelado', fecha_hora__gte=ahora).order_by('fecha_hora'),
    })


@login_required
def turno_detalle(request, pk):
    psicologo = request.user.psicologo
    turno = get_object_or_404(Turno.objects.select_related('tipo_sesion', 'paciente'),
                              pk=pk, psicologo=psicologo)

    if request.method == 'POST':
        turno.notas_profesional = request.POST.get('notas_profesional', '').strip()
        turno.save(update_fields=['notas_profesional'])
        messages.success(request, 'Notas guardadas.')
        return redirect('portal_turno_detalle', pk=turno.pk)

    return render(request, 'portal/turno_detalle.html', {'p': psicologo, 't': turno})


@login_required
def turno_accion(request, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    psicologo = request.user.psicologo
    turno = get_object_or_404(Turno, pk=pk, psicologo=psicologo)

    accion = request.POST.get('accion')
    if accion not in _ACCIONES_TURNO:
        messages.error(request, 'Acción no válida.')
    else:
        nuevo_estado, msg = _ACCIONES_TURNO[accion]
        turno.estado = nuevo_estado
        turno.save(update_fields=['estado'])
        messages.success(request, msg)

    return redirect(request.POST.get('next') or 'portal_turnos')


# =========================================================================
# PACIENTES
# =========================================================================
@login_required
def pacientes_lista(request):
    psicologo = request.user.psicologo
    q = request.GET.get('q', '').strip()
    pacientes = psicologo.pacientes.annotate(
        n_turnos=Count('turnos'), ultimo=Max('turnos__fecha_hora'),
    )
    if q:
        pacientes = pacientes.filter(nombres__icontains=q) | pacientes.filter(apellidos__icontains=q)
    return render(request, 'portal/pacientes.html', {
        'p': psicologo, 'pacientes': pacientes, 'q': q,
    })


@login_required
def paciente_nuevo(request):
    psicologo = request.user.psicologo
    if request.method == 'POST':
        form = PacienteForm(request.POST, psicologo=psicologo)
        if form.is_valid():
            paciente = form.save(commit=False)
            paciente.psicologo = psicologo
            paciente.save()
            messages.success(request, 'Paciente agregado.')
            return redirect('portal_paciente_detalle', pk=paciente.pk)
    else:
        form = PacienteForm(psicologo=psicologo)
    return render(request, 'portal/paciente_detalle.html', {
        'p': psicologo, 'form': form, 'paciente': None, 'turnos': [],
    })


@login_required
def paciente_detalle(request, pk):
    psicologo = request.user.psicologo
    paciente = get_object_or_404(Paciente, pk=pk, psicologo=psicologo)

    if request.method == 'POST':
        form = PacienteForm(request.POST, instance=paciente, psicologo=psicologo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ficha actualizada.')
            return redirect('portal_paciente_detalle', pk=paciente.pk)
    else:
        form = PacienteForm(instance=paciente, psicologo=psicologo)

    return render(request, 'portal/paciente_detalle.html', {
        'p': psicologo,
        'form': form,
        'paciente': paciente,
        'turnos': paciente.turnos.select_related('tipo_sesion').order_by('-fecha_hora'),
    })


@login_required
def paciente_eliminar(request, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    psicologo = request.user.psicologo
    paciente = get_object_or_404(Paciente, pk=pk, psicologo=psicologo)
    # Los turnos quedan (Turno.paciente es SET_NULL) con su snapshot de datos.
    paciente.delete()
    messages.success(request, 'Ficha de paciente eliminada.')
    return redirect('portal_pacientes')
