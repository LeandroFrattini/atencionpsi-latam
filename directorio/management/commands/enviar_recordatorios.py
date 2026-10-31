import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from directorio.models import Psicologo

VENTANA = datetime.timedelta(hours=24)
VENTANA_PERFIL_SIN_PLAN = datetime.timedelta(days=2)
VENTANA_SEGUNDO_AVISO = datetime.timedelta(days=7)
AVISO_VENCIMIENTO = datetime.timedelta(days=7)


def _cierre():
    texto = 'Cualquier cosa, respondé este mail'
    if settings.CONTACTO_TELEFONO:
        texto += f' o escribinos por WhatsApp al {settings.CONTACTO_TELEFONO}'
    return texto + '.'


def _mensaje_casi_listo(p):
    """Mail de los 2 días. Si el perfil ya está completo, solo falta elegir el plan y publicar; si no,
    se le dice exactamente qué le falta. En los dos casos se aclara que el plan se elige al final."""
    nombre = p.nombre_corto or p.nombre
    faltan = p.faltantes_perfil
    if faltan:
        cuerpo = (
            'Empezaste a armar tu perfil en Atención Psi y ya tenés buena parte hecha. '
            f'Para poder publicarlo te falta: {", ".join(faltan)}.\n\n'
            'Podés completarlo con calma y, mientras escribís, ves cómo te van a ver los pacientes. '
            'El plan se elige recién cuando decidas publicar.\n\n'
            'Seguí desde acá: https://atencionpsi.lat/portal/perfil/\n\n'
        )
    else:
        cuerpo = (
            'Tu perfil en Atención Psi está completo y se ve muy bien. Falta un solo paso: '
            'elegir tu plan y publicarlo, así los pacientes empiezan a encontrarte en el buscador.\n\n'
            'Mirá cómo te ven y publicalo desde acá: https://atencionpsi.lat/portal/\n\n'
        )
    return f'Hola {nombre},\n\n' + cuerpo + _cierre()


def _mensaje_segundo_aviso(p):
    """Mail de los 7 días, para quien ya recibió el primero y sigue sin plan. Más corto y sin presión:
    recuerda dónde quedó y que el plan se elige recién al publicar."""
    nombre = p.nombre_corto or p.nombre
    faltan = p.faltantes_perfil
    if faltan:
        cuerpo = (
            'Pasó una semana desde que armaste tu cuenta en Atención Psi y tu perfil todavía está en borrador. '
            f'Para poder publicarlo te falta: {", ".join(faltan)}.\n\n'
            'Lleva unos minutos y no pagás nada hasta el momento de publicar.\n\n'
            'Retomalo desde acá: https://atencionpsi.lat/portal/perfil/\n\n'
        )
    else:
        cuerpo = (
            'Tu perfil en Atención Psi quedó completo pero todavía no está publicado, así que los pacientes '
            f'de {p.pais.nombre} no pueden encontrarte en el buscador.\n\n'
            'Cuando quieras, elegí tu plan y publicalo; en cuanto se confirme el pago aparece solo.\n\n'
            'Entrá desde acá: https://atencionpsi.lat/portal/\n\n'
        )
    return f'Hola {nombre},\n\n' + cuerpo + _cierre()


