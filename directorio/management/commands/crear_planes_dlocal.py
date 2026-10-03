from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from directorio import dlocal_go
from directorio.models import Pais, PlanDLocal, Psicologo

DESCRIPCIONES = {
    'basico': 'Perfil publicado y optimizado para Google en el buscador de Atención Psi {pais}.',
    'premium': 'Perfil publicado, agenda de turnos online y difusión paga de Atención Psi en {pais}.',
}


class Command(BaseCommand):
    help = (
        'Crea en dLocal Go los planes de suscripción mensual (Básico y Premium) de cada país '
        'activo, en moneda local, y guarda sus links de pago. Es seguro correrlo de nuevo: '
        'solo crea los que faltan. Dry-run por defecto: usar --apply para crearlos de verdad '
        '(OJO: crea planes REALES en la cuenta a la que apuntan las claves cargadas; con claves '
        'de producción son planes de producción).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Crea los planes de verdad (si no, solo muestra el plan)')

    def handle(self, *args, **options):
        aplicar = options['apply']
        if aplicar and not dlocal_go.conectado():
            raise CommandError('Faltan DLOCAL_GO_API_KEY / DLOCAL_GO_SECRET_KEY.')

        site = settings.SITE_URL.rstrip('/')
        self.stdout.write(f'API: {settings.DLOCAL_GO_API_BASE}   Sitio: {site}')
        creados = 0
        for pais in Pais.objects.filter(activo=True, es_externo=False).order_by('orden'):
            for plan, etiqueta in Psicologo.PLAN_CHOICES:
                monto = pais.precio_basico if plan == 'basico' else pais.precio_premium
                prefijo = f'{pais.nombre} - Plan {etiqueta}: {pais.moneda} {monto}/mes'
                if not monto:
                    self.stdout.write(f'  OMITIDO (sin precio cargado) {prefijo}')
                    continue
                if PlanDLocal.objects.filter(pais=pais, plan=plan).exists():
                    self.stdout.write(f'  YA EXISTE {prefijo}')
                    continue
                if not aplicar:
                    self.stdout.write(f'  CREARÍA {prefijo}')
                    continue
                respuesta = dlocal_go.crear_plan(
                    nombre=f'Atención Psi {pais.nombre} - {etiqueta}',
                    descripcion=DESCRIPCIONES[plan].format(pais=pais.nombre),
                    pais_iso=pais.codigo_iso,
                    moneda=pais.moneda,
                    monto=monto,
                    success_url=site + reverse('portal_checkout_retorno'),
                    error_url=site + reverse('portal_checkout') + '?error=1',
                    back_url=site + reverse('portal_checkout'),
                    notification_url=site + reverse('portal_dlocal_webhook'),
                )
                PlanDLocal.objects.create(
                    pais=pais, plan=plan, dlocal_plan_id=respuesta['id'], plan_token=respuesta['plan_token'],
                    subscribe_url=respuesta['subscribe_url'], monto=monto, moneda=pais.moneda,
                )
                creados += 1
                self.stdout.write(self.style.SUCCESS(f'  CREADO {prefijo} -> {respuesta["subscribe_url"]}'))
        if not aplicar:
            self.stdout.write('\nEsto fue solo una simulación. Para crear los planes de verdad: python manage.py crear_planes_dlocal --apply')
        else:
            self.stdout.write(f'\nListo, {creados} plan(es) creado(s).')
