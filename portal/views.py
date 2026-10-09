import json
import logging
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt

from directorio import dlocal_go, suscripciones
from directorio.models import Ciudad, CodigoFundador, Especialidad, Orientacion, Pais, PlanDLocal, Psicologo, Publico
from directorio.taxonomia import buscar_o_proponer
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

logger = logging.getLogger(__name__)

_LOGIN_BACKEND = 'directorio.auth_backends.EmailCaseInsensitiveBackend'


def _enviar_verificacion(request, usuario):
    """Manda el link de confirmación de email. El token es el mismo
    mecanismo que usa Django para "olvidé mi contraseña" (PasswordResetTokenGenerator):
    queda atado al hash de la contraseña y a last_login, así que se invalida
    solo apenas se usa una vez (login() actualiza last_login)."""
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    url = request.build_absolute_uri(reverse('portal_verificar_email', args=[uid, token]))
    contexto = {'nombre': usuario.psicologo.nombre, 'url': url, 'contacto_email': settings.CONTACTO_EMAIL}

    email = EmailMultiAlternatives(
        subject='Confirmá tu email -- Atención Psi',
        body=render_to_string('portal/email/verificacion.txt', contexto),
        from_email=None,
        to=[usuario.email],
    )
    email.attach_alternative(render_to_string('portal/email/verificacion.html', contexto), 'text/html')
    email.send()


