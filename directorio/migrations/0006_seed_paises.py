from django.db import migrations

# Los 6 países vivían solo en la base local (cargados a mano en algún momento),
# nunca se guardaron como dato versionado -- por eso una base nueva (como la
# de producción en Render) arranca sin ninguno y el hub muestra "Todavía no
# hay países activos". Mismo problema que ya pasó una vez con el curso de
# Belén en el proyecto de Argentina: la solución es una migración de datos
# para que "manage.py migrate" (que ya corre solo en el build de Render) la
# reproduzca en cualquier entorno.
PAISES = [
    dict(nombre='Argentina', slug='argentina', codigo_iso='AR', bandera_emoji='🇦🇷',
         moneda='ARS', simbolo_moneda='$', activo=True, orden=0, es_externo=True,
         url_externa='https://atencionpsi.com.ar', etiqueta_matricula='N° de Matrícula',
         muestra_precio_sesion=False),
    dict(nombre='Perú', slug='peru', codigo_iso='PE', bandera_emoji='🇵🇪',
         moneda='PEN', simbolo_moneda='S/', activo=True, orden=1, es_externo=False,
         url_externa='', etiqueta_matricula='N° de Colegiatura (CPsP)',
         muestra_precio_sesion=True),
    dict(nombre='Uruguay', slug='uruguay', codigo_iso='UY', bandera_emoji='🇺🇾',
         moneda='UYU', simbolo_moneda='$U', activo=True, orden=2, es_externo=False,
         url_externa='', etiqueta_matricula='N° de Matrícula',
         muestra_precio_sesion=False),
    dict(nombre='Chile', slug='chile', codigo_iso='CL', bandera_emoji='🇨🇱',
         moneda='CLP', simbolo_moneda='$', activo=True, orden=3, es_externo=False,
         url_externa='', etiqueta_matricula='N° de Registro (RNPI)',
         muestra_precio_sesion=False),
    dict(nombre='Colombia', slug='colombia', codigo_iso='CO', bandera_emoji='🇨🇴',
         moneda='COP', simbolo_moneda='$', activo=False, orden=4, es_externo=False,
         url_externa='', etiqueta_matricula='N° de Tarjeta Profesional',
         muestra_precio_sesion=False),
    dict(nombre='México', slug='mexico', codigo_iso='MX', bandera_emoji='🇲🇽',
         moneda='MXN', simbolo_moneda='$', activo=False, orden=5, es_externo=False,
         url_externa='', etiqueta_matricula='N° de Cédula Profesional',
         muestra_precio_sesion=False),
]


def cargar_paises(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    for datos in PAISES:
        Pais.objects.get_or_create(slug=datos['slug'], defaults=datos)


def borrar_paises(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Pais.objects.filter(slug__in=[p['slug'] for p in PAISES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0005_psicologo_sesiones_atendidas'),
    ]

    operations = [
        migrations.RunPython(cargar_paises, borrar_paises),
    ]
