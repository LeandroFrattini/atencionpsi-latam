from django.core.management.base import BaseCommand, CommandError

from directorio import dlocal_go, planes_dlocal


class Command(BaseCommand):
    help = (
        'Registra en el sistema los planes que ya existen en dLocal Go (creados desde su panel o con '
        'crear_planes_dlocal): se asignan a un país por su código y a Básico/Premium por su monto. '
        'Solo LEE de dLocal. Dry-run por defecto: usar --apply para guardarlos.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Guarda los planes (si no, solo muestra el plan)')

    def handle(self, *args, **options):
        if not dlocal_go.conectado():
            raise CommandError('Faltan DLOCAL_GO_API_KEY / DLOCAL_GO_SECRET_KEY.')
        for resultado, texto in planes_dlocal.importar_planes(aplicar=options['apply']):
            self.stdout.write(f'  {resultado.upper()}: {texto}')
        if not options['apply']:
            self.stdout.write('\nEsto fue solo una simulación. Para guardarlos: python manage.py importar_planes_dlocal --apply')
