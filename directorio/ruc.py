"""Validación del RUC (Registro Único de Contribuyentes) de los centros especializados.

En Perú el RUC tiene 11 dígitos: empieza con 10 (persona natural con negocio), 15, 16, 17 (otros) o 20 (empresa) y el
último es un dígito verificador (módulo 11 con pesos 5-4-3-2-7-6-5-4-3-2). Esto descarta números inventados o con un
dígito mal tipeado, pero NO prueba que el RUC exista ni que sea del centro: eso se verifica a mano en SUNAT y se deja
tildado en la ficha («RUC verificado», que es lo que ve el público).
"""
import re

PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
PREFIJOS_PERU = ('10', '15', '16', '17', '20')
CONSULTA_SUNAT = 'https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/FrameCriterioBusquedaWeb.jsp'


def solo_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def validar_ruc_peru(texto):
    """El RUC solo con dígitos, o ValueError con un mensaje para mostrarle a quien lo escribió."""
    ruc = solo_digitos(texto)
    if len(ruc) != 11:
        raise ValueError('El RUC de Perú tiene 11 dígitos. Revisá que no falte ni sobre ninguno.')
    if ruc[:2] not in PREFIJOS_PERU:
        raise ValueError('Ese RUC no parece válido: tiene que empezar con 10 o 20 (también 15, 16 o 17).')
    suma = sum(int(d) * p for d, p in zip(ruc[:10], PESOS))
    verificador = 11 - (suma % 11)
    if verificador >= 10:
        verificador -= 10
    if int(ruc[10]) != verificador:
        raise ValueError('Ese RUC no es válido (el último dígito no coincide). Revisá que esté bien escrito.')
    return ruc


def validar_documento(pais, texto):
    """RUC del centro según el país. Perú se valida a fondo; para otros países solo que sean números razonables."""
    if getattr(pais, 'codigo_iso', '') == 'PE':
        return validar_ruc_peru(texto)
    documento = solo_digitos(texto)
    if not 6 <= len(documento) <= 20:
        raise ValueError('Escribí el número de identificación fiscal del centro, solo con números.')
    return documento
