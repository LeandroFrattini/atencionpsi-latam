"""Carga datos de demo para poder recorrer todo el sitio en local sin tener
que cargar países, orientaciones y profesionales a mano por /admin/.

    python manage.py seed_demo            # crea/actualiza todo (idempotente)
    python manage.py seed_demo --wipe     # borra solo lo de demo y sale

Todo lo que crea este comando queda marcado como "de demo":
  - los profesionales usan mails @demo.atencionpsi.lat
  - se los puede borrar de una con --wipe sin tocar datos reales

Los países / orientaciones / públicos se crean con get_or_create, así que si
ya existían no se duplican ni se pisan.
"""

import datetime
import io

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from directorio.models import (
    Formacion,
    Orientacion,
    Pais,
    Psicologo,
    Publico,
)
from turnos.models import DisponibilidadSemanal, Paciente, TipoSesion, Turno

DEMO_EMAIL_DOMAIN = 'demo.atencionpsi.lat'
DEMO_PASSWORD = 'DemoPsi12345'

# Datos de habilitación profesional por país -- confirmados 2026-08-11, ver
# comentarios en directorio.models.Pais.
PAISES = [
    dict(nombre='Perú', slug='peru', codigo_iso='PE', moneda='PEN', simbolo_moneda='S/',
         etiqueta_matricula='N° de Colegiatura (CPsP)', muestra_precio_sesion=True,
         activo=True, orden=1, bandera_emoji='\U0001F1F5\U0001F1EA'),
    dict(nombre='Uruguay', slug='uruguay', codigo_iso='UY', moneda='UYU', simbolo_moneda='$U',
         etiqueta_matricula='N° de Matrícula (Colegio de Psicólogos del Uruguay)',
         muestra_precio_sesion=False, activo=True, orden=2, bandera_emoji='\U0001F1FA\U0001F1FE'),
    dict(nombre='Chile', slug='chile', codigo_iso='CL', moneda='CLP', simbolo_moneda='$',
         etiqueta_matricula='N° de Registro (RNPI)', muestra_precio_sesion=False,
         activo=True, orden=3, bandera_emoji='\U0001F1E8\U0001F1F1'),
    dict(nombre='México', slug='mexico', codigo_iso='MX', moneda='MXN', simbolo_moneda='$',
         etiqueta_matricula='N° de Cédula Profesional (SEP)', muestra_precio_sesion=False,
         activo=False, orden=4, bandera_emoji='\U0001F1F2\U0001F1FD'),
    dict(nombre='Colombia', slug='colombia', codigo_iso='CO', moneda='COP', simbolo_moneda='$',
         etiqueta_matricula='N° de Tarjeta Profesional (COLPSIC)', muestra_precio_sesion=False,
         activo=False, orden=5, bandera_emoji='\U0001F1E8\U0001F1F4'),
    dict(nombre='Argentina', slug='argentina', codigo_iso='AR', moneda='ARS', simbolo_moneda='$',
         etiqueta_matricula='N° de Matrícula', muestra_precio_sesion=False,
         activo=True, orden=6, bandera_emoji='\U0001F1E6\U0001F1F7',
         es_externo=True, url_externa='https://atencionpsi.com.ar'),
]

ORIENTACIONES = [
    'Cognitivo Conductual (TCC)', 'Psicoanálisis', 'Sistémica',
    'Humanista / Gestalt', 'Integrativa', 'EMDR / Trauma', 'Terapia de Pareja',
]

PUBLICOS = [
    'Adultos', 'Adolescentes', 'Niños', 'Parejas',
    'Familias', 'Adultos mayores', 'LGBTIQ+',
]

