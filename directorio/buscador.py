"""Lógica del buscador de profesionales de cada país: búsqueda por palabras,
filtros, orden, "pills" de filtros activos y sugerencias del autocompletado.

Se resuelve en Python (y no en SQL) porque `publicado` no es un campo de la base
y porque la búsqueda tiene que ignorar tildes y mayúsculas ("psicologo" encuentra
"Psicólogo"), cosa que SQLite/Postgres no hacen igual de bien sin extensiones.
El volumen es chico: un país tiene decenas o cientos de profesionales publicados.
"""
from urllib.parse import urlencode

from .models import Ciudad, Especialidad, Orientacion, Publico
from .taxonomia import clave

# Palabras que no ayudan a buscar ("psicólogo en Lima" => solo "lima").
PALABRAS_VACIAS = {
    'psicologo', 'psicologa', 'psicologos', 'psicologas', 'psi', 'lic', 'licenciado', 'licenciada',
    'en', 'de', 'del', 'para', 'con', 'y', 'e', 'o', 'el', 'la', 'los', 'las', 'un', 'una', 'por', 'a',
    'quiero', 'busco', 'necesito', 'terapia',
}

ORDENES = [
    ('recomendados', 'Recomendados'),
    ('nombre', 'Nombre (A-Z)'),
    ('precio_asc', 'Menor precio'),
    ('precio_desc', 'Mayor precio'),
]
PARAMETROS = ('q', 'modalidad', 'ciudad', 'orientacion', 'especialidad', 'publico', 'orden')
MODALIDADES = [('', 'Todas'), ('online', 'Online'), ('presencial', 'Presencial')]


def palabras(q):
    return [t for t in clave(q).split() if t not in PALABRAS_VACIAS]


def _campos(p):
    """Texto normalizado de cada parte de un perfil, para buscar y puntuar."""
    return {
        'nombre': clave(p.nombre),
        'ciudad': clave(p.ciudad_publica),
        'temas': clave(' '.join(
            [e.nombre for e in p.especialidades_publicas]
            + [o.nombre for o in p.orientaciones_publicas]
            + [pu.nombre for pu in p.publicos_publicos]
        )),
        'bio': clave(p.bio or ''),
    }


def filtrar_por_texto(psicologos, q):
    """Deja solo a quienes coinciden con TODAS las palabras (en nombre, ciudad, motivos,
    enfoques, públicos o descripción), de más a menos relevante."""
    tokens = palabras(q)
    if not tokens:
        return list(psicologos)
    puntuados = []
    for p in psicologos:
        campos = _campos(p)
        total = 0
        for t in tokens:
            if t in campos['nombre']:
                total += 5
            elif t in campos['ciudad']:
                total += 4
            elif t in campos['temas']:
                total += 3
            elif t in campos['bio']:
                total += 1
            else:
                break
        else:
            puntuados.append((total, p))
    puntuados.sort(key=lambda par: (-par[0], clave(par[1].nombre)))
    return [p for _, p in puntuados]


def ordenar(psicologos, orden, con_texto=False):
    if orden == 'nombre':
        return sorted(psicologos, key=lambda p: clave(p.nombre))
    if orden in ('precio_asc', 'precio_desc'):
        con = [p for p in psicologos if p.precio_sesion is not None]
        sin = [p for p in psicologos if p.precio_sesion is None]
        con.sort(key=lambda p: p.precio_sesion, reverse=(orden == 'precio_desc'))
        return con + sin
    if con_texto:
        return list(psicologos)   # ya vienen por relevancia
    return sorted(psicologos, key=lambda p: (not p.destacado, clave(p.nombre)))


def leer_parametros(get):
    datos = {k: (get.get(k) or '').strip() for k in PARAMETROS}
    if datos['modalidad'] not in {'online', 'presencial'}:
        datos['modalidad'] = ''
    if datos['orden'] not in {k for k, _ in ORDENES}:
        datos['orden'] = ''
    for k in ('orientacion', 'especialidad', 'publico'):
        if not datos[k].isdigit():
            datos[k] = ''   # un valor que no es un id se ignora en vez de dejar la lista vacía
    return datos


