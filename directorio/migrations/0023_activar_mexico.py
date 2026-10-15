import unicodedata

from django.db import migrations
from django.utils.text import slugify

# México sale al aire (2026-10-15). El país ya estaba cargado desde 0006 (inactivo,
# sin precios); acá se activa, se le ponen los precios y se carga la lista base de
# ciudades. Va por migración -- no con un shell local -- para que "manage.py migrate"
# en el build de Render lo haga también en producción (mismo motivo que 0006/0015).
#
# Precios en pesos mexicanos, sin decimales. Equivalen a unos US$14,5 (Básico) y
# US$25 (Premium) al cambio de ~17,15 MXN/USD de mediados de septiembre de 2026, que
# es lo mismo que valen hoy los planes de Chile y Uruguay (CLP 13.990 / 23.990 y
# UYU 590 / 990). Si se quieren cambiar, se editan desde el admin (País) -- pero ojo:
# los planes de dLocal Go ya creados quedan con el monto con el que se crearon.
PRECIO_BASICO = 249
PRECIO_PREMIUM = 429

# Ciudad de México (alcaldías), zona metropolitana y las ciudades más grandes del país.
# Lo que cada profesional ya haya escrito o escriba a mano entra aparte, pendiente de
# aprobación (igual que en los demás países).
CIUDADES = [
    'Ciudad de México', 'Benito Juárez', 'Cuauhtémoc', 'Miguel Hidalgo', 'Coyoacán',
    'Álvaro Obregón', 'Tlalpan', 'Iztapalapa', 'Gustavo A. Madero', 'Azcapotzalco',
    'Venustiano Carranza', 'Xochimilco', 'Iztacalco', 'Cuajimalpa de Morelos',
    'La Magdalena Contreras', 'Tláhuac', 'Milpa Alta',
    'Naucalpan de Juárez', 'Ecatepec de Morelos', 'Nezahualcóyotl', 'Tlalnepantla de Baz',
    'Huixquilucan', 'Atizapán de Zaragoza', 'Cuautitlán Izcalli', 'Toluca', 'Texcoco',
    'Guadalajara', 'Zapopan', 'San Pedro Tlaquepaque', 'Tonalá', 'Puerto Vallarta',
    'Monterrey', 'San Pedro Garza García', 'San Nicolás de los Garza', 'Guadalupe',
    'Apodaca', 'Santa Catarina', 'Escobedo',
    'Puebla', 'Cholula', 'Querétaro', 'San Juan del Río', 'León', 'Guanajuato',
    'Irapuato', 'Celaya', 'San Miguel de Allende', 'Salamanca',
    'Mérida', 'Cancún', 'Playa del Carmen', 'Tulum', 'Cozumel', 'Chetumal', 'Campeche',
    'Tijuana', 'Mexicali', 'Ensenada', 'Tecate', 'La Paz', 'Los Cabos',
    'San José del Cabo', 'Cabo San Lucas',
    'Ciudad Juárez', 'Chihuahua', 'Hermosillo', 'Ciudad Obregón', 'Nogales',
    'Culiacán', 'Mazatlán', 'Los Mochis', 'Tepic', 'Durango',
    'Saltillo', 'Torreón', 'Monclova', 'Reynosa', 'Matamoros', 'Nuevo Laredo',
    'Tampico', 'Ciudad Victoria',
    'San Luis Potosí', 'Aguascalientes', 'Zacatecas', 'Colima', 'Manzanillo',
    'Morelia', 'Uruapan', 'Zamora',
    'Veracruz', 'Xalapa', 'Boca del Río', 'Coatzacoalcos', 'Poza Rica', 'Córdoba', 'Orizaba',
    'Villahermosa', 'Oaxaca de Juárez', 'Tuxtla Gutiérrez', 'San Cristóbal de las Casas',
    'Tapachula', 'Acapulco', 'Chilpancingo', 'Cuernavaca', 'Cuautla', 'Pachuca', 'Tlaxcala',
]


def _clave(texto):
    sin_tildes = unicodedata.normalize('NFD', texto or '')
    sin_tildes = ''.join(c for c in sin_tildes if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.lower().split())


def activar(apps, schema_editor):
    Pais = apps.get_model('directorio', 'Pais')
    Ciudad = apps.get_model('directorio', 'Ciudad')

    pais, _ = Pais.objects.get_or_create(
        slug='mexico',
        defaults=dict(nombre='México', codigo_iso='MX', bandera_emoji='🇲🇽', moneda='MXN', orden=5),
    )
    Pais.objects.filter(pk=pais.pk).update(
        activo=True, es_externo=False, moneda='MXN', simbolo_moneda='$', codigo_telefono='52',
        etiqueta_matricula='N° de Cédula Profesional',
        precio_basico=PRECIO_BASICO, precio_premium=PRECIO_PREMIUM,
    )

    existentes = {_clave(n) for n in Ciudad.objects.filter(pais=pais).values_list('nombre', flat=True)}
    slugs = set(Ciudad.objects.filter(pais=pais).values_list('slug', flat=True))
    for nombre in CIUDADES:
        if _clave(nombre) in existentes:
            continue
        base = slugify(nombre) or 'ciudad'
        slug, n = base, 2
        while slug in slugs:
            slug, n = f'{base}-{n}', n + 1
        Ciudad.objects.create(pais=pais, nombre=nombre, slug=slug, aprobado=True)
        existentes.add(_clave(nombre))
        slugs.add(slug)


def desactivar(apps, schema_editor):
    # Solo se vuelve a ocultar el país (las ciudades quedan: borrarlas podría
    # llevarse puesto lo que ya usen los profesionales).
    apps.get_model('directorio', 'Pais').objects.filter(slug='mexico').update(
        activo=False, precio_basico=0, precio_premium=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0022_visitas'),
    ]

    operations = [
        migrations.RunPython(activar, desactivar),
    ]