# Profesionales de demo -- todos exentos de pago y ya "publicados" para que
# aparezcan en el buscador sin tener que pasar por el checkout.
PSICOLOGOS = [
    dict(
        slug='peru', nombre='Lucía Fernández', ciudad='Lima', modalidad='ambas',
        matricula='CPsP 12345', whatsapp='51987654321', precio_sesion='120.00',
        sesiones_atendidas=1000,
        bio='Psicóloga clínica con 12 años de experiencia. Trabajo con adultos en '
            'procesos de ansiedad, duelo y transiciones vitales.',
        docencia='Docente de la cátedra de Psicopatología en la Universidad Nacional '
                 'Mayor de San Marcos desde 2018.',
        orientaciones=['Cognitivo Conductual (TCC)', 'EMDR / Trauma'],
        publicos=['Adultos', 'Adolescentes'],
        formaciones=[
            'Licenciada en Psicología. Universidad Nacional Mayor de San Marcos',
            'Especialización en Terapia Cognitivo Conductual. PUCP',
            'Formación en EMDR Nivel I y II. Asociación EMDR Iberoamérica',
        ],
    ),
    dict(
        slug='uruguay', nombre='Martín Rodríguez', ciudad='Montevideo', modalidad='online',
        matricula='CPU 4821', whatsapp='59899123456', precio_sesion=None,
        sesiones_atendidas=500,
        bio='Acompaño a personas adultas y parejas desde un enfoque sistémico. '
            'Especial interés en vínculos y crisis de pareja.',
        docencia='',
        orientaciones=['Sistémica', 'Terapia de Pareja'],
        publicos=['Adultos', 'Parejas', 'Familias'],
        formaciones=[
            'Licenciado en Psicología. Universidad de la República (UdelaR)',
            'Posgrado en Terapia Sistémica. Instituto de Terapia Familiar de Montevideo',
        ],
    ),
    dict(
        slug='chile', nombre='Camila Torres', ciudad='Santiago', modalidad='presencial',
        matricula='RNPI 30219', whatsapp='56961234567', precio_sesion=None,
        sesiones_atendidas=2000,
        bio='Psicóloga infanto-juvenil. Trabajo con niñas, niños y adolescentes, '
            'y orientación a familias.',
        docencia='Supervisora clínica de practicantes de psicología (Universidad '
                 'Diego Portales).',
        orientaciones=['Humanista / Gestalt', 'Integrativa'],
        publicos=['Niños', 'Adolescentes', 'Familias'],
        formaciones=[
            'Psicóloga. Pontificia Universidad Católica de Chile',
            'Diplomado en Psicoterapia Infanto-Juvenil. Universidad de Chile',
        ],
    ),
]


