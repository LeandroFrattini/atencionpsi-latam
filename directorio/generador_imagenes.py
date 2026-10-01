"""
Generador de historias (1080x1920) y posts de feed (1080x1350) de Instagram
por psicólogo, para usar desde el admin (ver acciones en directorio/admin.py).

Portado de atencionpsi.com.ar (profesionales/generador_imagenes.py), que ya
dejó el diseño preparado para reusarse en los sitios de otros países -- acá
se adapta al modelo multipaís: el código de teléfono sale de
`psicologo.pais.codigo_telefono` en vez de una constante fija, y los campos
de modalidad/ciudad/orientación se adaptan a los campos simples que usa este
proyecto (Psicologo.modalidad, Psicologo.ciudad, Psicologo.orientaciones) en
vez de los M2M propios que tiene el sitio de Argentina.
"""
import math
import os
import random
import re
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(_HERE, 'fonts')

# ── Configuración de marca ──────────────────────────────────────────────
# El dominio es el mismo en todos los países (no hay subdominio por país);
# el código de teléfono sí varía y se resuelve por psicólogo (ver
# _formatear_telefono). El handle de Instagram es único para toda la marca
# (settings.INSTAGRAM_URL) -- si no está cargado, la burbuja de Instagram
# directamente no se dibuja (mismo criterio que el resto del sitio: no
# mostrar un ícono/dato genérico si no hay algo real detrás).
DOMINIO_SITIO = 'atencionpsi.lat'


def _instagram_handle():
    url = (settings.INSTAGRAM_URL or '').strip().rstrip('/')
    if not url:
        return ''
    return '@' + url.rsplit('/', 1)[-1]


# ── Paleta (igual a static/css/base.css) ─────────────────────────────────
CREMA = (253, 251, 249)
BLUSH = (243, 231, 228)
VERDE = (125, 168, 123)
VERDE_OSCURO = (74, 124, 89)
ROSA = (233, 168, 166)
ROSA_OSCURO = (201, 130, 126)
TINTA = (43, 42, 40)
TINTA_SUAVE = (107, 101, 96)
BLANCO = (255, 255, 255)

W, H = 1080, 1920

# Post de feed: 1080x1350, el 4:5 que recomienda Instagram para feed (más
# superficie en el scroll que el clásico 1:1).
FEED_W, FEED_H = 1080, 1350


