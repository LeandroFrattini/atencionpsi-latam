from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render

from .forms import ContactoForm
from .models import Orientacion, Pais, Psicologo, Publico


def robots_txt(request):
    # Bloquea todo lo privado/funcional (portal de profesionales, admin,
    # checkout) -- lo mismo que hace Terapify con /mi-espacio/, /checkout/,
    # etc. -- para que Google no gaste rastreo ahí ni indexe una página de
    # login o de pago por error. El buscador y los perfiles publicados
    # quedan abiertos, y se apunta al sitemap para que los encuentre rápido.
    lineas = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /portal/',
        '',
        f'Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lineas), content_type='text/plain')


def hub(request):
    paises = Pais.objects.filter(activo=True)
    return render(request, 'directorio/hub.html', {'paises': paises})


def faq(request):
    return render(request, 'directorio/faq.html')


def terminos(request):
    return render(request, 'directorio/terminos.html', {
        'contacto_email': settings.CONTACTO_EMAIL,
        'terminos_precio_suscripcion': settings.TERMINOS_PRECIO_SUSCRIPCION,
        'terminos_datos_legales': settings.TERMINOS_DATOS_LEGALES,
    })


def contacto(request):
    enviado = False
    if request.method == 'POST':
        form = ContactoForm(request.POST)
        if form.is_valid():
            # El remitente real siempre tiene que ser DEFAULT_FROM_EMAIL (así
            # lo exige Brevo -- no deja mandar "de parte de" un email que no
            # esté verificado), así que el email de quien escribe va como
            # reply_to para poder responderle directo desde el cliente de
            # mail de la dueña sin tener que copiar y pegar la dirección.
            EmailMessage(
                subject=f"Contacto desde atencionpsi.lat -- {form.cleaned_data['nombre']}",
                body=(
                    f"Nombre: {form.cleaned_data['nombre']}\n"
                    f"Email: {form.cleaned_data['email']}\n\n"
                    f"{form.cleaned_data['mensaje']}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.CONTACTO_EMAIL],
                reply_to=[form.cleaned_data['email']],
            ).send()
            messages.success(request, 'Mensaje enviado, te vamos a responder a la brevedad.')
            enviado = True
            form = ContactoForm()
    else:
        form = ContactoForm()

    return render(request, 'directorio/contacto.html', {
        'form': form, 'enviado': enviado,
        'contacto_email': settings.CONTACTO_EMAIL,
        'contacto_whatsapp': settings.CONTACTO_WHATSAPP,
    })


def buscador_pais(request, pais_slug):
    try:
        pais = Pais.objects.get(slug=pais_slug, activo=True)
    except Pais.DoesNotExist:
        raise Http404('País no disponible todavía')

    # Argentina (y cualquier otro país marcado "externo") no vive en esta
    # base -- si alguien toca este link a mano, se lo manda directo afuera
    # en vez de mostrarle un buscador interno vacío.
    if pais.es_externo:
        return redirect(pais.url_externa)

    psicologos_qs = pais.psicologos.all().prefetch_related('orientaciones', 'publicos', 'tipos_sesion')

    ciudad = request.GET.get('ciudad', '').strip()
    modalidad = request.GET.get('modalidad', '').strip()
    orientacion_id = request.GET.get('orientacion', '').strip()
    publico_id = request.GET.get('publico', '').strip()

    if ciudad:
        psicologos_qs = psicologos_qs.filter(ciudad__iexact=ciudad)
    if modalidad:
        psicologos_qs = psicologos_qs.filter(modalidad=modalidad)
    if orientacion_id:
        psicologos_qs = psicologos_qs.filter(orientaciones__pk=orientacion_id)
    if publico_id:
        psicologos_qs = psicologos_qs.filter(publicos__pk=publico_id)

    # "publicado" combina pago + completitud de perfil -- no es un campo de
    # base, así que el filtro final se resuelve en Python sobre un queryset
    # ya achicado por los filtros de arriba.
    psicologos = [p for p in psicologos_qs.distinct() if p.publicado]

    ciudades = sorted({p.ciudad for p in pais.psicologos.all() if p.publicado and p.ciudad})

    return render(request, 'directorio/buscador.html', {
        'pais': pais,
        'psicologos': psicologos,
        'ciudades': ciudades,
        'orientaciones_list': Orientacion.objects.all(),
        'publicos_list': Publico.objects.all(),
    })


def detalle_psicologo(request, pais_slug, pk):
    try:
        pais = Pais.objects.get(slug=pais_slug, activo=True)
    except Pais.DoesNotExist:
        raise Http404('País no disponible todavía')

    try:
        psicologo = pais.psicologos.get(pk=pk)
    except Psicologo.DoesNotExist:
        raise Http404('Perfil no encontrado')

    if not psicologo.publicado:
        raise Http404('Perfil no publicado')

    return render(request, 'directorio/detalle_psicologo.html', {
        'pais': pais,
        'p': psicologo,
        'formaciones': psicologo.formaciones.all(),
    })
