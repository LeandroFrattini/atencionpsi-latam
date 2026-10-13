from django.db import migrations

# La migración 0011 (2026-10-01) desactivó Argentina del selector de países mientras
# duraba la revisión manual de dLocal Go. Se vuelve a mostrar (2026-10-12) a pedido de la
# dueña: su bandera lleva a atencionpsi.com.ar y sus profesionales entran al "mix" del inicio.
# Se puede volver a apagar desde Admin -> Países -> Argentina -> Activo.


def reactivar(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    pais, creado = Pais.objects.get_or_create(
        slug='argentina',
        defaults=dict(
            nombre='Argentina', codigo_iso='AR', bandera_emoji='🇦🇷', moneda='ARS', simbolo_moneda='$',
            activo=True, orden=0, es_externo=True, url_externa='https://atencionpsi.com.ar',
            etiqueta_matricula='N° de Matrícula', muestra_precio_sesion=False,
        ),
    )
    if not creado:
        pais.activo = True
        pais.es_externo = True
        if not pais.url_externa:
            pais.url_externa = 'https://atencionpsi.com.ar'
        pais.save(update_fields=['activo', 'es_externo', 'url_externa'])


def desactivar(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Pais.objects.filter(slug='argentina').update(activo=False)


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0020_instagram_y_colaborador'),
    ]

    operations = [
        migrations.RunPython(reactivar, desactivar),
    ]