# ── Fuentes (variable fonts locales, sin descargas externas) ───────────────
_FONT_INSTANCES = {
    'playfair': {100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium',
                 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black'},
    'montserrat': {100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium',
                   600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black'},
}
_FONT_FILES = {'playfair': 'PlayfairDisplay.ttf', 'montserrat': 'Montserrat.ttf'}
_FONT_CACHE = {}


def _font(familia, peso, tam):
    key = (familia, peso, tam)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = os.path.join(FONTS_DIR, _FONT_FILES[familia])
    fnt = ImageFont.truetype(path, tam)
    nombre_instancia = min(_FONT_INSTANCES[familia].items(), key=lambda kv: abs(kv[0] - peso))[1]
    try:
        fnt.set_variation_by_name(nombre_instancia)
    except Exception:
        pass
    _FONT_CACHE[key] = fnt
    return fnt


def _bb(draw, text, fnt):
    return draw.textbbox((0, 0), text, font=fnt)


def _tw(draw, text, fnt):
    b = _bb(draw, text, fnt)
    return b[2] - b[0]


def _th(draw, text, fnt):
    b = _bb(draw, text, fnt)
    return b[3] - b[1]


def _wrap(draw, text, fnt, max_w):
    palabras = text.split()
    lineas, actual = [], ''
    for palabra in palabras:
        prueba = (actual + ' ' + palabra).strip()
        if _tw(draw, prueba, fnt) <= max_w:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas or [text]


def _center(draw, text, cx, y, fnt, fill):
    draw.text((cx - _tw(draw, text, fnt) // 2, y), text, font=fnt, fill=fill)


def _limpiar_nombre(nombre):
    n = (nombre or '').strip()
    if n.lower().startswith('lic.'):
        n = n[4:].strip()
    return n


def _formatear_telefono(digitos, codigo_pais):
    """
    Devuelve el teléfono con "+<código> 9 " y agrupado para leerse bien.

    Algunos profesionales cargan el WhatsApp ya con el código de país y el 9
    adelante (así funciona bien el link de WhatsApp), otros cargan solo el
    número local. Si no se detecta esto, el prefijo se termina agregando
    dos veces. Por eso primero se le saca el código de país y el 9 si ya
    los tiene, y recién ahí se arma el texto siempre igual.
    """
    n = digitos
    if codigo_pais and n.startswith(codigo_pais):
        n = n[len(codigo_pais):]
    if n.startswith('9') and len(n) > 10:
        n = n[1:]

    if len(n) == 10:
        cuerpo = f'{n[:3]} {n[3:7]}-{n[7:]}'
    elif len(n) >= 8:
        cuerpo = f'{n[:-4]}-{n[-4:]}'
    else:
        cuerpo = n
    return f'+{codigo_pais} 9 {cuerpo}' if codigo_pais else cuerpo


# ── Fondo: gradiente + manchas difuminadas + grano ─────────────────────────
def _gradiente_lineal(w, h, color_a, color_b, angulo=150):
    """
    Degradé diagonal calculado por proyección (no por rotar + recortar
    Image.linear_gradient): rotar un cuadrado con expand=True rellena las
    esquinas nuevas de negro, y al reescalar eso quedaba un parche oscuro
    con forma de rombo bien visible. Se arma en baja resolución (es un
    degradé suave) y se escala arriba, así siempre cubre el lienzo entero.
    """
    sw, sh = max(2, w // 18), max(2, h // 18)
    rad = math.radians(angulo)
    dx, dy = math.cos(rad), math.sin(rad)
    esquinas = [(0, 0), (sw, 0), (0, sh), (sw, sh)]
    proyecciones = [px * dx + py * dy for px, py in esquinas]
    p_min, p_max = min(proyecciones), max(proyecciones)
    rango = (p_max - p_min) or 1

    pequena = Image.new('RGB', (sw, sh))
    pix = pequena.load()
    for y in range(sh):
        for x in range(sw):
            t = max(0.0, min(1.0, ((x * dx + y * dy) - p_min) / rango))
            pix[x, y] = tuple(int(color_a[i] + (color_b[i] - color_a[i]) * t) for i in range(3))
    return pequena.resize((w, h), Image.Resampling.BICUBIC)


# Fondo: dos manchas orgánicas grandes (arriba a la izquierda en verde
# claro, abajo a la derecha en rosa claro) más una franja tipo ola abajo
# del todo -- mismo diseño validado en atencionpsi.com.ar, aplanado de
# curvas bezier a polígono para poder rellenarlo con Pillow.
BLOB_FONDO_1 = [
    (-60, -60), (5.4, -64.2), (68.6, -63.9), (129.0, -59.4), (186.1, -50.8),
    (239.6, -38.4), (289.0, -22.2), (333.8, -2.5), (373.5, 20.6), (407.7, 46.9),
    (435.9, 76.2), (457.7, 108.3), (472.7, 143.1), (480.2, 180.4), (480.0, 220.0),
    (474.5, 253.3), (464.8, 284.7), (451.1, 313.8), (433.8, 340.5), (413.1, 364.6),
    (389.5, 386.0), (363.1, 404.4), (334.4, 419.7), (303.6, 431.6), (271.1, 440.0),
    (237.2, 444.8), (202.1, 445.7), (166.3, 442.5), (130.0, 435.0), (97.2, 424.2),
    (67.3, 410.3), (40.3, 393.6), (16.2, 374.5), (-4.8, 353.2), (-23.0, 330.0),
    (-38.1, 305.1), (-50.3, 279.0), (-59.5, 251.7), (-65.6, 223.8), (-68.8, 195.3),
    (-68.9, 166.7), (-66.0, 138.1), (-60.0, 110.0),
]
BLOB_FONDO_2 = [
    (1140, 480), (1110.2, 473.8), (1081.0, 472.3), (1052.8, 475.0), (1025.8, 481.9),
    (1000.4, 492.4), (976.9, 506.5), (955.6, 523.8), (936.9, 543.9), (920.9, 566.7),
    (908.1, 591.8), (898.9, 619.0), (893.4, 647.9), (892.0, 678.4), (895.0, 710.0),
    (901.6, 740.6), (911.2, 768.5), (923.3, 794.1), (937.4, 817.9), (953.0, 840.3),
    (969.6, 861.9), (986.8, 883.1), (1003.9, 904.4), (1020.7, 926.2), (1036.4, 949.1),
    (1050.7, 973.4), (1063.1, 999.7), (1073.0, 1028.4), (1080.0, 1060.0), (1083.7, 1095.1),
    (1083.1, 1127.8), (1078.9, 1158.5), (1072.0, 1187.5), (1062.8, 1215.2), (1052.2, 1242.0),
    (1040.9, 1268.1), (1029.4, 1294.1), (1018.6, 1320.1), (1009.1, 1346.7), (1001.6, 1374.1),
    (996.8, 1402.7), (995.3, 1432.9), (998.0, 1465.0), (1002.6, 1488.7), (1009.1, 1510.4),
    (1017.2, 1530.3), (1026.6, 1548.5), (1037.1, 1564.9), (1048.4, 1579.8), (1060.4, 1593.1),
    (1072.7, 1605.0), (1085.1, 1615.5), (1097.3, 1624.7), (1109.2, 1632.7), (1120.4, 1639.5),
    (1130.8, 1645.2), (1140.0, 1650.0),
]
BLOB_FONDO_3 = [
    (0, 1860), (54.8, 1850.1), (108.1, 1843.5), (160.0, 1839.8), (210.8, 1838.4),
    (260.9, 1838.8), (310.3, 1840.4), (359.4, 1842.6), (408.4, 1845.0), (457.6, 1847.0),
    (507.2, 1848.0), (557.5, 1847.6), (608.7, 1845.1), (661.2, 1840.1), (715.0, 1832.0),
    (745.4, 1827.8), (774.6, 1825.5), (802.7, 1824.5), (829.8, 1824.8), (856.1, 1825.8),
    (881.7, 1827.4), (906.9, 1829.2), (931.6, 1831.0), (956.1, 1832.3), (980.5, 1832.9),
    (1005.0, 1832.5), (1029.6, 1830.7), (1054.6, 1827.3), (1080.0, 1822.0), (1080, 1920),
    (0, 1920),
]


def _escalar_puntos(puntos, sx, sy):
    return [(x * sx, y * sy) for x, y in puntos]


# Mismas dos manchas de la historia (mancha 1 arriba a la izq. ya entra sin
# tocar, mancha 2 abajo a la derecha se comprime en vertical para que quepa
# en un lienzo mucho más bajo) -- la mancha 3 ("ola" del pie) se descarta
# para el feed, pensada para un lienzo mucho más alto.
_SY_FEED = FEED_H / H
BLOB_FEED_1 = BLOB_FONDO_1
BLOB_FEED_2 = _escalar_puntos(BLOB_FONDO_2, 1.0, _SY_FEED)


def _forma_organica(canvas, puntos, color, alpha=255):
    capa = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(capa).polygon(puntos, fill=color + (alpha,))
    resultado = Image.alpha_composite(canvas.convert('RGBA'), capa).convert('RGB')
    canvas.paste(resultado, (0, 0))


def _puntos_dispersos(canvas, cantidad, x_range, y_range, color, seed, alpha_range=(15, 40), r_range=(1.0, 2.4)):
    """
    Textura de puntitos de color dispersos al azar en una región (no una
    grilla pareja -- una grilla regular se termina viendo como un
    cuadriculado en vez de una textura orgánica).
    """
    rng = random.Random(seed)
    capa = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for _ in range(cantidad):
        x, y = rng.uniform(*x_range), rng.uniform(*y_range)
        r = rng.uniform(*r_range)
        a = rng.randint(*alpha_range)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color + (a,))
    resultado = Image.alpha_composite(canvas.convert('RGBA'), capa).convert('RGB')
    canvas.paste(resultado, (0, 0))


def _arco_punteado(canvas, cx, cy, radio, color, ancho=2, n_guiones=48, alpha=70):
    capa = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    paso = 360 / n_guiones
    for i in range(n_guiones):
        if i % 2 == 0:
            continue
        ini = i * paso
        fin = ini + paso
        d.arc([cx - radio, cy - radio, cx + radio, cy + radio], ini, fin, fill=color + (alpha,), width=ancho)
    canvas.paste(capa, (0, 0), capa)


# ── Burbujas / pills ─────────────────────────────────────────────────────
def _sombra_para(size, radio_borde, alpha=26, blur=14, offset=(0, 8)):
    w, h = size
    pad = blur * 2
    capa = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(capa).rounded_rectangle(
        [pad, pad, pad + w, pad + h], radius=radio_borde, fill=TINTA + (alpha,)
    )
    capa = capa.filter(ImageFilter.GaussianBlur(blur))
    return capa, pad, offset


def _pegar_con_sombra(canvas, capa_contenido, x, y, radio_borde):
    w, h = capa_contenido.size
    sombra, pad, offset = _sombra_para((w, h), radio_borde)
    canvas.paste(sombra, (x - pad + offset[0], y - pad + offset[1]), sombra)
    canvas.paste(capa_contenido, (x, y), capa_contenido)


# Silueta real de auricular, aplanada a polígono y normalizada a 0..1 sobre
# su viewBox de 24x24 (mismo path estándar de "llamada" que atencionpsi.com.ar).
_PUNTOS_ICONO_TELEFONO = [
    (0.27583, 0.44958), (0.29492, 0.48429), (0.31611, 0.51762), (0.33932, 0.54948),
    (0.36445, 0.57978), (0.39141, 0.60844), (0.4201, 0.63537), (0.45045, 0.6605),
    (0.48234, 0.68373), (0.51569, 0.70498), (0.55042, 0.72417), (0.64208, 0.6325),
    (0.64561, 0.62935), (0.64942, 0.62666), (0.65347, 0.62443), (0.6577, 0.62268),
    (0.66208, 0.62141), (0.66656, 0.62062), (0.6711, 0.62033), (0.67564, 0.62054),
    (0.68015, 0.62126), (0.68458, 0.6225), (0.69869, 0.62691), (0.71301, 0.63089),
    (0.72753, 0.63443), (0.74222, 0.63752), (0.75708, 0.64016), (0.77209, 0.64233),
    (0.78724, 0.64403), (0.8025, 0.64526), (0.81787, 0.646), (0.83333, 0.64625),
    (0.84007, 0.6468), (0.84647, 0.64838), (0.85244, 0.65092), (0.8579, 0.65432),
    (0.86276, 0.65849), (0.86693, 0.66335), (0.87033, 0.66881), (0.87287, 0.67478),
    (0.87445, 0.68118), (0.875, 0.68792), (0.875, 0.83333), (0.87445, 0.84007),
    (0.87287, 0.84647), (0.87033, 0.85244), (0.86693, 0.8579), (0.86276, 0.86276),
    (0.8579, 0.86693), (0.85244, 0.87033), (0.84647, 0.87287), (0.84007, 0.87445),
    (0.83333, 0.875), (0.71843, 0.86573), (0.60943, 0.83889), (0.50779, 0.79595),
    (0.41498, 0.73835), (0.33245, 0.66755), (0.26165, 0.58502), (0.20405, 0.49221),
    (0.16111, 0.39057), (0.13427, 0.28157), (0.125, 0.16667), (0.12555, 0.15993),
    (0.12713, 0.15353), (0.12967, 0.14756), (0.13307, 0.1421), (0.13724, 0.13724),
    (0.1421, 0.13307), (0.14756, 0.12967), (0.15353, 0.12713), (0.15993, 0.12555),
    (0.16667, 0.125), (0.3125, 0.125), (0.31924, 0.12555), (0.32563, 0.12713),
    (0.33161, 0.12967), (0.33707, 0.13307), (0.34193, 0.13724), (0.3461, 0.1421),
    (0.3495, 0.14756), (0.35203, 0.15353), (0.35362, 0.15993), (0.35417, 0.16667),
    (0.35442, 0.18223), (0.35516, 0.19766), (0.35638, 0.21295), (0.35809, 0.22809),
    (0.36026, 0.24307), (0.3629, 0.2579), (0.36599, 0.27255), (0.36953, 0.28703),
    (0.37351, 0.30132), (0.37792, 0.31542), (0.37905, 0.31984), (0.37971, 0.32432),
    (0.37989, 0.32882), (0.37959, 0.33332), (0.3788, 0.33776), (0.37753, 0.34212),
    (0.37576, 0.34635), (0.3735, 0.35042), (0.37075, 0.35429), (0.3675, 0.35792),
    (0.27583, 0.44958),
]


def _icono_telefono(draw, cx, cy, r, color, ancho=5):
    tam = r * 2.4
    x0, y0 = cx - tam / 2, cy - tam / 2
    puntos = [(x0 + nx * tam, y0 + ny * tam) for nx, ny in _PUNTOS_ICONO_TELEFONO]
    draw.polygon(puntos, fill=color)


def _icono_ubicacion(draw, cx, cy, r, color, ancho=5):
    top = cy - r * 0.5
    rc = r * 0.62
    draw.ellipse([cx - rc, top - rc, cx + rc, top + rc], outline=color, width=ancho)
    pr = r * 0.16
    draw.ellipse([cx - pr, top - pr, cx + pr, top + pr], fill=color)
    punta = (cx, cy + r * 0.85)
    draw.line([(cx - rc * 0.72, top + rc * 0.55), punta], fill=color, width=ancho)
    draw.line([(cx + rc * 0.72, top + rc * 0.55), punta], fill=color, width=ancho)


def _icono_globo(draw, cx, cy, r, color, ancho=3):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=ancho)
    draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=ancho)
    draw.ellipse([cx - r * 0.42, cy - r, cx + r * 0.42, cy + r], outline=color, width=max(2, ancho - 1))
    draw.line([(cx, cy - r), (cx, cy + r)], fill=color, width=max(2, ancho - 1))


def _icono_instagram(draw, cx, cy, r, color, ancho=3):
    draw.rounded_rectangle(
        [cx - r, cy - r * 0.82, cx + r, cy + r * 0.82], radius=r * 0.4, outline=color, width=ancho
    )
    draw.ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], outline=color, width=ancho)
    pr = r * 0.12
    px, py = cx + r * 0.55, cy - r * 0.55
    draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=color)


