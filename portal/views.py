from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from directorio.models import Pais, Psicologo

from .forms import FormacionFormSet, PerfilForm, RegistroForm


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
    return render(request, 'portal/dashboard.html', {'p': psicologo})


@login_required
def editar_perfil(request):
    psicologo = request.user.psicologo
    if request.method == 'POST':
        form = PerfilForm(request.POST, request.FILES, instance=psicologo, pais=psicologo.pais)
        formset = FormacionFormSet(request.POST, instance=psicologo)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
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
