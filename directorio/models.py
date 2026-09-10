from django.contrib.auth.models import User
from django.db import models


class Pais(models.Model):
    """Cada país de la expansión vive acá, no en repos separados.
    El slug es el path público: atencionpsi.lat/<slug>/."""
    nombre = models.CharField(max_length=60)
    slug = models.SlugField(max_length=30, unique=True)
    codigo_iso = models.CharField('Código ISO', max_length=2, help_text='Ej: PE, UY, CL')
    bandera_emoji = models.CharField(
        max_length=8,
        help_text='Ej: 🇵🇪 -- ya no se usa para mostrar la bandera en el sitio (eso sale de bandera_svg), se mantiene solo de referencia'
    )
    moneda = models.CharField('Moneda', max_length=3, help_text='Código ISO de moneda, ej: PEN, UYU')
    simbolo_moneda = models.CharField('Símbolo de moneda', max_length=6, blank=True, help_text='Ej: S/, $U, $')
    activo = models.BooleanField(default=False, help_text='Recién se activa cuando el país está listo para mostrarse al público')
    orden = models.PositiveIntegerField(default=0)

    # Argentina no vive en esta base -- sigue siendo atencionpsi.com.ar,
    # un proyecto totalmente aparte. Para que su bandera aparezca en el hub
    # y el menú junto a las demás sin que nadie termine en un buscador
    # interno vacío, se marca como "externo" y linkea directo afuera.
    es_externo = models.BooleanField(
        'Es un sitio externo (no vive en este proyecto)', default=False,
        help_text='Marcar para Argentina: la bandera linkea directo a url_externa en vez de abrir el buscador de acá'
    )
    url_externa = models.URLField(
        'URL externa', blank=True,
        help_text='Solo si "Es un sitio externo" está tildado, ej: https://atencionpsi.com.ar'
    )

    # Cada país llama distinto a la habilitación profesional -- mostrar el
    # rótulo correcto en el perfil público es lo que le da seriedad al perfil
    # ante un paciente de ese país. Confirmado por país (2026-08-11):
    # Perú = colegiatura (CPsP), Uruguay = matrícula (Colegio de Psicólogos),
    # Chile = registro RNPI (la colegiatura es voluntaria, no es la credencial
    # oficial), México = cédula profesional (SEP), Colombia = tarjeta
    # profesional (COLPSIC).
    etiqueta_matricula = models.CharField(
        'Etiqueta de habilitación profesional', max_length=60, default='N° de Matrícula',
        help_text='Ej: "N° de Colegiatura", "N° de Matrícula", "N° de Cédula Profesional"'
    )
    muestra_precio_sesion = models.BooleanField(
        'Mostrar precio de sesión en el perfil', default=False,
        help_text='Convención de mercado: en Perú se acostumbra publicar el costo de la sesión en el perfil, en otros países no'
    )

    # Dos planes reales (2026-09-09): Básico (perfil publicado en el
    # buscador) y Premium (Básico + agenda de turnos online + difusión en el
    # Instagram de Atención Psi de ese país). Precios en moneda local, sin
    # decimales -- así se cargan en los tres países activos hoy. En 0 para
    # los países que todavía no tienen plan definido (inactivos o externos).
    precio_basico = models.PositiveIntegerField(
        'Precio Plan Básico (moneda local)', default=0,
        help_text='En la moneda de este país, sin decimales. Ej: 49 (soles), 590 (pesos uruguayos)'
    )
    precio_premium = models.PositiveIntegerField(
        'Precio Plan Premium (moneda local)', default=0,
        help_text='Básico + agenda de turnos online + difusión en el Instagram de Atención Psi del país'
    )

    class Meta:
        verbose_name = 'País'
        verbose_name_plural = 'Países'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre

    @property
    def bandera_svg(self):
        """Ícono de bandera real (SVG en static/img/flags/) en vez del emoji
        -- en Windows los emoji de bandera a veces se ven como el código de
        país en texto plano en lugar de la bandera."""
        return f'img/flags/{self.codigo_iso.lower()}.svg'


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
    # La etiqueta que ve el paciente ("N° de Colegiatura", "N° de Matrícula", etc.)
    # sale de pais.etiqueta_matricula, no de acá -- este campo solo guarda el número.
    matricula = models.CharField('N° de habilitación profesional', max_length=60)
    whatsapp = models.CharField(max_length=30)
    ciudad = models.CharField(max_length=100, blank=True)
    modalidad = models.CharField(max_length=12, choices=MODALIDAD_CHOICES, default='online')
    foto = models.ImageField(upload_to='psicologos/', blank=True, null=True)
    bio = models.TextField(blank=True)
    docencia = models.TextField('Docencia', blank=True, help_text='Un párrafo con la experiencia dando clases/formación a otros, si tiene')
    precio_sesion = models.DecimalField(
        'Precio de sesión', max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Opcional. Se muestra en tu perfil público.'
    )

    # Rango aproximado, no un conteo exacto -- es autodeclarado en el
    # registro (todavía no hay turnos reales pasando por la plataforma para
    # medirlo solos). Se usa para mostrar "Más de X sesiones atendidas en su
    # trayectoria" en el perfil (nunca "a través de Atención Psi", sería
    # engañoso) y para sumar un total agregado en el buscador/hub. Opcional
    # -- no bloquea la publicación si no lo contesta.
    SESIONES_CHOICES = [
        (100, 'Más de 100'),
        (500, 'Más de 500'),
        (1000, 'Más de 1.000'),
        (2000, 'Más de 2.000'),
    ]
    sesiones_atendidas = models.PositiveIntegerField(
        'Sesiones atendidas (aprox.)', choices=SESIONES_CHOICES, null=True, blank=True,
        help_text='Elegí el rango que mejor represente tu trayectoria profesional (no hace falta ser exacto).'
    )

    orientaciones = models.ManyToManyField(Orientacion, blank=True, related_name='psicologos')
    publicos = models.ManyToManyField(Publico, blank=True, related_name='psicologos')

    # Pago y publicación -- a diferencia de atencionpsi.com.ar, acá nadie
    # aprueba el alta a mano. Pero a diferencia de lo que se pensó al
    # principio, publicar NO es automático apenas se cumplen los requisitos:
    # el profesional tiene que tocar "Publicar mi perfil" él mismo (decisión
    # de la dueña, 2026-08-11) -- así puede revisar cómo queda antes de que
    # lo vea un paciente. Si más adelante deja de pagar o el perfil queda
    # incompleto, la propiedad `publicado` lo oculta solo, sin que haga falta
    # que alguien lo despublique a mano.
    suscripcion_activa = models.BooleanField(default=False)
    dlocal_subscription_id = models.CharField(max_length=100, blank=True)
    publicado_por_usuario = models.BooleanField('Publicado por el profesional', default=False)

    # Excepción para las profesionales "fundadoras" reclutadas a pulmón antes
    # de tener el cobro automático andando -- ver plan de captación.
    exento_de_pago = models.BooleanField('Exenta de pago (fundadora)', default=False)

    fecha_alta = models.DateTimeField(auto_now_add=True)
    # Se completa cuando dLocal confirma el primer pago (o al marcar
    # exento_de_pago a mano) -- de acá salen los 24hs para el recordatorio
    # de "completá tu perfil", separado del recordatorio de "completá el pago"
    # que se mide desde fecha_alta.
    fecha_pago_confirmado = models.DateTimeField(null=True, blank=True)
    recordatorio_pago_enviado = models.BooleanField(default=False)
    recordatorio_perfil_enviado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Psicólogo'
        verbose_name_plural = 'Psicólogos'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.pais.codigo_iso})'

    def save(self, *args, **kwargs):
        # Si la marcan exenta a mano (fundadora) sin pasar por dLocal, igual
        # necesita una fecha de referencia para el recordatorio de "completá
        # tu perfil" -- si no, nunca se dispara.
        if self.exento_de_pago and not self.fecha_pago_confirmado:
            from django.utils import timezone
            self.fecha_pago_confirmado = timezone.now()
        super().save(*args, **kwargs)

    def activar_suscripcion(self, dlocal_subscription_id=''):
        """Llamado por el webhook de dLocal cuando confirma el primer pago
        (y, en dev, por el botón de "simular pago"). Idempotente: si ya
        estaba activa no pisa fecha_pago_confirmado de nuevo."""
        from django.utils import timezone
        if not self.suscripcion_activa:
            self.suscripcion_activa = True
            self.fecha_pago_confirmado = timezone.now()
        if dlocal_subscription_id:
            self.dlocal_subscription_id = dlocal_subscription_id
        self.save()

    @property
    def puede_publicar(self):
        """Cumple los requisitos para publicar (pagó o está exenta, y
        completó el perfil) -- todavía no significa que esté visible: falta
        que el profesional toque "Publicar"."""
        return (self.suscripcion_activa or self.exento_de_pago) and self.perfil_completo

    @property
    def publicado(self):
        """Visible en el buscador público. Se apaga solo si deja de cumplir
        los requisitos (por ejemplo, se le corta la suscripción), aunque en
        su momento haya tocado "Publicar"."""
        return self.publicado_por_usuario and self.puede_publicar

    @property
    def perfil_completo(self):
        campos_obligatorios = [self.nombre, self.matricula, self.whatsapp, self.foto, self.bio]
        return all(campos_obligatorios) and self.orientaciones.exists()


class Formacion(models.Model):
    """Un renglón de la lista de formación del perfil (título, posgrado,
    curso, workshop, etc.) -- el profesional carga los que quiera, en el
    orden que quiera, mismo patrón que se ve en perfiles de la competencia
    en Perú (título, profesorado, posgrado, cursos sueltos, todo mezclado
    en una sola lista numerada)."""
    psicologo = models.ForeignKey(Psicologo, on_delete=models.CASCADE, related_name='formaciones')
    descripcion = models.CharField(max_length=300, help_text='Ej: "Licenciada en Psicología. Universidad X"')
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Formación'
        verbose_name_plural = 'Formaciones'
        ordering = ['orden', 'id']

    def __str__(self):
        return self.descripcion[:60]
