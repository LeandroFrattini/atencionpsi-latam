from django.db import models


class ConfiguracionWhatsApp(models.Model):
    """Respuestas automáticas del WhatsApp de Atención Psi LATAM. Hay una sola (se edita desde el admin)."""
    activa = models.BooleanField(
        'Respuestas automáticas activas', default=False,
        help_text='Apagadas por defecto. Encendelas cuando el número esté conectado a la API y el webhook configurado.',
    )
    texto_bienvenida = models.TextField(
        'Mensaje de bienvenida', max_length=1000,
        default='¡Hola! Gracias por escribir a Atención Psi. En un momento te enviamos más información.',
        help_text='Es el primer mensaje, igual para todos.',
    )
    texto_otro_pais = models.TextField(
        'Segundo mensaje si el país no está en la lista', max_length=1000, blank=True,
        help_text='Para quienes escriben desde un país sin mensaje propio (abajo). Si lo dejás vacío, solo reciben la bienvenida.',
    )
    horas_entre_respuestas = models.PositiveIntegerField(
        'Horas entre respuestas a la misma persona', default=24,
        help_text='Si alguien escribe varias veces, solo se le responde una vez por este período.',
    )

    class Meta:
        verbose_name = 'Respuestas automáticas de WhatsApp'
        verbose_name_plural = 'Respuestas automáticas de WhatsApp'

    def __str__(self):
        return 'Respuestas automáticas de WhatsApp'

    def save(self, *args, **kwargs):
        self.pk = 1   # siempre la misma fila
        super().save(*args, **kwargs)

    @classmethod
    def obtener(cls):
        return cls.objects.get_or_create(pk=1)[0]


class RespuestaPais(models.Model):
    """Segundo mensaje, según el país de quien escribe (con un archivo adjunto opcional)."""
    configuracion = models.ForeignKey(ConfiguracionWhatsApp, on_delete=models.CASCADE, related_name='por_pais')
    pais = models.ForeignKey('directorio.Pais', on_delete=models.CASCADE, related_name='+')
    texto = models.TextField('Mensaje', max_length=1000, help_text='Hasta 1000 caracteres.')
    archivo = models.FileField(
        'Archivo adjunto (opcional)', upload_to='whatsapp/', blank=True, null=True,
        help_text='PDF o imagen. Se manda junto con el mensaje.',
    )

    class Meta:
        verbose_name = 'Mensaje por país'
        verbose_name_plural = 'Mensajes por país'
        constraints = [models.UniqueConstraint(fields=['configuracion', 'pais'], name='wa_una_respuesta_por_pais')]

    def __str__(self):
        return f'{self.pais.nombre}'


class ContactoWhatsApp(models.Model):
    """Quién escribió y a quién ya se le respondió (solo el teléfono y las fechas, no el contenido)."""
    telefono = models.CharField(max_length=30, unique=True)
    ultimo_mensaje = models.DateTimeField('Último mensaje recibido', null=True, blank=True)
    ultima_respuesta = models.DateTimeField('Última respuesta automática', null=True, blank=True)
    ultimo_error = models.CharField(
        'Último error al responder', max_length=300, blank=True,
        help_text='Lo que contestó Meta si rechazó el envío. Vacío si la última respuesta salió bien.',
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Contacto de WhatsApp'
        verbose_name_plural = 'Contactos de WhatsApp'

    def __str__(self):
        return self.telefono


class MensajeRecibido(models.Model):
    """Ids de mensajes ya atendidos: Meta reintenta el aviso si tarda, y así no se responde dos veces."""
    wa_id = models.CharField(max_length=200, unique=True)
    creado = models.DateTimeField(auto_now_add=True)


class EventoWebhook(models.Model):
    """Registro de cada vez que Meta (o cualquiera) llamó a /wa-coexistencia/webhook/, y qué se hizo.
    Sirve para diagnosticar: si no hay ninguno, Meta nunca llamó; si hay "firma inválida", Meta llama pero
    el secreto de la app no coincide. NO guarda el contenido de los mensajes ni teléfonos."""
    RESULTADOS = [
        ('verificacion_ok', 'Verificación de Meta aceptada'),
        ('verificacion_rechazada', 'Verificación rechazada (frase distinta)'),
        ('firma_invalida', 'RECHAZADO: firma inválida'),
        ('json_invalido', 'Rechazado: cuerpo inválido'),
        ('recibido', 'Aviso recibido'),
        ('recibido_con_error', 'Recibido, pero falló la respuesta'),
    ]

    creado = models.DateTimeField('Cuándo', auto_now_add=True, db_index=True)
    metodo = models.CharField('Método', max_length=6)
    resultado = models.CharField('Resultado', max_length=30, choices=RESULTADOS)
    detalle = models.CharField('Detalle', max_length=300, blank=True)
    mensajes = models.PositiveSmallIntegerField('Mensajes nuevos', default=0)
    numero_id = models.CharField('Número que lo recibió (ID de Meta)', max_length=40, blank=True)
    agente = models.CharField('Quién llamó', max_length=120, blank=True)

    class Meta:
        verbose_name = 'Aviso recibido de Meta'
        verbose_name_plural = 'Avisos de Meta (diagnóstico)'
        ordering = ['-creado']

    def __str__(self):
        return f'{self.creado:%d/%m %H:%M} {self.metodo} {self.resultado}'
