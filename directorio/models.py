from django.contrib.auth.models import User
from django.db import models


class Pais(models.Model):
    """Cada país de la expansión vive acá, no en repos separados.
    El slug es el path público: atencionpsi.com/<slug>/."""
    nombre = models.CharField(max_length=60)
    slug = models.SlugField(max_length=30, unique=True)
    codigo_iso = models.CharField('Código ISO', max_length=2, help_text='Ej: PE, UY, CL')
    bandera_emoji = models.CharField(max_length=8, help_text='Ej: 🇵🇪 (temporal, reemplazar por ícono de bandera real)')
    moneda = models.CharField('Moneda', max_length=3, help_text='Código ISO de moneda, ej: PEN, UYU')
    activo = models.BooleanField(default=False, help_text='Recién se activa cuando el país está listo para mostrarse al público')
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'País'
        verbose_name_plural = 'Países'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Orientacion(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Orientación'
        verbose_name_plural = 'Orientaciones'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Publico(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Público'
        verbose_name_plural = 'Públicos'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Psicologo(models.Model):
    MODALIDAD_CHOICES = [
        ('online', 'Online'),
        ('presencial', 'Presencial'),
        ('ambas', 'Online y presencial'),
    ]

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='psicologo')
    pais = models.ForeignKey(Pais, on_delete=models.PROTECT, related_name='psicologos')

    nombre = models.CharField(max_length=150)
    matricula = models.CharField('Matrícula profesional', max_length=60)
    whatsapp = models.CharField(max_length=30)
    ciudad = models.CharField(max_length=100, blank=True)
    modalidad = models.CharField(max_length=12, choices=MODALIDAD_CHOICES, default='online')
    foto = models.ImageField(upload_to='psicologos/', blank=True, null=True)
    bio = models.TextField(blank=True)

    orientaciones = models.ManyToManyField(Orientacion, blank=True, related_name='psicologos')
    publicos = models.ManyToManyField(Publico, blank=True, related_name='psicologos')

    # Pago y publicación -- a diferencia de atencionpsi.com.ar, acá nadie
    # aprueba el alta a mano: el perfil se autopublica cuando dLocal confirma
    # la primera suscripción, y se autodespublica si la suscripción se corta.
    suscripcion_activa = models.BooleanField(default=False)
    dlocal_subscription_id = models.CharField(max_length=100, blank=True)

    # Excepción para las profesionales "fundadoras" reclutadas a pulmón antes
    # de tener el cobro automático andando -- ver plan de captación.
    exento_de_pago = models.BooleanField('Exenta de pago (fundadora)', default=False)

    fecha_alta = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Psicólogo'
        verbose_name_plural = 'Psicólogos'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.pais.codigo_iso})'

    @property
    def publicado(self):
        """Visible en el buscador público: pagó (o está exenta) Y completó
        los datos mínimos para no publicar un perfil vacío."""
        return (self.suscripcion_activa or self.exento_de_pago) and self.perfil_completo

    @property
    def perfil_completo(self):
        campos_obligatorios = [self.nombre, self.matricula, self.whatsapp, self.foto]
        return all(campos_obligatorios) and self.orientaciones.exists()
