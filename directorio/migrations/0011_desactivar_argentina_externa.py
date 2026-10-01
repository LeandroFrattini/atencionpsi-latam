from django.db import migrations

# dLocal Go pidió auditar el sitio sin el link a atencionpsi.com.ar en el
# medio (2026-10-01): como Argentina está marcada "es_externo", la bandera
# del hub y del selector de país mandan afuera, a un proyecto totalmente
# aparte -- y un auditor manual que la toca termina revisando otro sitio sin
# darse cuenta. Se desactiva (no se borra) mientras dura la revisión; se
# puede reactivar con un update o desde /admin/ apenas dLocal Go confirme.


def desactivar_argentina(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Pais.objects.filter(slug='argentina').update(activo=False)


def reactivar_argentina(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Pais.objects.filter(slug='argentina').update(activo=True)


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0010_psicologo_plan_psicologo_terminos_aceptados_en'),
    ]

    operations = [
        migrations.RunPython(desactivar_argentina, reactivar_argentina),
    ]
