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
