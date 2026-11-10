import datetime
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from directorio import estados
from directorio.models import Psicologo

logger = logging.getLogger(__name__)

AVISO_VENCIMIENTO = datetime.timedelta(days=7)

# Seguimiento a quien todavía no publicó su perfil (esté incompleto, completo sin plan, o completo sin publicar):
# primer aviso a las 36 horas de registrarse y después uno cada 36 horas, hasta MAX_SEGUIMIENTOS avisos en total. Después se frena solo: no se insiste para siempre.
PRIMER_SEGUIMIENTO = datetime.timedelta(hours=36)
ENTRE_SEGUIMIENTOS = datetime.timedelta(hours=36)
MAX_SEGUIMIENTOS = 6
# Quedan afuera: los publicados y los que se les venció el período gratis (esos tienen su propio aviso de
# fin de período).
ESTADOS_CON_SEGUIMIENTO = ('sin_pago', 'incompleto', 'por_pagar', 'perfil_listo', 'listo')
# Quien se registró pero NUNCA confirmó el email no puede entrar: el mail de seguimiento común no le sirve. Se le
# manda otro, con un link NUEVO para confirmar (el del mail original vence a los 7 días), con el mismo ritmo de
# avisos pero menos veces: si en tres avisos no confirmó, es probable que el mail no sea suyo o no le interese.
MAX_CONFIRMACIONES = 3
PASOS_TOTALES = 6   # nombre, matrícula, WhatsApp, foto, descripción y una orientación

ASUNTOS_CONFIRMACION = [
    'Confirmá tu email para activar tu perfil en Atención Psi',
    'Tu perfil en Atención Psi te está esperando: confirmá tu email',
    'Último aviso: confirmá tu email para activar tu cuenta',
]

# Quien confirmó el email pero todavía no eligió ni pagó un plan: sin plan activo no puede armar el perfil.
ASUNTOS_PLAN = [
    'Elegí tu plan para empezar a armar tu perfil en Atención Psi',
    'Tu cuenta de Atención Psi está lista: falta activar tu plan',
    'Los pacientes todavía no pueden encontrarte en Atención Psi',
    'Tu lugar en Atención Psi sigue esperándote',
    'Seguimos acá: activá tu plan cuando quieras',
    'Último aviso sobre tu cuenta en Atención Psi',
]

ASUNTOS = [
    'Tu perfil en Atención Psi está casi listo',
    'Te falta muy poco para publicar tu perfil',
    '¿Te damos una mano para terminar tu perfil?',
    'Tu perfil en Atención Psi sigue esperándote',
    'Tu perfil todavía no está publicado',
    'Último aviso sobre tu perfil en Atención Psi',
]


def _cierre():
    texto = 'Cualquier cosa, respondé este mail'
    if settings.CONTACTO_TELEFONO:
        texto += f' o escribinos por WhatsApp al {settings.CONTACTO_TELEFONO}'
    return texto + '.'


def pendientes_de_seguimiento(ahora=None):
    """Profesionales a los que hoy les toca un aviso de seguimiento."""
    ahora = ahora or timezone.now()
    base = estados.con_estado(Psicologo.objects.all()).filter(
        Q(estado_codigo__in=ESTADOS_CON_SEGUIMIENTO, usuario__is_active=True, seguimientos_enviados__lt=MAX_SEGUIMIENTOS)
        | Q(estado_codigo='sin_confirmar', seguimientos_enviados__lt=MAX_CONFIRMACIONES),
        no_enviar_seguimiento=False,      # pausado a mano desde el admin
    ).select_related('usuario', 'pais')
    return base.filter(
        Q(seguimientos_enviados=0, fecha_alta__lte=ahora - PRIMER_SEGUIMIENTO)
        | Q(seguimientos_enviados__gt=0, ultimo_seguimiento__lte=ahora - ENTRE_SEGUIMIENTOS)
    )


def _asunto(p):
    if getattr(p, 'estado_codigo', '') == 'sin_confirmar':
        return ASUNTOS_CONFIRMACION[min(p.seguimientos_enviados, len(ASUNTOS_CONFIRMACION) - 1)]
    if p.plan_primero and not p.tiene_acceso:
        return ASUNTOS_PLAN[min(p.seguimientos_enviados, len(ASUNTOS_PLAN) - 1)]
    return ASUNTOS[min(p.seguimientos_enviados, len(ASUNTOS) - 1)]


def link_de_confirmacion(usuario):
    """Link NUEVO para confirmar el email (el mismo mecanismo que usa el registro: vence a los 7 días)."""
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    return settings.SITE_URL.rstrip('/') + reverse('portal_verificar_email', args=[uid, token])


