from django.db import migrations

# Decisión 2026-10-01: por ahora mostrar solo los países donde la expansión
# está realmente activa (Perú, Uruguay, Chile) -- Argentina, al estar
# marcada "es_externo", su bandera manda afuera a atencionpsi.com.ar, un
# proyecto totalmente aparte, y eso además complicó la auditoría manual de
# dLocal Go (un revisor que la toca termina mirando otro sitio sin darse
# cuenta). Se desactiva (no se borra) hasta que se retome la expansión ahí
# de verdad; se reactiva con un update o desde /admin/ cuando corresponda.


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
