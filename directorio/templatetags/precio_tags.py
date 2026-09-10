from django import template

register = template.Library()


@register.filter
def miles(valor):
    """Separador de miles con punto (13990 -> "13.990"), la convención real
    en Chile y Argentina -- el locale genérico 'es' de Django usa un espacio
    como separador (django.utils.formats), que no es lo que se ve en la
    calle acá, así que se resuelve con un filtro propio en vez de USE_L10N."""
    try:
        return f'{int(valor):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return valor
