from django.http import Http404
from django.shortcuts import redirect, render

from .models import Orientacion, Pais, Psicologo, Publico


def hub(request):
    paises = Pais.objects.filter(activo=True)
    return render(request, 'directorio/hub.html', {'paises': paises})


def faq(request):
    return render(request, 'directorio/faq.html')


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
