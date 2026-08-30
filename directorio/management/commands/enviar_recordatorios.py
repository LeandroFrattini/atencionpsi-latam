import datetime

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from directorio.models import Psicologo

VENTANA = datetime.timedelta(hours=24)


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

        pendientes_pago = Psicologo.objects.filter(
            suscripcion_activa=False,
            exento_de_pago=False,
            recordatorio_pago_enviado=False,
            fecha_alta__lte=limite,
        )
        pendientes_perfil = Psicologo.objects.filter(
            publicado_por_usuario=False,
            recordatorio_perfil_enviado=False,
            fecha_pago_confirmado__isnull=False,
            fecha_pago_confirmado__lte=limite,
        )

        self.stdout.write(self.style.MIGRATE_HEADING('Recordatorio de pago pendiente'))
        for p in pendientes_pago:
            self.stdout.write(f'  {p.nombre} <{p.usuario.email}> ({p.pais.nombre}) -- se registró el {p.fecha_alta:%d/%m %H:%M}')
            if aplicar:
                send_mail(
                    subject='Terminá de activar tu perfil en Atención Psi',
                    message=(
                        f'Hola {p.nombre},\n\n'
                        'Empezaste a crear tu perfil en Atención Psi pero todavía no activaste tu suscripción. '
                        'Sin eso tu perfil no se puede publicar.\n\n'
                        f'Entrá a tu cuenta para terminar: https://atencionpsi.lat/portal/checkout/\n\n'
                        'Cualquier cosa, respondé este mail.'
                    ),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_pago_enviado = True
                p.save(update_fields=['recordatorio_pago_enviado'])

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
                        'Cualquier cosa, respondé este mail.'
                    ),
                    from_email=None,
                    recipient_list=[p.usuario.email],
                )
                p.recordatorio_perfil_enviado = True
                p.save(update_fields=['recordatorio_perfil_enviado'])

        total = pendientes_pago.count() + pendientes_perfil.count()
        if aplicar:
            self.stdout.write(self.style.SUCCESS(f'Listo, se mandaron {total} recordatorios.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'Esto fue solo una simulación (dry-run) -- {total} recordatorios sin mandar. '
                'Para mandarlos de verdad: python manage.py enviar_recordatorios --apply'
            ))
