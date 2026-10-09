import unicodedata

from django.db import migrations
from django.utils.text import slugify

# Temas de consulta: lo que la gente escribe en Google ("psicólogo para
# ansiedad"). Sembrados por migración -- no con un shell local -- para que
# 'manage.py migrate' los cree también en producción (mismo motivo que 0006 y
# 0015). Todos entran aprobados; lo que un profesional agregue a mano nace
# pendiente. Se evitan a propósito términos clínicos en desuso.
ESPECIALIDADES = [
    'Ansiedad', 'Depresión', 'Estrés y burnout', 'Autoestima', 'Duelo y pérdidas',
    'Trauma y estrés postraumático', 'Ataques de pánico', 'Fobias', 'Ansiedad social y timidez',
    'Trastorno obsesivo compulsivo (TOC)', 'TDAH', 'Autismo (TEA)', 'Insomnio y problemas de sueño',
    'Trastornos de la alimentación', 'Adicciones', 'Dependencia emocional', 'Manejo de la ira',
    'Problemas de pareja', 'Rupturas, separación y divorcio', 'Problemas familiares',
    'Crianza y orientación a padres', 'Adolescencia', 'Infancia', 'Violencia y abuso',
    'Bullying y acoso', 'Estrés laboral', 'Estrés académico', 'Crisis y cambios de vida',
    'Regulación emocional', 'Habilidades sociales', 'Soledad', 'Sexualidad',
    'Diversidad sexual y de género (LGBTIQ+)', 'Trastornos de personalidad', 'Trastorno bipolar',
    'Autolesiones y prevención del suicidio', 'Enfermedades crónicas y psicooncología',
    'Embarazo, posparto y maternidad', 'Duelo migratorio', 'Rendimiento deportivo',
    'Orientación vocacional', 'Evaluación psicológica y neuropsicológica',
]


def _clave(texto):
    sin_tildes = unicodedata.normalize('NFD', texto or '')
    sin_tildes = ''.join(c for c in sin_tildes if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.lower().split())


def cargar(apps, schema_editor):
    Ciudad = apps.get_model('directorio', 'Ciudad')
    Especialidad = apps.get_model('directorio', 'Especialidad')

    # 1) Slug para las ciudades que ya existen (única por país).
    usados = set()
    for ciudad in Ciudad.objects.all().order_by('pais_id', 'id'):
        if ciudad.slug:
            usados.add((ciudad.pais_id, ciudad.slug))
            continue
        base = slugify(ciudad.nombre) or 'ciudad'
        slug, n = base, 2
        while (ciudad.pais_id, slug) in usados:
            slug, n = f'{base}-{n}', n + 1
        ciudad.slug = slug
        ciudad.save(update_fields=['slug'])
        usados.add((ciudad.pais_id, slug))

    # 2) Lista base de especialidades (sin duplicar si ya hubiera alguna).
    existentes = {_clave(n) for n in Especialidad.objects.values_list('nombre', flat=True)}
    slugs = set(Especialidad.objects.values_list('slug', flat=True))
    for nombre in ESPECIALIDADES:
        if _clave(nombre) in existentes:
            continue
        base = slugify(nombre)
        slug, n = base, 2
        while slug in slugs:
            slug, n = f'{base}-{n}', n + 1
        Especialidad.objects.create(nombre=nombre, slug=slug, aprobado=True)
        existentes.add(_clave(nombre))
        slugs.add(slug)


def descargar(apps, schema_editor):
    # Solo se deshace lo sembrado de especialidades que nadie usa todavía.
    Especialidad = apps.get_model('directorio', 'Especialidad')
    Especialidad.objects.filter(psicologos__isnull=True, propuesto_por__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('directorio', '0017_especialidades_y_slugs'),
    ]

    operations = [
        migrations.RunPython(cargar, descargar),
    ]
