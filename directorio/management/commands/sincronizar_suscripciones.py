from django.core.management.base import BaseCommand, CommandError

from directorio import dlocal_go, suscripciones


class Command(BaseCommand):
    help = (
        'Sincroniza con dLocal Go el estado de pago de los profesionales: activa a quien ya pagó, '
        'y despublica solo a quien se dio de baja o lleva más de DLOCAL_GO_DIAS_DE_GRACIA con el '
        'cobro rechazado. Pensado para correr una vez por día (Render Cron Job): es la red de '
        'seguridad por si una notificación se pierde. No tiene dry-run porque solo LEE de dLocal; '
        'lo único que escribe es el estado de pago de cada profesional.'
    )

    def handle(self, *args, **options):
        if not dlocal_go.conectado():
            raise CommandError('Faltan DLOCAL_GO_API_KEY / DLOCAL_GO_SECRET_KEY.')
        resumen = suscripciones.sincronizar_todos()
        if not resumen:
            self.stdout.write('No hay suscripciones para sincronizar.')
        for estado, cantidad in sorted(resumen.items()):
            self.stdout.write(f'  {estado}: {cantidad}')