def registro(request, pais_slug):
    pais = get_object_or_404(Pais, slug=pais_slug, activo=True)

    if request.user.is_authenticated:
        return redirect('portal_dashboard')

    if request.method == 'POST':
        form = RegistroForm(request.POST, pais=pais)
        if form.is_valid():
            # is_active=False hasta que confirme el mail -- si no, cualquiera
            # se registra con un email ajeno o inventado y nunca se entera.
            # Lo bloquea solo: tanto AuthenticationForm (login de /portal/)
            # como los dos backends de auth chequean is_active antes de
            # dejar entrar.
            usuario = User.objects.create_user(
                username=form.cleaned_data['email'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                is_active=False,
            )
            psicologo = Psicologo.objects.create(
                usuario=usuario,
                pais=pais,
                nombre=form.cleaned_data['nombre'],
                whatsapp=form.cleaned_data['whatsapp'],
                matricula='',
                terminos_aceptados_en=timezone.now(),
            )
            codigo = form.cleaned_data.get('codigo_fundador')
            if codigo:
                _canjear_codigo(request, psicologo, codigo, pais)
            try:
                _enviar_verificacion(request, usuario)
            except Exception:
                # El envío depende del SMTP de Brevo -- si falla, la cuenta ya
                # existe (sin eso no hay forma de que llegue a confirmarla
                # nunca), pero no tiene que tirar un 500 en pleno registro.
                logger.exception('No se pudo enviar el mail de verificación a %s', usuario.email)
                messages.error(
                    request,
                    f'Tu cuenta se creó, pero hubo un problema mandando el mail de confirmación. '
                    f'Escribinos a {settings.CONTACTO_EMAIL} para activarla.'
                )
                return redirect('portal_login')
            return render(request, 'portal/verificar_enviado.html', {'email': usuario.email})
    else:
        form = RegistroForm(pais=pais, initial={'codigo_fundador': request.GET.get('codigo', '').strip().upper()})

    return render(request, 'portal/registro.html', {'pais': pais, 'form': form})


def _canjear_codigo(request, psicologo, codigo, pais):
    """Canjea el código de fundador con la fila bloqueada, para que dos
    personas no puedan usar a la vez un código de un solo uso."""
    with transaction.atomic():
        bloqueado = CodigoFundador.objects.select_for_update().get(pk=codigo.pk)
        motivo = bloqueado.motivo_de_rechazo(pais)
        if motivo:
            messages.warning(request, f'Tu cuenta se creó, pero el código no se pudo aplicar: {motivo}')
            return
        psicologo.canjear_codigo_fundador(bloqueado)
    messages.success(request, f'Código aplicado: {bloqueado.meses_gratis} meses gratis.')


def verificar_enviado(request):
    """Accesible directo (no solo recién registrado) para quien vuelve a
    buscar el formulario de reenvío sin tener que recordar su mail en la URL."""
    return render(request, 'portal/verificar_enviado.html', {'email': None})


def verificar_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        usuario = User.objects.select_related('psicologo').get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        usuario = None

    if usuario is None:
        return render(request, 'portal/verificar_invalido.html')

    if usuario.is_active:
        # Ya se había confirmado (ej: tocó el link dos veces) -- no es un error.
        messages.info(request, 'Tu email ya estaba confirmado. Iniciá sesión para continuar.')
        return redirect('portal_login')

    if not default_token_generator.check_token(usuario, token):
        return render(request, 'portal/verificar_invalido.html')

    usuario.is_active = True
    usuario.save(update_fields=['is_active'])
    login(request, usuario, backend=_LOGIN_BACKEND)
    messages.success(request, '¡Listo, tu email quedó confirmado!')
    return redirect('portal_checkout')


def reenviar_verificacion(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    email = request.POST.get('email', '').strip().lower()
    usuario = User.objects.filter(username__iexact=email, is_active=False).select_related('psicologo').first()
    if usuario is not None:
        try:
            _enviar_verificacion(request, usuario)
        except Exception:
            logger.exception('No se pudo reenviar el mail de verificación a %s', usuario.email)
    # Mismo mensaje exista o no la cuenta (y exista o no haya fallado el
    # envío) -- no delatar qué emails están registrados.
    messages.success(request, 'Si ese email tiene una cuenta pendiente de confirmar, te reenviamos el link.')
    return redirect('portal_verificar_enviado')


def _dlocal_go_conectado():
    return dlocal_go.conectado()


def psicologo_required(view_func):
    """Como @login_required, pero además exige que la cuenta logueada
    tenga un Psicologo asociado -- todas las vistas de acá abajo hacen
    request.user.psicologo de entrada. Sin esto, cualquier cuenta logueada
    sin perfil (ej: un superusuario creado por createsuperuser para entrar
    a /admin/, que nunca pasó por el registro público) tira un 500 en vez
    de un error entendible (bug real, visto en producción 2026-10-01)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, 'psicologo'):
            logout(request)
            messages.error(
                request,
                'Esa cuenta no tiene un perfil de profesional asociado '
                '(¿es una cuenta de administración?). Iniciá sesión con tu cuenta de psicólogo/a.'
            )
            return redirect('portal_login')
        return view_func(request, *args, **kwargs)
    return wrapper


@psicologo_required
def checkout(request):
    psicologo = request.user.psicologo
    if psicologo.suscripcion_activa or psicologo.exento_de_pago:
        return redirect('portal_dashboard')

    conectado = _dlocal_go_conectado()
    planes = {p.plan: p for p in PlanDLocal.objects.filter(pais=psicologo.pais, activo=True)} if conectado else {}

    if request.method == 'POST' and conectado:
        plan = request.POST.get('plan', '')
        plan_dlocal = planes.get(plan)
        if not plan_dlocal:
            messages.error(
                request,
                'Ese plan todavía no está disponible para cobrar en tu país. Escribinos desde Contacto y lo resolvemos.',
            )
            return redirect('portal_checkout')
        psicologo.plan = plan
        psicologo.save(update_fields=['plan'])
        # El link de pago es de dLocal Go (ahí se cargan los datos de la
        # tarjeta, nunca pasan por este sitio). Se le adelanta el mail y se
        # le pone un identificador propio -- el estado real del pago se
        # confirma después contra la API (ver directorio/suscripciones.py),
        # no por lo que traiga la redirección de vuelta.
        return redirect(plan_dlocal.subscribe_url + '?' + urlencode({
            'email': psicologo.usuario.email,
            'external_id': suscripciones.external_id_de(psicologo),
        }))

    return render(request, 'portal/checkout.html', {
        'psicologo': psicologo,
        # En producción con claves cargadas ya no corre el modo de prueba.
        'integracion_pendiente': not conectado,
        'planes_disponibles': set(planes),
        'error_de_pago': request.GET.get('error') == '1',
    })


@psicologo_required
def checkout_retorno(request):
    """A donde vuelve el profesional después de pagar en dLocal Go
    (success_url del plan). No alcanza con que haya llegado acá: se consulta
    la API y recién ahí se activa. Si dLocal todavía está procesando, la
    página se recarga sola unos segundos."""
    psicologo = request.user.psicologo
    if _dlocal_go_conectado():
        try:
            suscripciones.sincronizar_psicologo(psicologo)
        except dlocal_go.DLocalError:
            logger.exception('No se pudo confirmar el pago del profesional %s al volver de dLocal Go', psicologo.pk)
    psicologo.refresh_from_db()
    if psicologo.suscripcion_activa:
        messages.success(request, '¡Listo! Tu suscripción está activa. Ya podés completar tu perfil y publicarlo.')
        return redirect('portal_dashboard')
    try:
        intento = int(request.GET.get('n', 0))
    except ValueError:
        intento = 0
    return render(request, 'portal/checkout_retorno.html', {
        'intento': intento, 'siguiente': intento + 1, 'seguir_esperando': intento < 10,
    })


@csrf_exempt
def dlocal_webhook(request):
    """Notificación de dLocal Go (solo trae {"payment_id": ...}, firmada).
    No se confía en el contenido: se verifica la firma, se pide el pago a la
    API y con el mail de quien pagó se sincroniza a ese profesional. Si algo
    falla por culpa de dLocal/red se responde 502 a propósito: dLocal
    reintenta cada 10 minutos (hasta 30 días) las respuestas que no son 200."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not dlocal_go.firma_valida(request.body, request.headers.get('Authorization', '')):
        return HttpResponse(status=403)
    try:
        payment_id = json.loads(request.body).get('payment_id')
    except (ValueError, AttributeError):
        return HttpResponse(status=400)
    if not payment_id:
        return HttpResponse(status=400)
    try:
        pago = dlocal_go.obtener_pago(payment_id)
        email = ((pago.get('payer') or {}).get('email') or '').strip()
        psicologo = (
            Psicologo.objects.filter(usuario__email__iexact=email, exento_de_pago=False)
            .select_related('usuario', 'pais').first() if email else None
        )
        if psicologo:
            suscripciones.sincronizar_psicologo(psicologo)
        else:
            logger.warning('Notificación de dLocal Go del pago %s sin profesional asociado (mail %r)', payment_id, email)
    except dlocal_go.DLocalError:
        logger.exception('Falló el procesamiento de la notificación de dLocal Go (pago %s)', payment_id)
        return HttpResponse(status=502)
    return HttpResponse(status=200)


@psicologo_required
def simular_pago(request):
    if _dlocal_go_conectado():
        raise Http404()
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    plan = request.POST.get('plan', 'basico')
    request.user.psicologo.activar_suscripcion(dlocal_subscription_id='SIMULADO-DEV', plan=plan)
    messages.success(request, 'Suscripción activada en modo de prueba.')
    return redirect('portal_dashboard')


@psicologo_required
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


@psicologo_required
def editar_perfil(request):
    psicologo = request.user.psicologo
    if request.method == 'POST':
        form = PerfilForm(request.POST, request.FILES, instance=psicologo, pais=psicologo.pais)
        formset = FormacionFormSet(request.POST, instance=psicologo)
        if form.is_valid() and formset.is_valid():
            psicologo = form.save()
            formset.save()

            # Lo escrito a mano no entra directo a la lista de todos: queda
            # pendiente y lo ve solo este profesional hasta que se apruebe
            # desde el admin (ver directorio/taxonomia.py).
            pendientes = []

            texto = form.cleaned_data.get('publico_nuevo', '')
            publico, pendiente = buscar_o_proponer(Publico, texto, psicologo)
            if publico:
                psicologo.publicos.add(publico)
                if pendiente:
                    pendientes.append(f'el público "{publico.nombre}"')

            texto = form.cleaned_data.get('especialidad_nueva', '')
            especialidad, pendiente = buscar_o_proponer(Especialidad, texto, psicologo)
            if especialidad:
                psicologo.especialidades.add(especialidad)
                if pendiente:
                    pendientes.append(f'el motivo de consulta "{especialidad.nombre}"')

            texto = form.cleaned_data.get('orientacion_nueva', '')
            orientacion, pendiente = buscar_o_proponer(Orientacion, texto, psicologo)
            if orientacion:
                psicologo.orientaciones.add(orientacion)
                if pendiente:
                    pendientes.append(f'la orientación "{orientacion.nombre}"')

            texto = form.cleaned_data.get('ciudad_nueva', '')
            ciudad, pendiente = buscar_o_proponer(Ciudad, texto, psicologo, pais=psicologo.pais)
            if ciudad:
                psicologo.ciudad = ciudad.nombre
                psicologo.save(update_fields=['ciudad'])
                if pendiente:
                    pendientes.append(f'la ciudad "{ciudad.nombre}"')

            if pendientes:
                messages.info(
                    request,
                    'Recibimos tu propuesta: ' + ', '.join(pendientes) + '. La revisamos y, si corresponde, '
                    'la sumamos a la lista; mientras tanto la ves solo vos y no se muestra en tu perfil público.',
                )

            messages.success(request, 'Perfil actualizado.')
            return redirect('portal_dashboard')
    else:
        form = PerfilForm(instance=psicologo, pais=psicologo.pais)
        formset = FormacionFormSet(instance=psicologo)

    return render(request, 'portal/editar_perfil.html', {'p': psicologo, 'form': form, 'formset': formset})


@psicologo_required
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


@psicologo_required
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
@psicologo_required
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


@psicologo_required
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


@psicologo_required
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


@psicologo_required
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
@psicologo_required
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


@psicologo_required
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


@psicologo_required
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


@psicologo_required
def paciente_eliminar(request, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    psicologo = request.user.psicologo
    paciente = get_object_or_404(Paciente, pk=pk, psicologo=psicologo)
    # Los turnos quedan (Turno.paciente es SET_NULL) con su snapshot de datos.
    paciente.delete()
    messages.success(request, 'Ficha de paciente eliminada.')
    return redirect('portal_pacientes')
