import logging
import random
import re
from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ContactoForm
from .models import Ciudad, Especialidad, Orientacion, Pais, Psicologo, Publico
from . import buscador
from .destacados import CANTIDAD_DESTACADOS_INICIO, mezcla_de_psicologos
from .taxonomia import clave

logger = logging.getLogger(__name__)


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
    return render(request, 'directorio/hub.html', {
        'paises': paises,
        # Mezcla distinta en cada visita, de todos los países activos.
        'destacados': mezcla_de_psicologos(CANTIDAD_DESTACADOS_INICIO),
    })


def sobre_nosotros(request):
    pais = Pais.objects.filter(activo=True, es_externo=False).order_by('orden').first()
    return render(request, 'directorio/sobre_nosotros.html', {
        'pais_inicio': pais,
        'contacto_email': settings.CONTACTO_EMAIL,
        'contacto_whatsapp': settings.CONTACTO_WHATSAPP,
        'contacto_telefono': settings.CONTACTO_TELEFONO,
    })


def faq(request):
    return render(request, 'directorio/faq.html')


def terminos(request):
    # Un país por sección, con sus dos planes y precios reales -- así la
    # misma página sirve para mandar a dLocal sin importar para cuál de los
    # 3 países activos sea el chequeo. Argentina no entra (es externa, vive
    # en atencionpsi.com.ar) y los países todavía inactivos tampoco tienen
    # plan cargado.
    paises_con_plan = Pais.objects.filter(activo=True, es_externo=False).order_by('orden')
    return render(request, 'directorio/terminos.html', {
        'contacto_email': settings.CONTACTO_EMAIL,
        'contacto_whatsapp': settings.CONTACTO_WHATSAPP,
        'contacto_telefono': settings.CONTACTO_TELEFONO,
        'paises_con_plan': paises_con_plan,
        'terminos_datos_legales': settings.TERMINOS_DATOS_LEGALES,
    })


