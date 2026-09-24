from django.db import migrations

# Precios calculados el 2026-09-09 en base a USD 15 (Básico) / USD 25 (Premium)
# al tipo de cambio de ese día, redondeados a un número comercialmente
# atractivo en cada moneda local. Verificado contra el precio de una sesión
# particular de psicología en cada país (fuentes: origen.pe, terapia.com.uy,
# 2x3.cl) -- en los tres países, incluso el plan Premium cuesta menos que
# una sola sesión de terapia.
PRECIOS = {
    'peru': dict(precio_basico=49, precio_premium=85),        # soles
    'uruguay': dict(precio_basico=590, precio_premium=990),   # pesos uruguayos
    'chile': dict(precio_basico=13990, precio_premium=23990), # pesos chilenos
}


def cargar_precios(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    for slug, precios in PRECIOS.items():
        Pais.objects.filter(slug=slug).update(**precios)


def borrar_precios(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    for slug in PRECIOS:
        Pais.objects.filter(slug=slug).update(precio_basico=0, precio_premium=0)


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0007_pais_precio_basico_pais_precio_premium'),
    ]

    operations = [
        migrations.RunPython(cargar_precios, borrar_precios),
    ]