class Command(BaseCommand):
    help = (
        'Manda recordatorios a profesionales que se registraron pero no terminaron '
        'de pagar, o que pagaron pero no completaron y publicaron el perfil. '
        'Corre dry-run por defecto: usar --apply para mandar los mails de verdad. '
        'Pensado para correr una vez por día (Render Cron Job).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Manda los mails de verdad (si no, solo muestra el plan)')

    def handle(self, *args, **options):
        aplicar = options['apply']
        ahora = timezone.now()
        limite = ahora - VENTANA

        # Se registraron, confirmaron el email y a los 2 días todavía no tienen plan: el mail depende de
        # cuánto avanzaron (si falta completar el perfil, o si ya está listo y solo falta elegir el plan).
        pendientes_pago = Psicologo.objects.filter(
            suscripcion_activa=False,
            exento_de_pago=False,
            gratis_hasta__isnull=True,   # los fundadores no deben nada hasta que venza
            recordatorio_pago_enviado=False,
            usuario__is_active=True,     # sin confirmar el email no pueden entrar: no tiene sentido invitarlos a completar
            fecha_alta__lte=ahora - VENTANA_PERFIL_SIN_PLAN,
        ).select_related('usuario', 'pais')
        pendientes_perfil = Psicologo.objects.filter(
            publicado_por_usuario=False,
            recordatorio_perfil_enviado=False,
            fecha_pago_confirmado__isnull=False,
            fecha_pago_confirmado__lte=limite,
        )

        # Segundo aviso: ya recibieron el primero y siguen sin plan a los 7 días. Se arma como lista ya
        # ahora (antes de mandar los primeros) para que nadie reciba los dos en la misma corrida.
        segundo_aviso = list(Psicologo.objects.filter(
            suscripcion_activa=False,
            exento_de_pago=False,
            gratis_hasta__isnull=True,
            recordatorio_pago_enviado=True,
            recordatorio_pago_2_enviado=False,
            usuario__is_active=True,
            fecha_alta__lte=ahora - VENTANA_SEGUNDO_AVISO,
        ).select_related('usuario', 'pais'))
        pendientes_pago = list(pendientes_pago)

        por_vencer = Psicologo.objects.filter(
            suscripcion_activa=False,
            exento_de_pago=False,
            recordatorio_vencimiento_enviado=False,
            gratis_hasta__gt=ahora,
            gratis_hasta__lte=ahora + AVISO_VENCIMIENTO,
        )

        self.stdout.write(self.style.MIGRATE_HEADING('Recordatorio de perfil casi listo (sin plan)'))
        for p in pendientes_pago:
            self.stdout.write(f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- se registró el {p.fecha_alta:%d/%m %H:%M}')
            if aplicar:
                send_mail(
                    subject='Tu perfil en Atención Psi está casi listo',
                    message=_mensaje_casi_listo(p),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_pago_enviado = True
                p.save(update_fields=['recordatorio_pago_enviado'])

        self.stdout.write(self.style.MIGRATE_HEADING('Segundo aviso de perfil casi listo (7 días)'))
        for p in segundo_aviso:
            self.stdout.write(f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- se registró el {p.fecha_alta:%d/%m %H:%M}')
            if aplicar:
                send_mail(
                    subject='¿Retomamos tu perfil en Atención Psi?',
                    message=_mensaje_segundo_aviso(p),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_pago_2_enviado = True
                p.save(update_fields=['recordatorio_pago_2_enviado'])

        self.stdout.write(self.style.MIGRATE_HEADING('Recordatorio de perfil sin publicar'))
        for p in pendientes_perfil:
            self.stdout.write(f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- pagó el {p.fecha_pago_confirmado:%d/%m %H:%M}')
            if aplicar:
                send_mail(
                    subject='Completá tu perfil y publicalo',
                    message=(
                        f'Hola {p.nombre},\n\n'
                        'Ya activaste tu suscripción en Atención Psi, pero tu perfil todavía no está '
                        'publicado en el buscador.\n\n'
                        f'Entrá a tu cuenta, completá los datos que falten y tocá "Publicar mi perfil": '
                        'https://atencionpsi.lat/portal/\n\n'
                        + _cierre()
                    ),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_perfil_enviado = True
                p.save(update_fields=['recordatorio_perfil_enviado'])

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

        total = len(pendientes_pago) + len(segundo_aviso) + pendientes_perfil.count() + por_vencer.count()
        if aplicar:
            self.stdout.write(self.style.SUCCESS(f'Listo, se mandaron {total} recordatorios.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'Esto fue solo una simulación (dry-run) -- {total} recordatorios sin mandar. '
                'Para mandarlos de verdad: python manage.py enviar_recordatorios --apply'
            ))
