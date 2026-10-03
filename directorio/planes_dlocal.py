"""Planes de suscripción de dLocal Go: cómo se llaman, qué dicen y cómo se
registran en el sistema.

Los planes se pueden crear desde el panel de dLocal Go o con
`manage.py crear_planes_dlocal`. En los dos casos el sistema necesita conocer
cada uno (su ID y su link de pago) para armar el checkout: de eso se ocupa
`importar_planes`.
"""
from django.conf import settings
from django.urls import reverse

from . import dlocal_go
from .models import Pais, PlanDLocal, Psicologo

# dLocal Go recorta la descripción a ~100 caracteres (verificado con los planes
# de Perú creados desde su panel, 2026-10-03). Se escribe para que entre entera.
LARGO_MAXIMO_DESCRIPCION = 100


def _etiqueta(plan):
    return dict(Psicologo.PLAN_CHOICES)[plan]


def nombre_plan(pais, plan):
    return f'Atención Psi {pais.nombre} - Plan {_etiqueta(plan)}'


def descripcion_plan(pais, plan):
    if plan == 'basico':
        return f'Perfil publicado en el buscador de Atención Psi {pais.nombre} y optimizado para Google.'
    return f'Plan Básico + agenda de turnos online + perfil destacado en la difusión paga en {pais.nombre}.'


def monto_plan(pais, plan):
    return pais.precio_basico if plan == 'basico' else pais.precio_premium


def urls_del_plan():
    """Adónde vuelve el profesional después de pagar y adónde avisa dLocal."""
    site = settings.SITE_URL.rstrip('/')
    return {
        'success_url': site + reverse('portal_checkout_retorno'),
        'error_url': site + reverse('portal_checkout') + '?error=1',
        'back_url': site + reverse('portal_checkout'),
        'notification_url': site + reverse('portal_dlocal_webhook'),
    }


def _nivel_por_monto(pais, monto_dlocal):
    """Qué nivel (Básico/Premium) es un plan de dLocal, por su monto."""
    for plan in ('basico', 'premium'):
        if monto_plan(pais, plan) and float(monto_dlocal) == float(monto_plan(pais, plan)):
            return plan
    return None


def _clasificar(remoto, paises):
    """A qué país y nivel corresponde un plan de dLocal. Devuelve
    (pais, nivel, motivo_de_omision); si no corresponde a ninguno, pais y nivel
    son None y viene el motivo."""
    if not remoto.get('active'):
        return None, None, 'está inactivo en dLocal Go.'
    pais = paises.get(remoto.get('country'))
    if not pais:
        return None, None, 'ese país no está activo en el sistema.'
    if remoto.get('currency') != pais.moneda or remoto.get('frequency_type') != 'MONTHLY':
        return None, None, f'la moneda ({pais.moneda}) o la frecuencia (mensual) no coinciden.'
    nivel = _nivel_por_monto(pais, remoto.get('amount'))
    if not nivel:
        return None, None, (
            f'el monto no coincide con el precio de ningún plan de {pais.nombre} '
            f'(Básico {pais.precio_basico}, Premium {pais.precio_premium}).'
        )
    return pais, nivel, None


def importar_planes(aplicar=False):
    """Registra en el sistema los planes que ya existen en dLocal Go. Cada plan
    se asigna a un país por su código y a un nivel por su monto (tiene que
    coincidir con el precio cargado en el país). Devuelve una lista de
    (resultado, texto) con lo que hizo o haría; no escribe en dLocal, solo lee."""
    paises = {p.codigo_iso: p for p in Pais.objects.filter(activo=True, es_externo=False)}
    informe = []
    for remoto in dlocal_go.listar_planes():
        titulo = f'{remoto.get("name")} ({remoto.get("country")} {remoto.get("currency")} {remoto.get("amount")})'
        pais, nivel, motivo = _clasificar(remoto, paises)
        if motivo:
            informe.append(('omitido', f'{titulo}: {motivo}'))
            continue
        datos = dict(
            dlocal_plan_id=remoto['id'], plan_token=remoto['plan_token'], subscribe_url=remoto['subscribe_url'],
            monto=int(float(remoto['amount'])), moneda=remoto['currency'], activo=True,
        )
        existente = PlanDLocal.objects.filter(pais=pais, plan=nivel).first()
        destino = f'Plan {_etiqueta(nivel)} de {pais.nombre}'
        if existente and all(getattr(existente, k) == v for k, v in datos.items()):
            informe.append(('igual', f'{titulo}: ya estaba registrado como {destino}.'))
            continue
        if aplicar:
            PlanDLocal.objects.update_or_create(pais=pais, plan=nivel, defaults=datos)
        hecho = 'actualizado' if existente else 'registrado'
        informe.append((hecho if aplicar else 'registraría', f'{titulo}: {hecho} como {destino}.'))
    return informe


def configurar_planes(aplicar=False):
    """Deja los planes de dLocal Go con la descripción corta y las direcciones
    de retorno/aviso correctas (los creados a mano desde el panel no las
    tienen). Solo toca lo que difiere, y solo planes que corresponden a un país
    y nivel del sistema (misma regla que importar_planes). Escribe en la cuenta
    de dLocal Go, por eso solo actúa con aplicar=True. Devuelve [(resultado, texto)]."""
    paises = {p.codigo_iso: p for p in Pais.objects.filter(activo=True, es_externo=False)}
    informe = []
    urls = urls_del_plan()
    for remoto in dlocal_go.listar_planes():
        titulo = f'{remoto.get("name")} ({remoto.get("country")} {remoto.get("currency")} {remoto.get("amount")})'
        pais, nivel, motivo = _clasificar(remoto, paises)
        if motivo:
            informe.append(('omitido', f'{titulo}: {motivo}'))
            continue
        deseado = {'description': descripcion_plan(pais, nivel), **urls}
        cambios = {k: v for k, v in deseado.items() if remoto.get(k) != v}
        if not cambios:
            informe.append(('igual', f'{titulo}: ya está bien configurado.'))
            continue
        detalle = ', '.join(sorted(cambios))
        if aplicar:
            dlocal_go.actualizar_plan(remoto['id'], **cambios)
        informe.append(('actualizado' if aplicar else 'actualizaría', f'{titulo}: {detalle}.'))
    return informe