def _siguiente_paso_tras_confirmar(p):
    if p.plan_primero:
        return ('Confirmar el email no tiene ningún costo. Una vez adentro elegís tu plan y activás tu suscripción, y recién ahí '
                'armás tu perfil con calma (podés ir guardándolo de a partes).\n\n')
    return ('Una vez adentro armás tu perfil con calma (podés ir guardándolo de a partes) y recién cuando lo publiques '
            'elegís tu plan: hasta ese momento no pagás nada.\n\n')


def _mensaje_confirmacion(p):
    nombre = p.nombre_corto or p.nombre
    final = ''
    if p.seguimientos_enviados + 1 >= MAX_CONFIRMACIONES:
        final = 'Este es el último aviso automático que te enviamos. '
    return (
        f'Hola {nombre},\n\n'
        f'Te registraste en Atención Psi {p.pais.nombre}, pero todavía no confirmaste tu email, y sin eso no podés entrar a '
        'armar tu perfil.\n\n'
        f'Confirmalo con un toque desde acá (el link dura 7 días): {link_de_confirmacion(p.usuario)}\n\n'
        + _siguiente_paso_tras_confirmar(p) +
        'Si no encontrás nuestros mails, revisá la carpeta de spam o de promociones.\n\n'
        f'{final}Si no querés recibir más estos avisos, respondé este mail y los pausamos.\n\n' + _cierre()
    )


def _mensaje(p):
    """Mail de seguimiento. Dice dónde quedó el perfil: qué falta, o que solo falta elegir el plan, o que ya
    puede publicarlo. Cambia el asunto con cada aviso y el último avisa que no habrá más."""
    if getattr(p, 'estado_codigo', '') == 'sin_confirmar':
        return _mensaje_confirmacion(p)
    nombre = p.nombre_corto or p.nombre
    faltan = p.faltantes_perfil
    if p.plan_primero and not p.tiene_acceso:
        # Cuentas nuevas: el plan va primero. Sin suscripción activa no puede armar ni publicar el perfil.
        simbolo, precio = p.pais.simbolo_moneda, p.pais.precio_basico
        desde = f' (desde {simbolo} {precio} por mes)' if precio else ''
        if not faltan:
            guardado = 'Tu perfil ya está cargado y completo: solo falta elegir tu plan' + desde + ' para publicarlo. '
        elif len(faltan) < PASOS_TOTALES:
            guardado = 'Lo que ya cargaste de tu perfil quedó guardado. Falta elegir tu plan' + desde + ' para seguir armándolo. '
        else:
            guardado = 'Tu cuenta ya está lista: falta elegir tu plan' + desde + ' y activar la suscripción. '
        cuerpo = (
            guardado + 'Apenas se confirme el pago, armás tu perfil con calma (podés ir guardándolo de a partes) y '
            'lo publicás cuando esté listo, así los pacientes empiezan a encontrarte en el buscador.\n\n'
            'Elegí tu plan desde acá: https://atencionpsi.lat/portal/checkout/'
        )
    elif faltan:
        hechos = PASOS_TOTALES - len(faltan)
        cuerpo = (
            f'Todavía no completaste tu perfil, ¡pero estás muy cerca! Ya tenés {hechos} de {PASOS_TOTALES} pasos hechos. '
            f'Te falta: {", ".join(faltan)}.\n\n'
            'Mientras lo completás ves cómo te van a ver los pacientes.'
        )
        if not p.tiene_acceso:
            cuerpo += ' El plan se elige recién cuando decidas publicar; hasta ese momento no pagás nada.'
        cuerpo += '\n\nSeguí desde acá: https://atencionpsi.lat/portal/perfil/'
    elif not p.tiene_acceso and p.publicado_por_usuario:
        # Ya tocó "Publicar" y se quedó en el pago: el link va directo a elegir el plan.
        simbolo, precio = p.pais.simbolo_moneda, p.pais.precio_basico
        desde = f' (desde {simbolo} {precio} por mes)' if precio else ''
        cuerpo = (
            'Tu perfil está completo y listo para publicarse: solo falta elegir tu plan' + desde + '. '
            'En cuanto se confirme el pago, los pacientes empiezan a encontrarte en el buscador.\n\n'
            'Elegí tu plan desde acá: https://atencionpsi.lat/portal/checkout/'
        )
    elif not p.tiene_acceso:
        cuerpo = (
            'Tu perfil está completo y se ve muy bien. Falta un solo paso: tocar "Guardar y publicar" y elegir tu plan, '
            'así los pacientes empiezan a encontrarte en el buscador. Hasta ese momento no pagás nada.\n\n'
            'Mirá cómo te ven y publicalo desde acá: https://atencionpsi.lat/portal/perfil/'
        )
    else:
        cuerpo = (
            'Tu perfil está completo y ya podés publicarlo: entrá y tocá "Publicar mi perfil" para que los '
            'pacientes empiecen a encontrarte en el buscador.\n\n'
            'Entrá desde acá: https://atencionpsi.lat/portal/'
        )
    final = ''
    if p.seguimientos_enviados + 1 >= MAX_SEGUIMIENTOS:
        final = 'Este es el último aviso automático que te enviamos. '
    return (
        f'Hola {nombre},\n\n{cuerpo}\n\n{final}'
        'Si no querés recibir más estos avisos, respondé este mail y los pausamos.\n\n' + _cierre()
    )


