import re

# Patrones de User-Agent de bots, crawlers, previsualizadores y scripts conocidos: los mismos
# que usa atencionpsi.com.ar, más algunos de monitoreo y de pruebas de velocidad. Ningún filtro
# por User-Agent es 100% infalible, pero esto corta la enorme mayoría del tráfico que no es de
# personas y que infla las estadísticas (Google, Bing, WhatsApp/Facebook armando la vista previa
# de un link, herramientas de SEO, scrapers, chequeos de que el sitio esté vivo, etc.).
BOT_PATTERNS = [
    r'bot', r'crawl', r'spider', r'slurp',
    r'facebookexternalhit', r'facebot', r'whatsapp', r'telegrambot', r'discordbot',
    r'twitterbot', r'linkedinbot', r'pinterest', r'slackbot', r'skypeuripreview',
    r'ahrefs', r'semrush', r'mj12bot', r'dotbot', r'petalbot', r'bytespider',
    r'yandex', r'baiduspider', r'duckduckbot', r'applebot', r'ia_archiver',
    r'python-requests', r'python-urllib', r'curl/', r'wget/', r'scrapy', r'libwww', r'java/',
    r'headlesschrome', r'phantomjs', r'go-http-client', r'okhttp', r'httpclient',
    r'postmanruntime', r'axios', r'node-fetch',
    r'uptime', r'pingdom', r'monitor', r'lighthouse', r'pagespeed', r'gtmetrix', r'render/',
    r'preview',
]

BOT_REGEX = re.compile('|'.join(BOT_PATTERNS), re.IGNORECASE)


def es_bot(request):
    """Heurística simple para detectar bots, crawlers y scripts a partir del User-Agent.
    Sin User-Agent, o con uno sospechosamente corto, se considera bot."""
    ua = request.META.get('HTTP_USER_AGENT', '')
    if not ua or len(ua) < 10:
        return True
    return bool(BOT_REGEX.search(ua))
