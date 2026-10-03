import unicodedata

from django.db import migrations

# Listas iniciales (2026-10-02). Se cargan por migración -- no con un shell
# local -- para que "manage.py migrate" en Render las cree también en
# producción (mismo motivo que 0006_seed_paises). Todo entra aprobado: es la
# lista base; lo que escriban los profesionales a mano entra pendiente.
#
# Se compara sin tildes ni mayúsculas contra lo que ya exista (en producción
# puede haber orientaciones/públicos cargados a mano antes de esta migración)
# para no duplicar "Psicoanálisis" / "Psicoanalisis".

ORIENTACIONES = [
    'Psicoanálisis', 'Cognitivo Conductual (TCC)', 'Sistémica', 'Tercera Ola',
    'Integrativa', 'Humanista / Existencial', 'Perinatal',
    'Gestalt', 'EMDR / Trauma', 'Terapia de Pareja', 'Terapia Familiar',
    'Terapia Breve / Estratégica', 'Constructivista', 'Junguiana (Psicología Analítica)',
    'Psicodrama', 'Terapia Dialéctica Conductual (DBT)', 'Terapia de Aceptación y Compromiso (ACT)',
    'Mindfulness', 'Neuropsicología', 'Psicooncología', 'Psicología de la Salud',
    'Psicología del Deporte', 'Psicología Clínica Infantil', 'Sexología Clínica',
    'Duelo y Pérdidas', 'Adicciones', 'Trastornos de la Alimentación',
    'Psicología Forense', 'Psicología Educativa', 'Orientación Vocacional',
    'Coaching y Desarrollo Personal',
]

PUBLICOS = [
    'Adultos', 'Adolescentes', 'Niños', 'Parejas', 'Familias', 'Deportistas',
    'Adultos mayores', 'Jóvenes', 'Orientación a padres', 'Embarazo y posparto',
    'Personas con discapacidad', 'Comunidad LGBTIQ+', 'Profesionales de la salud',
    'Migrantes',
]

CIUDADES = {
    'peru': [
        'Lima', 'Callao', 'Miraflores', 'San Isidro', 'Santiago de Surco', 'San Borja',
        'La Molina', 'Barranco', 'Jesús María', 'Lince', 'Magdalena del Mar',
        'Pueblo Libre', 'San Miguel', 'Surquillo', 'San Juan de Lurigancho',
        'Los Olivos', 'Chorrillos', 'Ate', 'Comas', 'Villa El Salvador',
        'Arequipa', 'Trujillo', 'Chiclayo', 'Piura', 'Iquitos', 'Cusco', 'Huancayo',
        'Tacna', 'Pucallpa', 'Chimbote', 'Ica', 'Juliaca', 'Puno', 'Cajamarca',
        'Ayacucho', 'Huánuco', 'Sullana', 'Tarapoto', 'Moquegua', 'Ilo', 'Abancay',
        'Huaraz', 'Tumbes', 'Puerto Maldonado', 'Cerro de Pasco', 'Huancavelica',
        'Chachapoyas', 'Moyobamba', 'Jaén', 'Chincha Alta', 'Huacho', 'Barranca',
        'Pisco', 'Talara', 'Paita', 'Cañete', 'Tingo María', 'Bagua Grande',
    ],
    'uruguay': [
        'Montevideo', 'Ciudad de la Costa', 'Las Piedras', 'Pando', 'Barros Blancos',
        'Canelones', 'Atlántida', 'Maldonado', 'Punta del Este', 'San Carlos',
        'Piriápolis', 'Colonia del Sacramento', 'Carmelo', 'Nueva Helvecia',
        'Rosario', 'Salto', 'Paysandú', 'Rivera', 'Tacuarembó', 'Melo', 'Mercedes',
        'Minas', 'San José de Mayo', 'Durazno', 'Florida', 'Treinta y Tres',
        'Rocha', 'La Paloma', 'Chuy', 'Artigas', 'Bella Unión', 'Fray Bentos',
        'Trinidad', 'Young', 'Dolores', 'Río Branco',
    ],
    'chile': [
        'Santiago', 'Providencia', 'Las Condes', 'Ñuñoa', 'Vitacura', 'La Reina',
        'Lo Barnechea', 'Macul', 'Peñalolén', 'San Miguel', 'La Florida', 'Maipú',
        'Puente Alto', 'Estación Central', 'Recoleta', 'Independencia', 'Quilicura',
        'Huechuraba', 'San Bernardo', 'Pudahuel', 'Cerrillos', 'La Cisterna',
        'Arica', 'Iquique', 'Alto Hospicio', 'Antofagasta', 'Calama', 'Copiapó',
        'La Serena', 'Coquimbo', 'Ovalle', 'Valparaíso', 'Viña del Mar', 'Concón',
        'Quilpué', 'Villa Alemana', 'San Antonio', 'Quillota', 'Los Andes',
        'Rancagua', 'San Fernando', 'Talca', 'Curicó', 'Linares', 'Chillán',
        'Concepción', 'San Pedro de la Paz', 'Talcahuano', 'Los Ángeles',
        'Temuco', 'Villarrica', 'Pucón', 'Valdivia', 'Osorno', 'Puerto Montt',
        'Puerto Varas', 'Castro', 'Coyhaique', 'Punta Arenas',
    ],
}


def _clave(texto):
    """Minúsculas y sin tildes, para comparar nombres."""
    sin_tildes = unicodedata.normalize('NFD', texto or '')
    sin_tildes = ''.join(c for c in sin_tildes if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.lower().split())


def _cargar_nombres(Modelo, nombres):
    existentes = {_clave(n) for n in Modelo.objects.values_list('nombre', flat=True)}
    for nombre in nombres:
        if _clave(nombre) not in existentes:
            Modelo.objects.create(nombre=nombre, aprobado=True)
            existentes.add(_clave(nombre))


def cargar(apps, schema_editor):
    Orientacion = apps.get_model('directorio', 'Orientacion')
    Publico = apps.get_model('directorio', 'Publico')
    Ciudad = apps.get_model('directorio', 'Ciudad')
    Pais = apps.get_model('directorio', 'Pais')
    Psicologo = apps.get_model('directorio', 'Psicologo')

    _cargar_nombres(Orientacion, ORIENTACIONES)
    _cargar_nombres(Publico, PUBLICOS)

    for pais in Pais.objects.filter(es_externo=False):
        nombres = list(CIUDADES.get(pais.slug, []))
        # Lo que los profesionales ya tenían escrito a mano también entra
        # como opción aprobada, si no el filtro del buscador lo perdería.
        nombres += [
            c.strip() for c in Psicologo.objects.filter(pais=pais).values_list('ciudad', flat=True) if c and c.strip()
        ]
        existentes = {_clave(n) for n in Ciudad.objects.filter(pais=pais).values_list('nombre', flat=True)}
        for nombre in nombres:
            if _clave(nombre) not in existentes:
                Ciudad.objects.create(pais=pais, nombre=nombre, aprobado=True)
                existentes.add(_clave(nombre))


def descargar(apps, schema_editor):
    # Solo se deshacen las ciudades: borrar orientaciones/públicos podría
    # llevarse puestas las que ya usan los profesionales.
    apps.get_model('directorio', 'Ciudad').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0014_moderacion_taxonomia_y_ciudades'),
    ]

    operations = [
        migrations.RunPython(cargar, descargar),
    ]