class Command(BaseCommand):
    help = (
        'Manda recordatorios por mail: seguimiento a quien todavía no publicó su perfil (un aviso a los 2 días y '
        'después uno cada 3, hasta 6) y el aviso de fin del período de fundador. '
        'Corre dry-run por defecto: usar --apply para mandar los mails de verdad.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Manda los mails de verdad (si no, solo muestra el plan)')

    def handle(self, *args, **options):
        aplicar = options['apply']
        ahora = timezone.now()

        # Se arma la lista antes de mandar: lo que se manda en esta corrida no entra de nuevo en ella.
        seguimiento = list(pendientes_de_seguimiento(ahora))
        por_vencer = list(Psicologo.objects.filter(
            suscripcion_activa=False,
            exento_de_pago=False,
            recordatorio_vencimiento_enviado=False,
            gratis_hasta__gt=ahora,
            gratis_hasta__lte=ahora + AVISO_VENCIMIENTO,
        ).select_related('usuario', 'pais'))

        fallos = 0
        self.stdout.write(self.style.MIGRATE_HEADING('Seguimiento de perfiles sin publicar'))
        for p in seguimiento:
            numero = p.seguimientos_enviados + 1
            etiqueta = estados.ETIQUETAS.get(p.estado_codigo, p.estado_codigo)
            self.stdout.write(
                f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- aviso {numero} de {MAX_SEGUIMIENTOS} -- {etiqueta}'
            )
            if not aplicar:
                continue
            try:
                send_mail(subject=_asunto(p), message=_mensaje(p), from_email=None, recipient_list=[p.usuario.email])
            except Exception:
                # Un mail que falla (casilla inexistente, problema del proveedor) no frena a los demás ni se cuenta.
                fallos += 1
                logger.exception('No se pudo mandar el seguimiento a %s', p.usuario.email)
                self.stdout.write(self.style.ERROR(f'    (no se pudo mandar a {p.usuario.email})'))
                continue
            p.seguimientos_enviados = numero
            p.ultimo_seguimiento = ahora
            p.save(update_fields=['seguimientos_enviados', 'ultimo_seguimiento'])

        self.stdout.write(self.style.MIGRATE_HEADING('Aviso de fin del período de fundador'))
        for p in por_vencer:
            self.stdout.write(f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- gratis hasta el {p.gratis_hasta:%d/%m}')
            if aplicar:
                send_mail(
                    subject='Tu período gratis en Atención Psi está por terminar',
                    message=(
                        f'Hola {p.nombre},\n\n'
                        f'Gracias por ser de los primeros profesionales de Atención Psi. Tu período gratis termina el '
                        f'{p.gratis_hasta:%d/%m/%Y}. Para que tu perfil siga publicado después de esa fecha, '
                        'activá tu suscripción desde tu cuenta: https://atencionpsi.lat/portal/checkout/\n\n'
                        + _cierre()
                    ),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_vencimiento_enviado = True
                p.save(update_fields=['recordatorio_vencimiento_enviado'])

        total = len(seguimiento) + len(por_vencer)
        if aplicar:
            enviados = total - fallos
            self.stdout.write(self.style.SUCCESS(f'Listo, se mandaron {enviados} recordatorios.'))
            if fallos:
                self.stdout.write(self.style.WARNING(f'{fallos} no se pudieron mandar; se reintentan en la próxima corrida.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'Esto fue solo una simulación (dry-run) -- {total} recordatorios sin mandar. '
                'Para mandarlos de verdad: python manage.py enviar_recordatorios --apply'
            ))
