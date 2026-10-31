from django import template
from django.urls import reverse

from directorio.models import Ciudad, Especialidad, Orientacion, Publico

register = template.Library()


@register.simple_tag
def propuestas_pendientes():
    """Cuántas propuestas de profesionales esperan aprobación, para el aviso
    del inicio del admin. Lista vacía si no hay ninguna."""
    items = []
    for singular, plural, Modelo, url_name in (
        ('ciudad', 'ciudades', Ciudad, 'admin:directorio_ciudad_changelist'),
        ('orientación', 'orientaciones', Orientacion, 'admin:directorio_orientacion_changelist'),
        ('especialidad', 'especialidades', Especialidad, 'admin:directorio_especialidad_changelist'),
        ('público', 'públicos', Publico, 'admin:directorio_publico_changelist'),
    ):
        cantidad = Modelo.objects.filter(aprobado=False).count()
        if cantidad:
            items.append({
                'texto': f'{cantidad} {singular if cantidad == 1 else plural}',
                'url': reverse(url_name) + '?aprobado__exact=0',
            })
    return items


@register.simple_tag
def resumen_profesionales():
    """Cuadro del inicio del admin: una fila por estado y una columna por país."""
    from directorio import estados

    filas, total = estados.resumen_por_pais()
    renglones = []
    for codigo, etiqueta, explicacion, color in estados.ESTADOS:
        renglones.append({
            'codigo': codigo, 'etiqueta': etiqueta, 'explicacion': explicacion, 'color': color,
            'celdas': [{'n': f['estados'][codigo], 'pais_id': f['pais'].pk} for f in filas], 'total': total['estados'][codigo],
        })
    return {'paises': [f['pais'] for f in filas], 'totales_pais': [f['total'] for f in filas], 'total': total['total'], 'estados': renglones}
