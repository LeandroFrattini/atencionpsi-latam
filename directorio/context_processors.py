from .models import Pais


def paises_activos(request):
    return {'paises_activos': Pais.objects.filter(activo=True)}
