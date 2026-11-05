from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from directorio.sitemaps import CiudadesSitemap, EspecialidadesSitemap, PaisesSitemap, PsicologosSitemap
from directorio.views import robots_txt, tareas_diarias
from wa_coexistencia import views as wa_views
from wa_coexistencia import webhook as wa_webhook

sitemaps = {
    'paises': PaisesSitemap,
    'psicologos': PsicologosSitemap,
    'ciudades': CiudadesSitemap,
    'especialidades': EspecialidadesSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('tareas-diarias/<str:token>/', tareas_diarias, name='tareas_diarias'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('portal/', include('portal.urls')),
    path('wa-coexistencia/', wa_views.coexistencia, name='wa_coexistencia'),
    path('wa-coexistencia/callback/', wa_views.coexistencia_callback, name='wa_coexistencia_callback'),
    path('wa-coexistencia/token/', wa_views.coexistencia_con_token, name='wa_coexistencia_token'),
    path('wa-coexistencia/webhook/', wa_webhook.recibir, name='wa_webhook'),
    path('', include('turnos.urls')),
    path('', include('directorio.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static('/media/', document_root=settings.BASE_DIR / 'media')
