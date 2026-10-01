from django.db import migrations

CODIGOS = {
    'peru': '51',
    'uruguay': '598',
    'chile': '56',
    'mexico': '52',
    'colombia': '57',
    'argentina': '54',
}


def cargar_codigos(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    for slug, codigo in CODIGOS.items():
        Pais.objects.filter(slug=slug).update(codigo_telefono=codigo)


def borrar_codigos(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Pais.objects.filter(slug__in=CODIGOS).update(codigo_telefono='')


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0012_pais_codigo_telefono'),
    ]

    operations = [
        migrations.RunPython(cargar_codigos, borrar_codigos),
    ]