def _imagen_placeholder():
    """JPG de 600x600 gris con Pillow -- evita que las <img> del perfil den
    404 en local. Si Pillow no estuviera, se sigue sin foto."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover
        return None
    img = Image.new('RGB', (600, 600), (214, 219, 224))
    draw = ImageDraw.Draw(img)
    draw.ellipse((180, 130, 420, 370), fill=(150, 160, 170))
    draw.rectangle((120, 400, 480, 620), fill=(150, 160, 170))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return buf.getvalue()


class Command(BaseCommand):
    help = 'Carga datos de demo (países, orientaciones, públicos y profesionales) para desarrollo local.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wipe', action='store_true',
            help='Borra solo los datos de demo (profesionales @%s y sus datos) y termina.' % DEMO_EMAIL_DOMAIN,
        )
        parser.add_argument(
            '--no-superuser', action='store_true',
            help='No crear el superusuario admin de demo.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['wipe']:
            self._wipe()
            return

        self._crear_paises()
        self._crear_taxonomias()
        self._crear_psicologos()
        if not opts['no_superuser']:
            self._crear_superuser()

        self.stdout.write(self.style.SUCCESS('\nListo. Datos de demo cargados.'))
        self.stdout.write('  Buscadores activos: /peru/  /uruguay/  /chile/')
        self.stdout.write('  Portal de un profesional de demo:')
        self.stdout.write('    usuario: lucia.fernandez@%s' % DEMO_EMAIL_DOMAIN)
        self.stdout.write('    clave:   %s' % DEMO_PASSWORD)

    # ------------------------------------------------------------------ wipe
    def _wipe(self):
        users = User.objects.filter(username__endswith='@' + DEMO_EMAIL_DOMAIN)
        n = users.count()
        # El Psicologo se borra en cascada con el User (OneToOne on_delete=CASCADE),
        # y con él sus formaciones, tipos de sesión y disponibilidad.
        users.delete()
        User.objects.filter(username='admin@' + DEMO_EMAIL_DOMAIN).delete()
        self.stdout.write(self.style.WARNING('Borrados %d profesionales de demo (+ superusuario de demo).' % n))

    # --------------------------------------------------------------- países
    def _crear_paises(self):
        for datos in PAISES:
            defaults = {k: v for k, v in datos.items() if k != 'slug'}
            pais, creado = Pais.objects.get_or_create(slug=datos['slug'], defaults=defaults)
            verbo = 'creado' if creado else 'ya existía'
            self.stdout.write('  País %s: %s' % (pais.nombre, verbo))

    # ----------------------------------------------------------- taxonomías
    def _crear_taxonomias(self):
        for i, nombre in enumerate(ORIENTACIONES, start=1):
            Orientacion.objects.get_or_create(nombre=nombre, defaults={'orden': i})
        for i, nombre in enumerate(PUBLICOS, start=1):
            Publico.objects.get_or_create(nombre=nombre, defaults={'orden': i})
        self.stdout.write('  Orientaciones: %d  ·  Públicos: %d'
                          % (Orientacion.objects.count(), Publico.objects.count()))

    # -------------------------------------------------------- profesionales
    def _crear_psicologos(self):
        img_bytes = _imagen_placeholder()

        for datos in PSICOLOGOS:
            slug_local = datos['nombre'].lower().replace(' ', '.')
            slug_local = (slug_local.replace('á', 'a').replace('é', 'e').replace('í', 'i')
                          .replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n'))
            email = '%s@%s' % (slug_local, DEMO_EMAIL_DOMAIN)
            pais = Pais.objects.get(slug=datos['slug'])

            user, _ = User.objects.get_or_create(
                username=email, defaults={'email': email, 'first_name': datos['nombre']},
            )
            user.set_password(DEMO_PASSWORD)
            user.save()

            psi, _ = Psicologo.objects.get_or_create(
                usuario=user,
                defaults={'pais': pais, 'nombre': datos['nombre'], 'matricula': datos['matricula'],
                          'whatsapp': datos['whatsapp']},
            )
            psi.pais = pais
            psi.nombre = datos['nombre']
            psi.matricula = datos['matricula']
            psi.whatsapp = datos['whatsapp']
            psi.ciudad = datos['ciudad']
            psi.modalidad = datos['modalidad']
            psi.bio = datos['bio']
            psi.docencia = datos['docencia']
            psi.precio_sesion = datos['precio_sesion']
            psi.sesiones_atendidas = datos['sesiones_atendidas']
            psi.exento_de_pago = True
            psi.suscripcion_activa = True
            psi.publicado_por_usuario = True
            if img_bytes and not psi.foto:
                psi.foto.save('demo_%s.jpg' % slug_local, ContentFile(img_bytes), save=False)
            psi.save()

            psi.orientaciones.set(Orientacion.objects.filter(nombre__in=datos['orientaciones']))
            psi.publicos.set(Publico.objects.filter(nombre__in=datos['publicos']))

            psi.formaciones.all().delete()
            for i, desc in enumerate(datos['formaciones']):
                Formacion.objects.create(psicologo=psi, descripcion=desc, orden=i)

            self._crear_agenda(psi)
            self._crear_pacientes_y_turnos(psi)

            estado = 'PUBLICADO' if psi.publicado else 'NO publicado (perfil incompleto)'
            self.stdout.write('  Psicólogo %s (%s) -> %s' % (psi.nombre, pais.codigo_iso, estado))

    def _crear_agenda(self, psi):
        """Tipos de sesión + disponibilidad lunes a viernes, para que el
        wizard de reserva de turno tenga slots reales."""
        TipoSesion.objects.get_or_create(
            psicologo=psi, nombre='Individual',
            defaults={'duracion_min': 50, 'precio': psi.precio_sesion, 'orden': 0},
        )
        TipoSesion.objects.get_or_create(
            psicologo=psi, nombre='Pareja',
            defaults={'duracion_min': 60, 'precio': None, 'orden': 1},
        )
        if not psi.disponibilidad_semanal.exists():
            for dia in range(5):  # 0=lunes .. 4=viernes
                DisponibilidadSemanal.objects.create(
                    psicologo=psi, dia_semana=dia,
                    hora_desde=datetime.time(9, 0), hora_hasta=datetime.time(13, 0),
                )
                DisponibilidadSemanal.objects.create(
                    psicologo=psi, dia_semana=dia,
                    hora_desde=datetime.time(15, 0), hora_hasta=datetime.time(19, 0),
                )

    def _crear_pacientes_y_turnos(self, psi):
        """Un puñado de fichas de paciente con turnos (pasados y próximos)
        para que las pantallas de Turnos y Pacientes del portal tengan
        contenido. Idempotente: si ya hay turnos cargados, no hace nada."""
        if psi.turnos.exists():
            return

        tipo = psi.tipos_sesion.order_by('orden').first()
        if tipo is None:
            return

        modalidad = 'online' if psi.modalidad in ('online', 'ambas') else 'presencial'
        ahora = timezone.now()

        def _dia_habil(fecha):
            while fecha.weekday() >= 5:  # corre sábado/domingo al lunes
                fecha += datetime.timedelta(days=1)
            return fecha

        fichas = [
            dict(nombres='Sofía', apellidos='Gómez', telefono='5491133334444',
                 email='sofia.gomez@ejemplo.com', edad=34,
                 notas='Consulta inicial por ansiedad laboral. Deriva su médica clínica.',
                 turnos=[(-7, 10, 'realizado'), (7, 11, 'agendado')]),
            dict(nombres='Diego', apellidos='Pereyra', telefono='5491155556666',
                 email='diego.pereyra@ejemplo.com', edad=28, notas='',
                 turnos=[(-3, 16, 'ausente')]),
            dict(nombres='Valentina', apellidos='Ríos', telefono='5491177778888',
                 email='valentina.rios@ejemplo.com', edad=41,
                 notas='Sesiones de pareja. Trabajar comunicación.',
                 turnos=[(-14, 9, 'realizado'), (-7, 9, 'realizado'), (2, 10, 'agendado')]),
        ]

        for f in fichas:
            paciente = Paciente.objects.create(
                psicologo=psi, nombres=f['nombres'], apellidos=f['apellidos'],
                telefono=f['telefono'], email=f['email'], edad=f['edad'], notas=f['notas'],
            )
            for offset_dias, hora, estado in f['turnos']:
                fecha = _dia_habil((ahora + datetime.timedelta(days=offset_dias)).date())
                fecha_hora = timezone.make_aware(
                    datetime.datetime.combine(fecha, datetime.time(hora, 0))
                )
                Turno.objects.create(
                    psicologo=psi, paciente=paciente, tipo_sesion=tipo, fecha_hora=fecha_hora,
                    modalidad=modalidad, estado=estado,
                    nombres=f['nombres'], apellidos=f['apellidos'],
                    telefono=f['telefono'], email=f['email'], edad=f['edad'],
                    motivo_consulta='' if estado != 'agendado' else 'Turno reservado desde el sitio.',
                )

    # ------------------------------------------------------------ superuser
    def _crear_superuser(self):
        email = 'admin@' + DEMO_EMAIL_DOMAIN
        if User.objects.filter(username=email).exists():
            self.stdout.write('  Superusuario de demo: ya existía (%s)' % email)
            return
        User.objects.create_superuser(email, email, DEMO_PASSWORD)
        self.stdout.write(self.style.SUCCESS('  Superusuario de demo creado:'))
        self.stdout.write('    /admin/  ->  %s  /  %s' % (email, DEMO_PASSWORD))
