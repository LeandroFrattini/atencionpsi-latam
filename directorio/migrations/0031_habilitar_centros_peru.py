from django.db import migrations


def habilitar(apps, schema_editor):
    apps.get_model('directorio', 'Pais').objects.filter(slug='peru').update(acepta_centros=True)


def deshabilitar(apps, schema_editor):
    apps.get_model('directorio', 'Pais').objects.filter(slug='peru').update(acepta_centros=False)


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0030_centros_especializados'),
    ]

    operations = [
        migrations.RunPython(habilitar, deshabilitar),
    ]
