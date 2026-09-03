from django import forms
from django.contrib.auth.models import User
from django.forms import inlineformset_factory

from directorio.models import Formacion, Psicologo
from turnos.models import DiaNoAtiende, DisponibilidadSemanal, Paciente, TipoSesion


class RegistroForm(forms.Form):
    nombre = forms.CharField(label='Nombre y apellido', max_length=150)
    email = forms.EmailField(label='Email')
    whatsapp = forms.CharField(label='WhatsApp', max_length=30)
    password = forms.CharField(label='Contraseña', widget=forms.PasswordInput, min_length=8)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con ese email.')
        return email


class PerfilForm(forms.ModelForm):
    # No es un campo del modelo -- si el profesional escribe algo acá, la
    # vista crea (o reusa si ya existe) un Publico nuevo y se lo agrega.
    # Así la lista de "¿Para quién?" crece sola con lo que va apareciendo en
    # cada país, en vez de que la dueña tenga que darlas de alta a mano en
    # el admin antes de que alguien las pueda usar.
    publico_nuevo = forms.CharField(
        label='¿El público que atendés no está en la lista? Escribilo acá', max_length=60, required=False,
        help_text='Ej: "Adultos mayores", "Deportistas" -- se agrega a las opciones para todos'
    )
    # Mismo patrón que publico_nuevo, para Orientación -- estaba asimétrico
    # que "¿Para quién?" pudiera crecer sola y "Orientación" no. El form
    # renderiza los campos declarados acá (no del modelo) al final, después
    # de las dos listas de checkboxes -- por eso los labels tienen que
    # aclarar a cuál lista corresponde cada uno, no alcanza con la posición.
    orientacion_nueva = forms.CharField(
        label='¿Tu orientación no está en la lista? Escribila acá', max_length=60, required=False,
        help_text='Ej: "Gestalt", "EMDR" -- se agrega a las opciones para todos'
    )

    class Meta:
        model = Psicologo
        fields = [
            'nombre', 'matricula', 'whatsapp', 'ciudad', 'modalidad',
            'foto', 'bio', 'docencia', 'precio_sesion', 'sesiones_atendidas',
            'orientaciones', 'publicos',
        ]
        widgets = {
            'orientaciones': forms.CheckboxSelectMultiple,
            'publicos': forms.CheckboxSelectMultiple,
            'bio': forms.Textarea(attrs={'rows': 4}),
            'docencia': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, pais=None, **kwargs):
        super().__init__(*args, **kwargs)
        if pais:
            self.fields['matricula'].label = pais.etiqueta_matricula
            if not pais.muestra_precio_sesion:
                del self.fields['precio_sesion']
        # La opción en blanco que arma Django para un choices field opcional
        # sale en inglés por defecto ("- Select an option -") -- se pisa acá
        # en vez de una traducción global porque es la única del sitio.
        self.fields['sesiones_atendidas'].choices = (
            [('', 'Preferís no decir por ahora')] + Psicologo.SESIONES_CHOICES
        )


FormacionFormSet = inlineformset_factory(
    Psicologo, Formacion,
    fields=['descripcion'],
    extra=1, can_delete=True,
)


# --- Agenda del profesional -------------------------------------------------
# Tres formsets que se editan juntos en /portal/agenda/. Los widgets nativos
# type="time"/type="date" evitan tener que sumar una librería de datepicker.

_hora = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
_fecha = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class DisponibilidadForm(forms.ModelForm):
    class Meta:
        model = DisponibilidadSemanal
        fields = ['dia_semana', 'hora_desde', 'hora_hasta']
        widgets = {'hora_desde': _hora, 'hora_hasta': _hora}

    def clean(self):
        cleaned = super().clean()
        desde, hasta = cleaned.get('hora_desde'), cleaned.get('hora_hasta')
        if desde and hasta and desde >= hasta:
            raise forms.ValidationError('El horario "desde" tiene que ser anterior al "hasta".')
        return cleaned


class DiaNoAtiendeForm(forms.ModelForm):
    class Meta:
        model = DiaNoAtiende
        fields = ['fecha_desde', 'fecha_hasta', 'motivo']
        widgets = {'fecha_desde': _fecha, 'fecha_hasta': _fecha}

    def clean(self):
        cleaned = super().clean()
        desde, hasta = cleaned.get('fecha_desde'), cleaned.get('fecha_hasta')
        if desde and hasta and desde > hasta:
            raise forms.ValidationError('La fecha "desde" no puede ser posterior a la "hasta".')
        return cleaned


TipoSesionFormSet = inlineformset_factory(
    Psicologo, TipoSesion,
    fields=['nombre', 'duracion_min', 'precio', 'orden'],
    extra=1, can_delete=True,
)

DisponibilidadFormSet = inlineformset_factory(
    Psicologo, DisponibilidadSemanal,
    form=DisponibilidadForm,
    extra=2, can_delete=True,
)

DiaNoAtiendeFormSet = inlineformset_factory(
    Psicologo, DiaNoAtiende,
    form=DiaNoAtiendeForm,
    extra=1, can_delete=True,
)


# --- Pacientes ------------------------------------------------------------
class PacienteForm(forms.ModelForm):
    class Meta:
        model = Paciente
        fields = ['nombres', 'apellidos', 'telefono', 'email', 'edad', 'notas']
        widgets = {'notas': forms.Textarea(attrs={'rows': 5})}

    def __init__(self, *args, psicologo=None, **kwargs):
        self.psicologo = psicologo
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and self.psicologo:
            chocan = Paciente.objects.filter(psicologo=self.psicologo, email=email)
            if self.instance.pk:
                chocan = chocan.exclude(pk=self.instance.pk)
            if chocan.exists():
                raise forms.ValidationError('Ya tenés una ficha de paciente con ese email.')
        return email
