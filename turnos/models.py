from django.db import models
from django.db.models import Q
from django.utils import timezone


class TipoSesion(models.Model):
    """Cada psicólogo define sus propios tipos de sesión (Individual, Pareja,
    etc.), cada uno con su propia duración y precio -- el precio acá es
    siempre informativo, el cobro real lo arregla el profesional directo
    con el paciente (decisión de la dueña, 2026-08-12)."""
    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='tipos_sesion')
    nombre = models.CharField(max_length=60, help_text='Ej: Individual, Pareja, Familiar')
    duracion_min = models.PositiveIntegerField('Duración (minutos)', default=50)
    precio = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Tipo de sesión'
        verbose_name_plural = 'Tipos de sesión'
        ordering = ['orden', 'id']

    def __str__(self):
        return f'{self.nombre} ({self.psicologo.nombre})'


class DisponibilidadSemanal(models.Model):
    """Plantilla de disponibilidad por día de la semana -- se carga una vez
    y se repite sola todas las semanas. Mismo patrón que atencionpsi.com.ar."""
    DIA_CHOICES = [
        (0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'),
        (3, 'Jueves'), (4, 'Viernes'), (5, 'Sábado'),
    ]

    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='disponibilidad_semanal')
    dia_semana = models.PositiveSmallIntegerField(choices=DIA_CHOICES, verbose_name='Día de la semana')
    hora_desde = models.TimeField(verbose_name='Desde')
    hora_hasta = models.TimeField(verbose_name='Hasta')

    class Meta:
        verbose_name = 'Bloque de disponibilidad semanal'
        verbose_name_plural = 'Disponibilidad semanal'
        ordering = ['dia_semana', 'hora_desde']

    def __str__(self):
        return f'{self.get_dia_semana_display()} {self.hora_desde}-{self.hora_hasta}'


class DiaNoAtiende(models.Model):
    """Período en el que el psicólogo no atiende (vacaciones, licencia).
    Tiene prioridad sobre la disponibilidad semanal."""
    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='dias_no_atiende')
    fecha_desde = models.DateField(verbose_name='Desde')
    fecha_hasta = models.DateField(verbose_name='Hasta')
    motivo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'Día que no atiende'
        verbose_name_plural = 'Días que no atiende'
        ordering = ['fecha_desde']

    def __str__(self):
        return f'{self.psicologo} · {self.fecha_desde:%d/%m/%Y} — {self.fecha_hasta:%d/%m/%Y}'


class Paciente(models.Model):
    """Ficha de paciente que el profesional maneja desde su portal. Se crea
    sola cuando alguien reserva un turno (agrupando por email dentro de la
    cartera de ese psicólogo) y también se puede cargar a mano para pacientes
    que ya venían atendiendo por fuera de la plataforma.

    A diferencia del `Turno`, que guarda un snapshot de los datos de contacto
    tal como se cargaron al reservar, la ficha es editable y acumula la
    historia: todos los turnos de esa persona con ese psicólogo, más las
    notas privadas que el profesional quiera dejar."""
    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='pacientes')

    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    edad = models.PositiveIntegerField(null=True, blank=True)
    notas = models.TextField(
        'Notas privadas', blank=True,
        help_text='Solo las ves vos. No se muestran en ningún lado público.'
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        ordering = ['apellidos', 'nombres']
        constraints = [
            # Un mismo email no se repite dentro de la cartera de un psicólogo
            # (así el alta automática al reservar reusa la ficha en vez de
            # duplicarla). Los pacientes cargados a mano sin email quedan
            # afuera de la restricción.
            models.UniqueConstraint(
                fields=['psicologo', 'email'],
                condition=~Q(email=''),
                name='paciente_email_unico_por_psicologo',
            ),
        ]

    def __str__(self):
        return f'{self.nombre_completo} ({self.psicologo.nombre})'

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellidos}'.strip()


class Turno(models.Model):
    """Reserva puntual. Guarda un snapshot de los datos de contacto tal como
    se cargaron al reservar (los de la ficha del paciente pueden cambiar
    después); `paciente` linkea a esa ficha para poder ver la historia."""
    ESTADO_CHOICES = [
        ('agendado', 'Agendado'),
        ('realizado', 'Realizado'),
        ('ausente', 'No asistió'),
        ('cancelado', 'Cancelado'),
    ]
    MODALIDAD_CHOICES = [
        ('online', 'Online'),
        ('presencial', 'Presencial'),
    ]

    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='turnos')
    paciente = models.ForeignKey(
        Paciente, on_delete=models.SET_NULL, null=True, blank=True, related_name='turnos'
    )
    tipo_sesion = models.ForeignKey(TipoSesion, on_delete=models.PROTECT, related_name='turnos')
    fecha_hora = models.DateTimeField()
    modalidad = models.CharField(max_length=12, choices=MODALIDAD_CHOICES)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='agendado')

    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30)
    email = models.EmailField()
    edad = models.PositiveIntegerField(null=True, blank=True)
    motivo_consulta = models.TextField(blank=True)
    notas_profesional = models.TextField(
        'Notas del profesional', blank=True,
        help_text='Privadas, para esta sesión puntual.'
    )

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'
        ordering = ['-fecha_hora']

    def __str__(self):
        return f'{self.nombres} {self.apellidos} con {self.psicologo.nombre} el {self.fecha_hora:%d/%m %H:%M}'

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellidos}'.strip()

    @property
    def es_futuro(self):
        return self.fecha_hora >= timezone.now()
