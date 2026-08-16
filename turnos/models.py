from django.db import models


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


class Turno(models.Model):
    """Reserva hecha por un paciente. Guarda los datos de contacto directo
    en vez de un modelo Paciente aparte -- acá no hay CRM de pacientes
    (todavía), solo la reserva puntual."""
    ESTADO_CHOICES = [
        ('agendado', 'Agendado'),
        ('cancelado', 'Cancelado'),
    ]
    MODALIDAD_CHOICES = [
        ('online', 'Online'),
        ('presencial', 'Presencial'),
    ]

    psicologo = models.ForeignKey('directorio.Psicologo', on_delete=models.CASCADE, related_name='turnos')
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

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'
        ordering = ['-fecha_hora']

    def __str__(self):
        return f'{self.nombres} {self.apellidos} con {self.psicologo.nombre} el {self.fecha_hora:%d/%m %H:%M}'
