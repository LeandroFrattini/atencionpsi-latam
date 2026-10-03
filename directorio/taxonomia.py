"""Orientaciones, públicos y ciudades que un profesional escribe a mano.

Lo escrito a mano NO entra directo a la lista de todos: se crea pendiente
(aprobado=False, propuesto_por=el profesional) y lo ve solo él hasta que la
dueña lo apruebe desde el admin (2026-10-02). Si lo que escribe ya existe en
la lista -- sin importar mayúsculas ni tildes -- se reusa lo que ya hay en
vez de duplicar.
"""
import unicodedata


def clave(texto):
    """Minúsculas, sin tildes ni espacios de más: "Psicoanálisis" y
    "psicoanalisis " son lo mismo."""
    sin_tildes = unicodedata.normalize('NFD', texto or '')
    sin_tildes = ''.join(c for c in sin_tildes if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.lower().split())


def buscar_o_proponer(Modelo, nombre, psicologo, **filtros):
    """Devuelve (objeto, creado_pendiente). Si ya hay uno con ese nombre
    (aprobado o pendiente de cualquiera) se reusa tal cual; si no, se crea
    pendiente a nombre de `psicologo`. `filtros` acota la búsqueda (para
    Ciudad: pais=...)."""
    nombre = ' '.join((nombre or '').split())
    if not nombre:
        return None, False
    for existente in Modelo.objects.filter(**filtros):
        if clave(existente.nombre) == clave(nombre):
            return existente, False
    nuevo = Modelo.objects.create(nombre=nombre, aprobado=False, propuesto_por=psicologo, **filtros)
    return nuevo, True
