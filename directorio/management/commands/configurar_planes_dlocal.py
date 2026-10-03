from django.core.management.base import BaseCommand, CommandError

from directorio import dlocal_go, planes_dlocal


class Command(BaseCommand):
    help = (
        'Deja los planes de dLocal Go con la descripción corta (dLocal la recorta a ~100 caracteres) y con '
        'las direcciones de retorno y de aviso (success_url, error_url, back_url, notification_url) -- los '
        'planes creados a mano desde el panel no las tienen, y sin ellas el cliente no vuelve al sitio '
        'después de pagar ni dLocal nos avisa. ESCRIBE en la cuenta de dLocal Go: dry-run por defecto, '
        '--apply para cambiarlos de verdad. Solo toca lo que difiere. No cambia monto, país ni moneda.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Modifica los planes en dLocal Go (si no, solo muestra qué cambiaría)')

    def handle(self, *args, **options):
        if not dlocal_go.conectado():
            raise CommandError('Faltan DLOCAL_GO_API_KEY / DLOCAL_GO_SECRET_KEY.')
        for resultado, texto in planes_dlocal.configurar_planes(aplicar=options['apply']):
            self.stdout.write(f'  {resultado.upper()}: {texto}')
        if not options['apply']:
            self.stdout.write('\nEsto fue solo una simulación. Para aplicar los cambios: python manage.py configurar_planes_dlocal --apply')
