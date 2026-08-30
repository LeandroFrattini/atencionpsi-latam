from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from directorio.sitemaps import PaisesSitemap, PsicologosSitemap
from directorio.views import robots_txt

sitemaps = {
    'paises': PaisesSitemap,
    'psicologos': PsicologosSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('portal/', include('portal.urls')),
    path('', include('turnos.urls')),
    path('', include('directorio.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static('/media/', document_root=settings.BASE_DIR / 'media')
