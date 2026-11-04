# Configuración de gunicorn (lo lee solo, por estar junto a manage.py: no depende del "Start Command" de Render).
#
# Por defecto gunicorn atiende UN pedido a la vez (1 proceso sync). Eso causaba un bloqueo mutuo con Meta: al
# conectar WhatsApp, esta web le pedía algo a Meta y se quedaba esperando su respuesta; Meta, para aceptar la
# dirección, llamaba a esta web a verificarla, pero el único proceso estaba ocupado esperándolo a ÉL. Meta daba
# error por tiempo (#2200, 6 segundos) y los avisos nunca quedaban apuntados acá.
#
# Con varios hilos en el mismo proceso se atienden pedidos en paralelo sin gastar más memoria que con un
# proceso solo. Al ser threads > 1, gunicorn usa solo el worker "gthread".
workers = 1
threads = 4
# Algunas pantallas hablan con servicios externos (Meta, dLocal Go, Brevo): se les da margen antes de cortarlas.
timeout = 60
