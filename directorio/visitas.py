"""Resúmenes de visitas: para cada profesional en su cuenta y para el reporte del admin."""
import datetime

from django.db.models import Sum
from django.utils import timezone

from .models import Psicologo, Visita, VisitaPerfil


def _total(qs):
    return qs.aggregate(t=Sum('cantidad'))['t'] or 0


def resumen_perfil(psicologo):
    """Visitas reales al perfil de un profesional: hoy, 7 días, 30 días, total y día por día."""
    hoy = timezone.localdate()
    propias = VisitaPerfil.objects.filter(psicologo=psicologo)
    por_dia = dict(propias.filter(fecha__gte=hoy - datetime.timedelta(days=6)).values_list('fecha', 'cantidad'))
    return {
        'hoy': por_dia.get(hoy, 0),
        'siete': _total(propias.filter(fecha__gte=hoy - datetime.timedelta(days=6))),
        'treinta': _total(propias.filter(fecha__gte=hoy - datetime.timedelta(days=29))),
        'total': _total(propias),
        'dias': [(hoy - datetime.timedelta(days=i), por_dia.get(hoy - datetime.timedelta(days=i), 0)) for i in range(6, -1, -1)],
    }


def reporte_general(limite_paginas=25):
    """Para el admin: páginas más vistas, visitas por profesional y visitas por día."""
    hoy = timezone.localdate()
    desde7 = hoy - datetime.timedelta(days=6)
    desde30 = hoy - datetime.timedelta(days=29)

    paginas = {}
    for fecha, pagina, cantidad in Visita.objects.filter(fecha__gte=desde30).values_list('fecha', 'pagina', 'cantidad'):
        fila = paginas.setdefault(pagina, {'pagina': pagina, 'siete': 0, 'treinta': 0})
        fila['treinta'] += cantidad
        if fecha >= desde7:
            fila['siete'] += cantidad
    top = sorted(paginas.values(), key=lambda f: (-f['treinta'], f['pagina']))[:limite_paginas]

    por_psicologo = {}
    for psicologo_id, fecha, cantidad in VisitaPerfil.objects.values_list('psicologo_id', 'fecha', 'cantidad'):
        fila = por_psicologo.setdefault(psicologo_id, {'siete': 0, 'treinta': 0, 'total': 0})
        fila['total'] += cantidad
        if fecha >= desde30:
            fila['treinta'] += cantidad
        if fecha >= desde7:
            fila['siete'] += cantidad
    profesionales = []
    for p in Psicologo.objects.select_related('pais').order_by('nombre'):
        fila = por_psicologo.get(p.pk, {'siete': 0, 'treinta': 0, 'total': 0})
        profesionales.append({'psicologo': p, 'publicado': p.publicado, **fila})
    profesionales.sort(key=lambda f: (-f['treinta'], -f['total'], f['psicologo'].nombre))

    por_dia = dict(
        Visita.objects.filter(fecha__gte=hoy - datetime.timedelta(days=13)).values('fecha').annotate(t=Sum('cantidad')).values_list('fecha', 't')
    )
    dias = [(hoy - datetime.timedelta(days=i), por_dia.get(hoy - datetime.timedelta(days=i), 0)) for i in range(13, -1, -1)]
    return {'paginas': top, 'profesionales': profesionales, 'dias': dias}