def _ancho_burbuja_dato(draw, lineas_y_fuentes, icono_cx=66, icono_r=33, gap=26, margen=None):
    """
    Ancho de la burbuja calculado a partir del contenido real (ícono +
    texto más largo) en vez de un porcentaje fijo del canvas, así un texto
    corto no deja la burbuja con un montón de aire vacío a la derecha.

    margen: por defecto usa el que ya deja el ícono a la izquierda
    (icono_cx - icono_r). La burbuja de teléfono pasa un margen más
    generoso a propósito -- tiene que verse grande y prominente.
    """
    if margen is None:
        margen = icono_cx - icono_r
    x_texto = icono_cx + icono_r + gap
    ancho_texto = max(_tw(draw, texto, fnt) for texto, fnt in lineas_y_fuentes)
    return x_texto + ancho_texto + margen


def _dibujar_burbuja_dato(draw_fn, ancho, alto, icono_fn, estilo='claro', icono_cx=66, icono_r=33, gap=26):
    """
    Arma en una capa aparte una burbuja con ícono + contenido (dibujado por
    draw_fn). estilo='claro' -> burbuja blanca, ícono en circulito verde
    suave. estilo='solido' -> burbuja verde llena, ícono en circulito
    blanco (para el teléfono, que tiene que resaltar más que el resto).
    """
    capa = Image.new('RGBA', (ancho, alto), (0, 0, 0, 0))
    fondo_burbuja = VERDE_OSCURO if estilo == 'solido' else BLANCO
    ImageDraw.Draw(capa).rounded_rectangle([0, 0, ancho, alto], radius=alto // 2, fill=fondo_burbuja + (255,))
    d = ImageDraw.Draw(capa)
    if estilo == 'solido':
        d.ellipse([icono_cx - icono_r, alto // 2 - icono_r, icono_cx + icono_r, alto // 2 + icono_r], fill=BLANCO)
        color_icono = VERDE_OSCURO
    else:
        d.ellipse(
            [icono_cx - icono_r, alto // 2 - icono_r, icono_cx + icono_r, alto // 2 + icono_r],
            fill=(*VERDE, 38),
        )
        color_icono = VERDE_OSCURO
    icono_fn(d, icono_cx, alto // 2, icono_r * 0.55, color_icono)
    draw_fn(d, icono_cx + icono_r + gap)
    return capa


# ── Foto / placeholder circular ─────────────────────────────────────────
def _crop_cuadrado(img, lado, foco_vertical=0.12):
    """
    Recorta a cuadrado, sesgado hacia arriba (no al centro): la mayoría de
    las fotos que suben los profesionales son de cuerpo entero o 3/4, con
    la cara en el tercio superior. Centrar el recorte dejaba medio cuerpo
    y fondo de oficina en el medallón en vez de un encuadre tipo retrato.
    """
    sw, sh = img.size
    ratio = max(lado / sw, lado / sh)
    nw, nh = int(sw * ratio), int(sh * ratio)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - lado) // 2
    top = int((nh - lado) * foco_vertical)
    top = max(0, min(nh - lado, top))
    return img.crop((left, top, left + lado, top + lado))


def _crop_rectangulo(img, ancho, alto, foco_vertical=0.15):
    """Mismo criterio que _crop_cuadrado pero a un rectángulo de proporción
    libre, para la tarjeta de foto del post de feed."""
    sw, sh = img.size
    ratio = max(ancho / sw, alto / sh)
    nw, nh = int(sw * ratio), int(sh * ratio)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - ancho) // 2
    top = int((nh - alto) * foco_vertical)
    top = max(0, min(nh - alto, top))
    return img.crop((left, top, left + ancho, top + alto))


def _abrir_foto(foto_field):
    if not foto_field:
        return None
    try:
        foto_field.open('rb')
        data = BytesIO(foto_field.read())
        foto_field.close()
        return data
    except Exception:
        return None


def _icono_persona_placeholder(draw, cx, cy, r, color):
    draw.ellipse([cx - r * 0.32, cy - r * 0.62, cx + r * 0.32, cy - r * 0.02], outline=color, width=6)
    draw.arc([cx - r * 0.55, cy - r * 0.05, cx + r * 0.55, cy + r * 0.9], 200, 340, fill=color, width=6)


def _medallion(canvas, cx, cy, diametro, foto_field):
    r = diametro // 2
    aro_grosor = 14

    aro = _gradiente_lineal(diametro, diametro, VERDE, ROSA, angulo=145)
    mask = Image.new('L', (diametro, diametro), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, diametro, diametro], fill=255)
    md.ellipse([aro_grosor, aro_grosor, diametro - aro_grosor, diametro - aro_grosor], fill=0)
    aro.putalpha(mask)
    canvas.paste(aro, (cx - r, cy - r), aro)

    interior_d = diametro - aro_grosor * 2 - 6
    interior_r = interior_d // 2
    ix, iy = cx - interior_r, cy - interior_r

    interior = _gradiente_lineal(interior_d, interior_d, BLANCO, BLUSH, angulo=160)
    mask_int = Image.new('L', (interior_d, interior_d), 0)
    ImageDraw.Draw(mask_int).ellipse([0, 0, interior_d, interior_d], fill=255)

    data = _abrir_foto(foto_field)
    if data:
        try:
            foto = Image.open(data).convert('RGB')
            foto = _crop_cuadrado(foto, interior_d)
            foto.putalpha(mask_int)
            canvas.paste(foto, (ix, iy), foto)
        except Exception:
            data = None
    if not data:
        interior.putalpha(mask_int)
        canvas.paste(interior, (ix, iy), interior)

        lado = interior_d * 0.62
        capa_forma = Image.new('RGBA', (interior_d, interior_d), (0, 0, 0, 0))
        cf = interior_r
        ImageDraw.Draw(capa_forma).polygon(
            [(cf, cf - lado / 2), (cf + lado / 2, cf), (cf, cf + lado / 2), (cf - lado / 2, cf)],
            fill=ROSA + (55,),
        )
        capa_forma.putalpha(ImageChops.multiply(capa_forma.split()[3], mask_int))
        canvas.paste(capa_forma, (ix, iy), capa_forma)

        d = ImageDraw.Draw(canvas)
        _icono_persona_placeholder(d, cx, cy, interior_r * 0.62, VERDE_OSCURO)


def _tarjeta_foto(canvas, x, y, ancho, alto, foto_field, radio=32):
    """Tarjeta de foto rectangular con esquinas redondeadas, marco en
    degradé verde-rosa y sombra propia, para el post de feed."""
    borde = 10
    marco = _gradiente_lineal(ancho, alto, VERDE, ROSA, angulo=145)
    mask_marco = Image.new('L', (ancho, alto), 0)
    md = ImageDraw.Draw(mask_marco)
    md.rounded_rectangle([0, 0, ancho, alto], radius=radio, fill=255)
    md.rounded_rectangle([borde, borde, ancho - borde, alto - borde], radius=max(4, radio - borde), fill=0)
    marco.putalpha(mask_marco)

    sombra, pad, offset = _sombra_para((ancho, alto), radio, alpha=45, blur=24, offset=(0, 14))
    canvas.paste(sombra, (x - pad + offset[0], y - pad + offset[1]), sombra)

    interior_w, interior_h = ancho - borde * 2, alto - borde * 2
    ix, iy = x + borde, y + borde
    radio_int = max(4, radio - borde)

    interior = _gradiente_lineal(interior_w, interior_h, BLANCO, BLUSH, angulo=160)
    mask_int = Image.new('L', (interior_w, interior_h), 0)
    ImageDraw.Draw(mask_int).rounded_rectangle([0, 0, interior_w, interior_h], radius=radio_int, fill=255)

    canvas.paste(marco, (x, y), marco)

    data = _abrir_foto(foto_field)
    if data:
        try:
            foto = Image.open(data).convert('RGB')
            foto = _crop_rectangulo(foto, interior_w, interior_h)
            foto.putalpha(mask_int)
            canvas.paste(foto, (ix, iy), foto)
            return
        except Exception:
            data = None
    if not data:
        interior.putalpha(mask_int)
        canvas.paste(interior, (ix, iy), interior)

        lado = min(interior_w, interior_h) * 0.5
        capa_forma = Image.new('RGBA', (interior_w, interior_h), (0, 0, 0, 0))
        cfx, cfy = interior_w / 2, interior_h / 2
        ImageDraw.Draw(capa_forma).polygon(
            [(cfx, cfy - lado / 2), (cfx + lado / 2, cfy), (cfx, cfy + lado / 2), (cfx - lado / 2, cfy)],
            fill=ROSA + (55,),
        )
        capa_forma.putalpha(ImageChops.multiply(capa_forma.split()[3], mask_int))
        canvas.paste(capa_forma, (ix, iy), capa_forma)

        d = ImageDraw.Draw(canvas)
        _icono_persona_placeholder(d, ix + interior_w // 2, iy + interior_h // 2, min(interior_w, interior_h) * 0.28, VERDE_OSCURO)


def _datos_atencion(psicologo):
    """Adapta los campos propios de este proyecto (modalidad simple,
    ciudad simple) a las mismas listas que usaba el generador de
    atencionpsi.com.ar (M2M de modalidades/ciudades)."""
    if psicologo.modalidad == 'ambas':
        modalidades = ['Online', 'Presencial']
    elif psicologo.modalidad:
        modalidades = [psicologo.get_modalidad_display()]
    else:
        modalidades = []
    ciudades = [psicologo.ciudad] if psicologo.ciudad else []
    return modalidades, ciudades


def _texto_modalidad_ciudad(modalidades, ciudades):
    if len(modalidades) >= 2:
        texto_modalidad = ' y '.join(modalidades)
        texto_ciudad = ', '.join(ciudades)
    else:
        texto_modalidad = modalidades[0] if modalidades else ''
        texto_ciudad = ', '.join(ciudades)
    return texto_modalidad, texto_ciudad


# ── Generador principal: historia ───────────────────────────────────────
def generar_imagen_story(psicologo, telefono_manual=None):
    """
    telefono_manual: si se pasa, se usa este número para la imagen en vez
    del guardado en el campo WhatsApp del profesional. Sirve porque el
    número del botón de WhatsApp del sitio y el número que se quiere
    mostrar en la foto de la historia no siempre son el mismo.
    """
    codigo_pais = psicologo.pais.codigo_telefono

    canvas = Image.new('RGB', (W, H), CREMA)
    diam = 588
    medallion_cy = 224 + diam // 2

    _forma_organica(canvas, BLOB_FONDO_1, (220, 231, 221))
    _forma_organica(canvas, BLOB_FONDO_2, (244, 229, 226))
    _forma_organica(canvas, BLOB_FONDO_3, (220, 231, 221), alpha=140)
    _puntos_dispersos(canvas, 60, (0, 430), (0, 430), VERDE_OSCURO, seed=7)
    _puntos_dispersos(canvas, 70, (880, 1080), (480, 1500), (217, 137, 133), seed=8)
    _puntos_dispersos(canvas, 30, (0, 1080), (1830, 1920), VERDE_OSCURO, seed=9)

    _arco_punteado(canvas, W // 2, medallion_cy, diam // 2 + 35, (143, 163, 143), ancho=2, alpha=90, n_guiones=170)
    dy = medallion_cy - 470
    _forma_organica(canvas, [(800, 290 + dy), (828, 322 + dy), (786, 332 + dy)], (232, 181, 177), alpha=217)
    _forma_organica(canvas, [(280, 625 + dy), (313, 653 + dy), (270, 663 + dy)], (232, 181, 177), alpha=217)

    draw = ImageDraw.Draw(canvas)

    # ── Marca ──
    f_marca_a = _font('montserrat', 700, 42)
    marca_a, marca_p = 'Atención', 'Psi'
    espacio_w = _tw(draw, ' ', f_marca_a)
    total_w = _tw(draw, marca_a, f_marca_a) + espacio_w + _tw(draw, marca_p, f_marca_a)
    mx = (W - total_w) // 2
    my = 96
    draw.text((mx, my), marca_a, font=f_marca_a, fill=VERDE_OSCURO)
    mx += _tw(draw, marca_a, f_marca_a) + espacio_w
    draw.text((mx, my), marca_p, font=f_marca_a, fill=ROSA_OSCURO)

    # ── Medallón de foto ──
    _medallion(canvas, W // 2, medallion_cy, diam, getattr(psicologo, 'foto', None))
    cy = 224 + diam + 56

    # ── Nombre ──
    nombre = _limpiar_nombre(psicologo.nombre)
    f_nombre = _font('playfair', 700, 86)
    lineas_nombre = _wrap(draw, nombre, f_nombre, W - 160)
    if len(lineas_nombre) > 2:
        f_nombre = _font('playfair', 700, 66)
        lineas_nombre = _wrap(draw, nombre, f_nombre, W - 160)
    for linea in lineas_nombre:
        _center(draw, linea, W // 2, cy, f_nombre, TINTA)
        cy += _th(draw, linea, f_nombre) + 16
    cy += 36

    # ── Datos: teléfono / modalidad + ciudad ──
    modalidades, ciudades = _datos_atencion(psicologo)
    texto_modalidad, texto_ciudad = _texto_modalidad_ciudad(modalidades, ciudades)

    digitos = re.sub(r'\D', '', telefono_manual) if telefono_manual else psicologo.whatsapp_limpio()
    texto_telefono = _formatear_telefono(digitos, codigo_pais) if digitos else ''

    f_dato = _font('montserrat', 800, 36)
    f_dato_sub = _font('montserrat', 500, 23)
    f_tel = _font('montserrat', 800, 41)

    datos_bloques = []
    if texto_telefono:
        alto = 110
        icono_cx_tel, icono_r_tel, gap_tel = 74, 37, 29
        ancho_tel = _ancho_burbuja_dato(
            draw, [(texto_telefono, f_tel)], icono_cx=icono_cx_tel, icono_r=icono_r_tel, gap=gap_tel, margen=80,
        )
        capa = _dibujar_burbuja_dato(
            lambda d, x: d.text((x, alto // 2), texto_telefono, font=f_tel, fill=BLANCO, anchor='lm'),
            ancho_tel, alto, _icono_telefono, estilo='solido',
            icono_cx=icono_cx_tel, icono_r=icono_r_tel, gap=gap_tel,
        )
        datos_bloques.append(capa)
    if texto_modalidad:
        alto = 112 if texto_ciudad else 96
        lineas_modal = [(texto_modalidad, f_dato)] + ([(texto_ciudad, f_dato_sub)] if texto_ciudad else [])
        ancho_modal = _ancho_burbuja_dato(draw, lineas_modal)

        def _dibujar_modalidad(d, x, alto=alto, texto_ciudad=texto_ciudad, texto_modalidad=texto_modalidad):
            if texto_ciudad:
                d.text((x, alto // 2 - 20), texto_modalidad, font=f_dato, fill=TINTA, anchor='lm')
                ancho_modalidad = _tw(d, texto_modalidad, f_dato)
                ancho_ciudad = _tw(d, texto_ciudad, f_dato_sub)
                x_ciudad = x + (ancho_modalidad - ancho_ciudad) / 2
                d.text((x_ciudad, alto // 2 + 22), texto_ciudad, font=f_dato_sub, fill=TINTA_SUAVE, anchor='lm')
            else:
                d.text((x, alto // 2), texto_modalidad, font=f_dato, fill=TINTA, anchor='lm')
        capa = _dibujar_burbuja_dato(_dibujar_modalidad, ancho_modal, alto, _icono_ubicacion)
        datos_bloques.append(capa)

    for capa in datos_bloques:
        bx = (W - capa.size[0]) // 2
        _pegar_con_sombra(canvas, capa, bx, cy, capa.size[1] // 2)
        cy += capa.size[1] + 22
    cy += 30

    # ── Burbujas inferiores (ancladas al fondo): sitio web siempre, Instagram
    # solo si hay un handle real configurado (settings.INSTAGRAM_URL). ──
    f_burbuja_web = _font('montserrat', 700, 38)
    web_texto = DOMINIO_SITIO
    ig_texto = _instagram_handle()

    pad_web_x, pad_web_y = 40, 20
    icono_web_d = 44
    web_texto_w = _tw(draw, web_texto, f_burbuja_web)
    web_h = _th(draw, web_texto, f_burbuja_web) + pad_web_y * 2 + 10
    web_w = pad_web_x * 2 + icono_web_d + 18 + web_texto_w

    margen_inferior = 90

    if ig_texto:
        f_burbuja_ig = _font('montserrat', 600, 26)
        pad_ig_x, pad_ig_y = 28, 11
        icono_ig_d = 32
        ig_texto_w = _tw(draw, ig_texto, f_burbuja_ig)
        ig_h = _th(draw, ig_texto, f_burbuja_ig) + pad_ig_y * 2 + 8
        ig_w = pad_ig_x * 2 + icono_ig_d + 14 + ig_texto_w

        gap_burbujas = 18
        ig_y = H - margen_inferior - ig_h
        web_y = ig_y - gap_burbujas - web_h

        ig_x0 = (W - ig_w) // 2
        draw.rounded_rectangle(
            [ig_x0, ig_y, ig_x0 + ig_w, ig_y + ig_h],
            radius=ig_h // 2, outline=ROSA_OSCURO, width=3,
        )
        icono_ig_cx = ig_x0 + pad_ig_x + icono_ig_d // 2
        icono_ig_cy = ig_y + ig_h // 2
        _icono_instagram(draw, icono_ig_cx, icono_ig_cy, icono_ig_d * 0.42, ROSA_OSCURO)
        draw.text((icono_ig_cx + icono_ig_d // 2 + 14, icono_ig_cy), ig_texto, font=f_burbuja_ig, fill=ROSA_OSCURO, anchor='lm')
    else:
        web_y = H - margen_inferior - web_h

    web_x0 = (W - web_w) // 2
    draw.rounded_rectangle(
        [web_x0, web_y, web_x0 + web_w, web_y + web_h],
        radius=web_h // 2, fill=VERDE_OSCURO,
    )
    icono_web_cx = web_x0 + pad_web_x + icono_web_d // 2
    icono_web_cy = web_y + web_h // 2
    _icono_globo(draw, icono_web_cx, icono_web_cy, icono_web_d * 0.42, BLANCO)
    draw.text((icono_web_cx + icono_web_d // 2 + 18, icono_web_cy), web_texto, font=f_burbuja_web, fill=BLANCO, anchor='lm')

    # ── Franja etaria: tipografía libre, se achica sola si la lista es larga ──
    destinatarios = ', '.join(psicologo.publicos.values_list('nombre', flat=True))
    if destinatarios:
        eyebrow = 'ATIENDE A'
        f_eyebrow = _font('montserrat', 700, 24)
        max_ancho_franja = 900
        limite_superior_y = cy
        limite_inferior_y = web_y - 40
        alto_encabezado = _th(draw, eyebrow, f_eyebrow) + 16 + 20 + 12

        for tam in (58, 50, 44, 38):
            f_franja = _font('playfair', 600, tam)
            lineas = _wrap(draw, destinatarios, f_franja, max_ancho_franja)
            alto_linea = _th(draw, 'Ag', f_franja) + 14
            alto_bloque = alto_linea * len(lineas)
            if limite_superior_y + alto_encabezado + alto_bloque <= limite_inferior_y or tam == 38:
                break

        fy = limite_superior_y
        _center(draw, eyebrow, W // 2, fy, f_eyebrow, VERDE_OSCURO)
        fy += _th(draw, eyebrow, f_eyebrow) + 16
        draw.line([(W // 2 - 32, fy + 8), (W // 2 + 32, fy + 8)], fill=VERDE, width=2)
        fy += 20 + 12
        for linea in lineas:
            capa_linea = _texto_italica(linea, f_franja, TINTA)
            canvas.paste(capa_linea, ((W - capa_linea.size[0]) // 2, fy), capa_linea)
            fy += alto_linea

    return canvas


# ── Generador de post de feed ────────────────────────────────────────────
def generar_imagen_feed(psicologo):
    """
    Post de feed (1080x1350) con UN profesional. A diferencia de la
    historia, no lleva el logo de "Atención Psi" ni la burbuja de
    Instagram -- se postea directo en la cuenta, así que ya se sabe de
    quién es -- pero sí una burbuja con la web al final. Campos: nombre,
    orientación (acá: las orientaciones-filtro que cargó el profesional,
    ya que este proyecto no tiene un campo de texto libre aparte como
    atencionpsi.com.ar), localidad + modalidad, y a quién atiende. Foto en
    tarjeta rectangular en vez de medallón circular, mismo lenguaje visual
    que la historia para que se sientan de la misma familia.
    """
    canvas = Image.new('RGB', (FEED_W, FEED_H), CREMA)

    _forma_organica(canvas, BLOB_FEED_1, (220, 231, 221))
    _forma_organica(canvas, BLOB_FEED_2, (244, 229, 226))
    _puntos_dispersos(canvas, 45, (0, 360), (0, 360), VERDE_OSCURO, seed=27)
    _puntos_dispersos(canvas, 55, (740, FEED_W), (260, FEED_H - 60), (217, 137, 133), seed=28)

    draw = ImageDraw.Draw(canvas)

    # ── Tarjeta de foto ──
    foto_w, foto_h = 560, 600
    foto_x = (FEED_W - foto_w) // 2
    foto_y = 90
    _tarjeta_foto(canvas, foto_x, foto_y, foto_w, foto_h, getattr(psicologo, 'foto', None))
    draw = ImageDraw.Draw(canvas)
    cy = foto_y + foto_h + 46

    # ── Nombre ──
    nombre = _limpiar_nombre(psicologo.nombre)
    f_nombre = _font('playfair', 700, 60)
    lineas_nombre = _wrap(draw, nombre, f_nombre, FEED_W - 140)
    if len(lineas_nombre) > 2:
        f_nombre = _font('playfair', 700, 48)
        lineas_nombre = _wrap(draw, nombre, f_nombre, FEED_W - 140)
    for linea in lineas_nombre:
        _center(draw, linea, FEED_W // 2, cy, f_nombre, TINTA)
        cy += _th(draw, linea, f_nombre) + 10
    cy += 10

    # ── Orientación, en itálica (mismo efecto "escrito a mano" que la
    # franja de a quién atiende) para que se lea distinto del nombre. ──
    orientacion = ', '.join(psicologo.orientaciones.values_list('nombre', flat=True))
    if orientacion:
        f_orient = _font('playfair', 500, 33)
        lineas_orient = _wrap(draw, orientacion, f_orient, FEED_W - 220)[:3]
        for linea in lineas_orient:
            capa = _texto_italica(linea, f_orient, TINTA_SUAVE)
            canvas.paste(capa, ((FEED_W - capa.size[0]) // 2, cy), capa)
            cy += _th(draw, linea, f_orient) + 8
        cy += 22

    # ── Modalidad + localidad ──
    modalidades, ciudades = _datos_atencion(psicologo)
    texto_modalidad = ' y '.join(modalidades) if modalidades else ''
    texto_ciudad = ', '.join(ciudades) if ciudades else ''

    if texto_modalidad:
        f_dato = _font('montserrat', 800, 34)
        f_dato_sub = _font('montserrat', 500, 22)
        alto = 106 if texto_ciudad else 90
        lineas_modal = [(texto_modalidad, f_dato)] + ([(texto_ciudad, f_dato_sub)] if texto_ciudad else [])
        ancho_modal = _ancho_burbuja_dato(draw, lineas_modal)

        def _dibujar_modalidad(d, x, alto=alto, texto_ciudad=texto_ciudad, texto_modalidad=texto_modalidad):
            if texto_ciudad:
                d.text((x, alto // 2 - 19), texto_modalidad, font=f_dato, fill=TINTA, anchor='lm')
                ancho_modalidad = _tw(d, texto_modalidad, f_dato)
                ancho_ciudad = _tw(d, texto_ciudad, f_dato_sub)
                x_ciudad = x + (ancho_modalidad - ancho_ciudad) / 2
                d.text((x_ciudad, alto // 2 + 21), texto_ciudad, font=f_dato_sub, fill=TINTA_SUAVE, anchor='lm')
            else:
                d.text((x, alto // 2), texto_modalidad, font=f_dato, fill=TINTA, anchor='lm')

        capa = _dibujar_burbuja_dato(_dibujar_modalidad, ancho_modal, alto, _icono_ubicacion)
        bx = (FEED_W - capa.size[0]) // 2
        _pegar_con_sombra(canvas, capa, bx, cy, capa.size[1] // 2)
        cy += capa.size[1] + 30
    else:
        cy += 10

    # ── Burbuja de sitio web, anclada abajo (se calcula antes que "a quién
    # atiende" para que esa franja sepa hasta dónde tiene lugar libre). ──
    f_burbuja_web = _font('montserrat', 700, 36)
    web_texto = DOMINIO_SITIO
    pad_web_x, pad_web_y = 38, 19
    icono_web_d = 42
    web_texto_w = _tw(draw, web_texto, f_burbuja_web)
    web_h = _th(draw, web_texto, f_burbuja_web) + pad_web_y * 2 + 10
    web_w = pad_web_x * 2 + icono_web_d + 16 + web_texto_w
    margen_inferior_web = 70
    web_y = FEED_H - margen_inferior_web - web_h
    web_x0 = (FEED_W - web_w) // 2
    draw.rounded_rectangle([web_x0, web_y, web_x0 + web_w, web_y + web_h], radius=web_h // 2, fill=VERDE_OSCURO)
    icono_web_cx = web_x0 + pad_web_x + icono_web_d // 2
    icono_web_cy = web_y + web_h // 2
    _icono_globo(draw, icono_web_cx, icono_web_cy, icono_web_d * 0.42, BLANCO)
    draw.text((icono_web_cx + icono_web_d // 2 + 16, icono_web_cy), web_texto, font=f_burbuja_web, fill=BLANCO, anchor='lm')

    destinatarios = ', '.join(psicologo.publicos.values_list('nombre', flat=True))
    if destinatarios:
        eyebrow = 'ATIENDE A'
        f_eyebrow = _font('montserrat', 700, 23)
        max_ancho_franja = FEED_W - 160
        limite_superior_y = cy
        limite_inferior_y = web_y - 40
        alto_encabezado = _th(draw, eyebrow, f_eyebrow) + 16 + 20 + 12

        for tam in (52, 46, 40, 34):
            f_franja = _font('playfair', 600, tam)
            lineas = _wrap(draw, destinatarios, f_franja, max_ancho_franja)
            alto_linea = _th(draw, 'Ag', f_franja) + 12
            alto_bloque = alto_linea * len(lineas)
            if limite_superior_y + alto_encabezado + alto_bloque <= limite_inferior_y or tam == 34:
                break

        fy = limite_superior_y
        _center(draw, eyebrow, FEED_W // 2, fy, f_eyebrow, VERDE_OSCURO)
        fy += _th(draw, eyebrow, f_eyebrow) + 16
        draw.line([(FEED_W // 2 - 32, fy + 8), (FEED_W // 2 + 32, fy + 8)], fill=VERDE, width=2)
        fy += 20 + 12
        for linea in lineas:
            capa_linea = _texto_italica(linea, f_franja, TINTA)
            canvas.paste(capa_linea, ((FEED_W - capa_linea.size[0]) // 2, fy), capa_linea)
            fy += alto_linea

    return canvas


def _texto_italica(texto, fnt, color, inclinacion=0.22):
    """
    PlayfairDisplay.ttf es una variable font solo de peso (sin eje itálico).
    Para lograr la itálica se dibuja el texto derecho en una capa aparte y
    se aplica una transformación afín (la misma técnica que usan los
    navegadores para la itálica "sintética").
    """
    tmp = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    bbox = tmp.textbbox((0, 0), texto, font=fnt)
    w, h = bbox[2] - bbox[0] + 20, bbox[3] - bbox[1] + 20
    capa = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(capa).text((10 - bbox[0], 10 - bbox[1]), texto, font=fnt, fill=color)
    ancho_final = w + int(h * inclinacion)
    capa = capa.transform(
        (ancho_final, h), Image.AFFINE,
        (1, inclinacion, -h * inclinacion, 0, 1, 0),
        resample=Image.BICUBIC,
    )
    return capa
