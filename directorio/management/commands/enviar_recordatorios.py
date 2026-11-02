import datetime
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from directorio import estados
from directorio.models import Psicologo

logger = logging.getLogger(__name__)

AVISO_VENCIMIENTO = datetime.timedelta(days=7)

# Seguimiento a quien todavía no publicó su perfil (esté incompleto, completo sin plan, o completo sin publicar):
# primer aviso a los 2 días de registrarse y después uno cada 3 días, hasta MAX_SEGUIMIENTOS avisos en total
# (unas dos semanas y media). Después se frena solo: no se insiste para siempre.
PRIMER_SEGUIMIENTO = datetime.timedelta(days=2)
ENTRE_SEGUIMIENTOS = datetime.timedelta(days=3)
MAX_SEGUIMIENTOS = 6
# Quedan afuera: los publicados, los que no confirmaron el email y los que se les venció el período gratis
# (esos tienen su propio aviso de fin de período).
ESTADOS_CON_SEGUIMIENTO = ('sin_pago', 'incompleto', 'por_pagar', 'perfil_listo', 'listo')
PASOS_TOTALES = 6   # nombre, matrícula, WhatsApp, foto, descripción y una orientación

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
        estado_codigo__in=ESTADOS_CON_SEGUIMIENTO,
        usuario__is_active=True,          # sin confirmar el email no pueden entrar
        no_enviar_seguimiento=False,      # pausado a mano desde el admin
        seguimientos_enviados__lt=MAX_SEGUIMIENTOS,
    ).select_related('usuario', 'pais')
    return base.filter(
        Q(seguimientos_enviados=0, fecha_alta__lte=ahora - PRIMER_SEGUIMIENTO)
        | Q(seguimientos_enviados__gt=0, ultimo_seguimiento__lte=ahora - ENTRE_SEGUIMIENTOS)
    )


def _asunto(p):
    return ASUNTOS[min(p.seguimientos_enviados, len(ASUNTOS) - 1)]


def _mensaje(p):
    """Mail de seguimiento. Dice dónde quedó el perfil: qué falta, o que solo falta elegir el plan, o que ya
    puede publicarlo. Cambia el asunto con cada aviso y el último avisa que no habrá más."""
    nombre = p.nombre_corto or p.nombre
    faltan = p.faltantes_perfil
    if faltan:
        hechos = PASOS_TOTALES - len(faltan)
        cuerpo = (
            f'Todavía no completaste tu perfil, ¡pero estás muy cerca! Ya tenés {hechos} de {PASOS_TOTALES} pasos hechos. '
            f'Te falta: {", ".join(faltan)}.\n\n'
            'Mientras lo completás ves cómo te van a ver los pacientes.'
        )
        if not p.tiene_acceso:
            cuerpo += ' El plan se elige recién cuando decidas publicar; hasta ese momento no pagás nada.'
        cuerpo += '\n\nSeguí desde acá: https://atencionpsi.lat/portal/perfil/'
    elif not p.tiene_acceso:
        cuerpo = (
            'Tu perfil está completo y se ve muy bien. Falta un solo paso: elegir tu plan y publicarlo, '
            'así los pacientes empiezan a encontrarte en el buscador.\n\n'
            'Mirá cómo te ven y publicalo desde acá: https://atencionpsi.lat/portal/'
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