def privacidad(request):
    return render(request, 'directorio/privacidad.html', {
        'contacto_email': settings.CONTACTO_EMAIL,
        'contacto_whatsapp': settings.CONTACTO_WHATSAPP,
        'contacto_telefono': settings.CONTACTO_TELEFONO,
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
            try:
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
            except Exception:
                # El envío depende del SMTP de Brevo -- si falla (credenciales
                # mal cargadas, Brevo caído, etc.) no tiene que tirar un 500,
                # sino avisar que no se pudo mandar y dejar un canal alternativo.
                logger.exception('No se pudo enviar el mail de contacto')
                messages.error(
                    request,
                    f'Hubo un problema enviando tu mensaje. Probá de nuevo en unos minutos, '
                    f'o escribinos directo a {settings.CONTACTO_EMAIL} (WhatsApp {settings.CONTACTO_TELEFONO}).'
                )
            else:
                messages.success(request, 'Mensaje enviado, te vamos a responder a la brevedad.')
                enviado = True
                form = ContactoForm()
    else:
        form = ContactoForm()

    return render(request, 'directorio/contacto.html', {
        'form': form, 'enviado': enviado,
        'contacto_email': settings.CONTACTO_EMAIL,
        'contacto_whatsapp': settings.CONTACTO_WHATSAPP,
        'contacto_telefono': settings.CONTACTO_TELEFONO,
    })


def _pais_o_404(pais_slug):
    """País activo y propio de este sitio. Argentina (externa) no tiene páginas
    acá: vive en atencionpsi.com.ar."""
    pais = Pais.objects.filter(slug=pais_slug, activo=True).first()
    if not pais or pais.es_externo:
        raise Http404('País no disponible todavía')
    return pais


def _publicados(pais):
    """Psicólogos publicados de un país, con todo lo que muestran las tarjetas
    ya traído (publicado es una property, no un campo: se filtra en Python)."""
    qs = pais.psicologos.all().select_related('pais').prefetch_related(
        'orientaciones', 'publicos', 'especialidades', 'tipos_sesion')
    return [p for p in qs if p.publicado]


def _ciudades_con_psicologos(pais, publicados):
    """[(Ciudad, cantidad)] solo de ciudades aprobadas con al menos un
    profesional publicado, de más a menos -- una página sin nadie adentro no se
    enlaza ni se indexa."""
    cuenta = Counter(clave(p.ciudad_publica) for p in publicados if p.ciudad_publica)
    resultado = []
    for ciudad in Ciudad.objects.filter(pais=pais, aprobado=True):
        n = cuenta.get(clave(ciudad.nombre), 0)
        if n:
            resultado.append((ciudad, n))
    return sorted(resultado, key=lambda par: (-par[1], par[0].nombre))


def _especialidades_con_psicologos(publicados):
    """[(Especialidad, cantidad)] aprobadas con al menos un profesional publicado."""
    cuenta, objetos = Counter(), {}
    for p in publicados:
        for e in p.especialidades_publicas:
            cuenta[e.pk] += 1
            objetos[e.pk] = e
    return sorted(((objetos[pk], n) for pk, n in cuenta.items()), key=lambda par: (-par[1], par[0].nombre))


def pais_home(request, pais_slug):
    # Landing por país (2026-09-09): antes /peru/ ERA el buscador directo,
    # pero para un mercado nuevo con pocos profesionales cargados, caer de
    # una en una grilla de filtros semivacía da mala primera impresión --
    # atencionpsi.com.ar ya resuelve esto con un home propio + "Profesionales
    # destacados" antes del buscador, mismo patrón acá.
    try:
        pais = Pais.objects.get(slug=pais_slug, activo=True)
    except Pais.DoesNotExist:
        raise Http404('País no disponible todavía')

    if pais.es_externo:
        return redirect(pais.url_externa)

    publicados = _publicados(pais)
    return render(request, 'directorio/home_pais.html', {
        'pais': pais,
        'psicologos_destacados': _elegidos_para_home(pais),
        'total_publicados': len(publicados),
        # Enlaces internos a las páginas por ciudad y por especialidad (solo
        # las que tienen gente adentro).
        'ciudades_con_psicologos': _ciudades_con_psicologos(pais, publicados)[:12],
        'especialidades_con_psicologos': _especialidades_con_psicologos(publicados)[:12],
    })


def _elegidos_para_home(pais, cantidad=6):
    """Hasta `cantidad` psicólogos publicados de ese país para el home,
    siempre en orden aleatorio. Los marcados `destacado` entran primero (si
    hay más que `cantidad`, se eligen al azar entre ellos); el resto de los
    lugares se completa al azar con el resto de los publicados. Mismo
    criterio que `_seis_para_home` en profesionales/views.py de
    atencionpsi.com.ar."""
    publicados = [p for p in pais.psicologos.all().prefetch_related('orientaciones', 'publicos', 'tipos_sesion') if p.publicado]
    destacados = [p for p in publicados if p.destacado]
    random.shuffle(destacados)
    elegidos = destacados[:cantidad]

    if len(elegidos) < cantidad:
        usados = {p.id for p in elegidos}
        resto = [p for p in publicados if p.id not in usados]
        random.shuffle(resto)
        elegidos += resto[:cantidad - len(elegidos)]

    random.shuffle(elegidos)
    return elegidos


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

    publicados = _publicados(pais)
    datos = buscador.leer_parametros(request.GET)
    ruta = request.path

    # 1) filtros exactos, 2) búsqueda por palabras, 3) orden
    resultado = buscador.aplicar_filtros(publicados, datos)
    resultado = buscador.filtrar_por_texto(resultado, datos['q'])
    orden = datos['orden'] if (datos['orden'] not in ('precio_asc', 'precio_desc') or pais.muestra_precio_sesion) else ''
    psicologos = buscador.ordenar(resultado, orden, con_texto=bool(buscador.palabras(datos['q'])))

    nombres = buscador.nombres_por_id()
    pills = buscador.pills_activas(ruta, datos, nombres)

    populares = buscador.motivos_populares(publicados)
    contexto = {
        'pais': pais,
        'psicologos': psicologos,
        'total': len(psicologos),
        'total_pais': len(publicados),
        'datos': datos,
        'ruta': ruta,
        'pills': pills,
        'hay_filtros': bool(pills),
        'limpiar_url': ruta,
        'motivos_chips': [{
            'nombre': nombre, 'cantidad': n,
            'activo': datos['especialidad'] == str(pk),
            'url': buscador.url_con(ruta, datos, especialidad='' if datos['especialidad'] == str(pk) else str(pk)),
        } for pk, nombre, n in populares],
        'motivos_sugeridos': [
            {'nombre': nombre, 'cantidad': n, 'url': f'{ruta}?especialidad={pk}'} for pk, nombre, n in populares[:6]
        ],
        'modalidades': [{
            'etiqueta': etiqueta, 'activo': datos['modalidad'] == valor,
            'url': buscador.url_con(ruta, datos, modalidad=valor),
        } for valor, etiqueta in buscador.MODALIDADES],
        'ordenes': buscador.ORDENES if pais.muestra_precio_sesion else [o for o in buscador.ORDENES if not o[0].startswith('precio')],
    }

    # Listas de los desplegables: solo lo que tiene al menos un profesional publicado.
    ids_orient = {o.pk for p in publicados for o in p.orientaciones_publicas}
    ids_esp = {e.pk for p in publicados for e in p.especialidades_publicas}
    ids_pub = {pu.pk for p in publicados for pu in p.publicos_publicos}
    contexto.update({
        'ciudades': buscador.ciudades_con_gente(publicados),
        'orientaciones_list': [o for o in Orientacion.objects.filter(aprobado=True) if o.pk in ids_orient],
        'publicos_list': [pu for pu in Publico.objects.filter(aprobado=True) if pu.pk in ids_pub],
        'especialidades_list': [e for e in Especialidad.objects.filter(aprobado=True) if e.pk in ids_esp],
        'filtros_extra': sum(1 for k in ('ciudad', 'orientacion', 'especialidad', 'publico') if datos[k]),
    })

    # Con ?fragmento=1 se devuelve solo la parte que cambia (la usa el buscador en vivo).
    if request.GET.get('fragmento'):
        return render(request, 'directorio/_buscador_resultados.html', contexto)

    contexto['sugerencias'] = buscador.sugerencias(publicados)
    return render(request, 'directorio/buscador.html', contexto)


def detalle_psicologo(request, pais_slug, pk):
    """URL vieja del perfil (/<país>/p/<id>/): se mantiene viva y redirige con
    301 a la URL con el nombre adentro, así nada de lo ya compartido se rompe."""
    pais = _pais_o_404(pais_slug)
    psicologo = pais.psicologos.select_related('pais').filter(pk=pk).first()
    if not psicologo or not psicologo.publicado:
        raise Http404('Perfil no encontrado')
    return redirect(psicologo.url_publica, permanent=True)


def perfil_psicologo(request, pais_slug, slug):
    pais = _pais_o_404(pais_slug)
    m = re.search(r'-(\d+)$', slug)
    if not m:
        raise Http404('Perfil no encontrado')
    psicologo = pais.psicologos.select_related('pais').prefetch_related(
        'orientaciones', 'publicos', 'especialidades', 'tipos_sesion', 'formaciones',
    ).filter(pk=int(m.group(1))).first()
    if not psicologo or not psicologo.publicado:
        raise Http404('Perfil no encontrado')
    if slug != psicologo.slug_url:
        # El nombre cambió o la URL está mal escrita: va a la correcta.
        return redirect(psicologo.url_publica, permanent=True)

    ciudad_nombre = psicologo.ciudad_publica
    ciudad_obj = None
    otros = []
    if ciudad_nombre:
        k = clave(ciudad_nombre)
        ciudad_obj = next((c for c in Ciudad.objects.filter(pais=pais, aprobado=True) if clave(c.nombre) == k), None)
        otros = [p for p in _publicados(pais) if p.pk != psicologo.pk and clave(p.ciudad_publica) == k][:3]

    return render(request, 'directorio/detalle_psicologo.html', {
        'pais': pais,
        'p': psicologo,
        'formaciones': psicologo.formaciones.all(),
        'sesiones': list(psicologo.tipos_sesion.all()),
        'ciudad_obj': ciudad_obj,
        'otros_en_la_ciudad': otros,
    })


def psicologos_en_ciudad(request, pais_slug, ciudad_slug):
    pais = _pais_o_404(pais_slug)
    ciudad = get_object_or_404(Ciudad, pais=pais, slug=ciudad_slug, aprobado=True)
    publicados = _publicados(pais)
    k = clave(ciudad.nombre)
    psicologos = [p for p in publicados if clave(p.ciudad_publica) == k]
    return render(request, 'directorio/landing_seo.html', {
        'pais': pais,
        'tipo': 'ciudad',
        'titulo_zona': ciudad.nombre,
        'ciudad': ciudad,
        'psicologos': psicologos,
        'chips_titulo': 'Por especialidad en %s' % ciudad.nombre,
        'chips': [(e.nombre, reverse_especialidad(pais, e), n) for e, n in _especialidades_con_psicologos(psicologos)],
        'otros_titulo': 'Otras ciudades de %s' % pais.nombre,
        'otros': [(c.nombre, reverse_ciudad(pais, c), n) for c, n in _ciudades_con_psicologos(pais, publicados) if c.pk != ciudad.pk][:15],
        'noindex': not psicologos,
    })


def psicologos_por_especialidad(request, pais_slug, especialidad_slug):
    pais = _pais_o_404(pais_slug)
    especialidad = get_object_or_404(Especialidad, slug=especialidad_slug, aprobado=True)
    publicados = _publicados(pais)
    psicologos = [p for p in publicados if especialidad in p.especialidades_publicas]
    return render(request, 'directorio/landing_seo.html', {
        'pais': pais,
        'tipo': 'especialidad',
        'titulo_zona': especialidad.nombre,
        'especialidad': especialidad,
        'psicologos': psicologos,
        'chips_titulo': 'Por ciudad',
        'chips': [(c.nombre, reverse_ciudad(pais, c), n) for c, n in _ciudades_con_psicologos(pais, psicologos)],
        'otros_titulo': 'Otras especialidades',
        'otros': [(e.nombre, reverse_especialidad(pais, e), n) for e, n in _especialidades_con_psicologos(publicados) if e.pk != especialidad.pk][:15],
        'noindex': not psicologos,
    })


def reverse_ciudad(pais, ciudad):
    from django.urls import reverse
    return reverse('psicologos_en_ciudad', args=[pais.slug, ciudad.slug])


def reverse_especialidad(pais, especialidad):
    from django.urls import reverse
    return reverse('psicologos_por_especialidad', args=[pais.slug, especialidad.slug])