def aplicar_filtros(psicologos, datos):
    """Filtros exactos (modalidad, ciudad, orientación, motivo, público) sobre una lista ya publicada."""
    resultado = []
    for p in psicologos:
        if datos['modalidad'] and p.modalidad not in (datos['modalidad'], 'ambas'):
            continue
        if datos['ciudad'] and clave(p.ciudad_publica) != clave(datos['ciudad']):
            continue
        if datos['orientacion'] and not any(str(o.pk) == datos['orientacion'] for o in p.orientaciones_publicas):
            continue
        if datos['especialidad'] and not any(str(e.pk) == datos['especialidad'] for e in p.especialidades_publicas):
            continue
        if datos['publico'] and not any(str(pu.pk) == datos['publico'] for pu in p.publicos_publicos):
            continue
        resultado.append(p)
    return resultado


def url_con(ruta, datos, **cambios):
    """Link a la misma búsqueda con algún parámetro cambiado (o quitado con '')."""
    nuevos = {**datos, **cambios}
    qs = urlencode({k: v for k, v in nuevos.items() if v})
    return f'{ruta}?{qs}' if qs else ruta


def pills_activas(ruta, datos, nombres):
    """Lista de filtros activos, cada uno con el link que lo quita."""
    pills = []
    if datos['q']:
        pills.append({'etiqueta': f'“{datos["q"]}”', 'quitar': url_con(ruta, datos, q='')})
    if datos['modalidad']:
        pills.append({'etiqueta': dict(MODALIDADES)[datos['modalidad']], 'quitar': url_con(ruta, datos, modalidad='')})
    for clave_param, etiqueta in (('ciudad', None), ('especialidad', 'especialidad'), ('orientacion', 'orientacion'), ('publico', 'publico')):
        if datos[clave_param]:
            texto = datos[clave_param] if clave_param == 'ciudad' else nombres[etiqueta].get(datos[clave_param])
            if texto:
                pills.append({'etiqueta': texto, 'quitar': url_con(ruta, datos, **{clave_param: ''})})
    return pills


def nombres_por_id():
    return {
        'especialidad': {str(e.pk): e.nombre for e in Especialidad.objects.filter(aprobado=True)},
        'orientacion': {str(o.pk): o.nombre for o in Orientacion.objects.filter(aprobado=True)},
        'publico': {str(pu.pk): pu.nombre for pu in Publico.objects.filter(aprobado=True)},
    }


def sugerencias(publicados):
    """Datos del autocompletado: ciudades, motivos, enfoques, públicos y nombres que
    existen entre los profesionales publicados (nunca algo sin nadie adentro)."""
    ciudades, motivos, enfoques, publicos = {}, {}, {}, {}
    for p in publicados:
        if p.ciudad_publica:
            ciudades[p.ciudad_publica] = ciudades.get(p.ciudad_publica, 0) + 1
        for e in p.especialidades_publicas:
            motivos[(e.pk, e.nombre)] = motivos.get((e.pk, e.nombre), 0) + 1
        for o in p.orientaciones_publicas:
            enfoques[(o.pk, o.nombre)] = enfoques.get((o.pk, o.nombre), 0) + 1
        for pu in p.publicos_publicos:
            publicos[(pu.pk, pu.nombre)] = publicos.get((pu.pk, pu.nombre), 0) + 1
    items = []
    items += [{'t': 'ciudad', 'n': n, 'v': n, 'c': c, 'k': clave(n)} for n, c in ciudades.items()]
    items += [{'t': 'motivo', 'n': n, 'v': str(pk), 'c': c, 'k': clave(n)} for (pk, n), c in motivos.items()]
    items += [{'t': 'enfoque', 'n': n, 'v': str(pk), 'c': c, 'k': clave(n)} for (pk, n), c in enfoques.items()]
    items += [{'t': 'publico', 'n': n, 'v': str(pk), 'c': c, 'k': clave(n)} for (pk, n), c in publicos.items()]
    items += [{'t': 'profesional', 'n': p.nombre, 'v': p.nombre, 'c': 0, 'k': clave(p.nombre)} for p in publicados]
    return items


def motivos_populares(publicados, limite=8):
    """[(pk, nombre, cantidad)] de los motivos de consulta con más profesionales."""
    cuenta, nombres = {}, {}
    for p in publicados:
        for e in p.especialidades_publicas:
            cuenta[e.pk] = cuenta.get(e.pk, 0) + 1
            nombres[e.pk] = e.nombre
    orden = sorted(cuenta, key=lambda pk: (-cuenta[pk], nombres[pk]))
    return [(pk, nombres[pk], cuenta[pk]) for pk in orden[:limite]]


def ciudades_con_gente(publicados):
    return sorted({p.ciudad_publica for p in publicados if p.ciudad_publica})
