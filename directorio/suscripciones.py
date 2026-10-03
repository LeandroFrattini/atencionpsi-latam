"""Sincroniza el estado de pago de los profesionales contra dLocal Go.

Por qué se consulta en vez de confiar en la redirección o en la notificación:
- Al volver de pagar, dLocal manda al navegador a success_url con nuestro
  external_id, pero esa URL la puede abrir cualquiera a mano -- no prueba que
  se haya pagado.
- La notificación (webhook) solo trae un payment_id y el pago no dice a qué
  suscripción pertenece (ver docs de "Retrieve a payment").
Así que la verdad se saca de la propia API: la lista de suscripciones del plan
(con el mail de quien se suscribió) y los cobros de cada una (COMPLETED /
DECLINED / PENDING). Esto corre (a) apenas vuelve el profesional de pagar,
(b) cuando llega una notificación y (c) todos los días desde un cron
(`manage.py sincronizar_suscripciones`) -- (c) es la red de seguridad por si
una notificación se pierde, y es lo que despublica solo a quien deja de pagar.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import dlocal_go
from .models import PlanDLocal, Psicologo

logger = logging.getLogger(__name__)

EXTERNAL_ID_PREFIJO = 'psi-'


def external_id_de(psicologo):
    """Lo que se manda a dLocal al armar el link de pago (máx. 255 caracteres)."""
    return f'{EXTERNAL_ID_PREFIJO}{psicologo.pk}'


def _es_de(psicologo, suscripcion):
    email = (psicologo.usuario.email or '').strip().lower()
    cliente = (suscripcion.get('client_email') or '').strip().lower()
    if email and cliente == email:
        return True
    return external_id_de(psicologo) in {str(suscripcion.get('external_id') or ''), str(suscripcion.get('client_id') or '')}


def _aplicar(psicologo, plan_dlocal, suscripcion, ejecuciones):
    """Traduce lo que dice dLocal al estado del profesional. Devuelve uno de:
    'activa', 'en_gracia', 'declinada', 'baja', 'pendiente'."""
    ahora = timezone.now()
    ejecuciones = sorted(ejecuciones, key=lambda e: e.get('created_at') or '')
    ultima = ejecuciones[-1] if ejecuciones else None
    hubo_cobro = any(e.get('status') == 'COMPLETED' for e in ejecuciones)
    es_la_vinculada = psicologo.dlocal_subscription_id == str(suscripcion['id'])

    if not ejecuciones and suscripcion.get('status') == 'CREATED':
        return 'pendiente'  # eligió el plan pero todavía no se hizo el primer cobro

    if not suscripcion.get('active'):
        # Dada de baja (por el profesional, por nosotros o por dLocal).
        if psicologo.suscripcion_activa and es_la_vinculada:
            psicologo.suscripcion_activa = False
            psicologo.save(update_fields=['suscripcion_activa'])
        return 'baja'

    if ultima and ultima.get('status') == 'COMPLETED':
        psicologo.activar_suscripcion(dlocal_subscription_id=str(suscripcion['id']), plan=plan_dlocal.plan)
        if psicologo.pago_declinado_desde:
            psicologo.pago_declinado_desde = None
            psicologo.save(update_fields=['pago_declinado_desde'])
        return 'activa'

    if ultima and ultima.get('status') == 'DECLINED':
        if not hubo_cobro:
            return 'declinada'  # el primer pago fue rechazado: nunca estuvo activa
        if not psicologo.pago_declinado_desde:
            psicologo.pago_declinado_desde = ahora
            psicologo.save(update_fields=['pago_declinado_desde'])
        gracia = timedelta(days=settings.DLOCAL_GO_DIAS_DE_GRACIA)
        if ahora - psicologo.pago_declinado_desde > gracia:
            if psicologo.suscripcion_activa:
                psicologo.suscripcion_activa = False
                psicologo.save(update_fields=['suscripcion_activa'])
            return 'declinada'
        return 'en_gracia'

    return 'pendiente'


def sincronizar_psicologo(psicologo, suscripciones_por_plan=None):
    """Consulta dLocal y actualiza a UN profesional. `suscripciones_por_plan`
    ({plan_dlocal_id: [suscripciones]}) permite reusar listados ya pedidos
    cuando se sincroniza a mucha gente de una. Devuelve el estado
    ('activa', 'en_gracia', 'declinada', 'baja', 'pendiente'), 'exento' o
    'sin_suscripcion'. Puede lanzar DLocalError."""
    if psicologo.exento_de_pago:
        return 'exento'

    planes = list(PlanDLocal.objects.filter(pais=psicologo.pais, activo=True))
    # Primero el plan que eligió en el checkout.
    planes.sort(key=lambda p: p.plan != psicologo.plan)
    suscripciones_por_plan = suscripciones_por_plan if suscripciones_por_plan is not None else {}

    for plan in planes:
        if plan.dlocal_plan_id not in suscripciones_por_plan:
            suscripciones_por_plan[plan.dlocal_plan_id] = dlocal_go.listar_suscripciones(plan.dlocal_plan_id)
        propias = [s for s in suscripciones_por_plan[plan.dlocal_plan_id] if _es_de(psicologo, s)]
        if not propias:
            continue
        # Si se suscribió más de una vez, vale la más reciente.
        suscripcion = max(propias, key=lambda s: s.get('created_at') or '')
        ejecuciones = dlocal_go.listar_ejecuciones(plan.dlocal_plan_id, suscripcion['id'])
        return _aplicar(psicologo, plan, suscripcion, ejecuciones)
    return 'sin_suscripcion'


def sincronizar_todos():
    """Recorre todas las suscripciones de todos los planes y actualiza a quien
    corresponda. Devuelve {estado: cantidad}. Lo usa el cron diario."""
    resumen = {}
    ya_vistos = set()   # quien cambió de plan aparece en las listas de los dos
    for plan in PlanDLocal.objects.filter(activo=True).select_related('pais'):
        suscripciones = dlocal_go.listar_suscripciones(plan.dlocal_plan_id)
        cache = {plan.dlocal_plan_id: suscripciones}
        candidatos = Psicologo.objects.filter(pais=plan.pais, exento_de_pago=False).select_related('usuario')
        for psicologo in candidatos:
            if psicologo.pk in ya_vistos or not any(_es_de(psicologo, s) for s in suscripciones):
                continue
            ya_vistos.add(psicologo.pk)
            try:
                estado = sincronizar_psicologo(psicologo, cache)
            except dlocal_go.DLocalError:
                logger.exception('No se pudo sincronizar al profesional %s', psicologo.pk)
                estado = 'error'
            resumen[estado] = resumen.get(estado, 0) + 1
    return resumen
