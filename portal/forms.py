import io

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.forms import inlineformset_factory
from django.urls import reverse
from django.utils.html import format_html
from PIL import Image, ImageOps

from directorio.forms import HoneypotMixin
from django.db.models import Q

from directorio.models import Ciudad, Formacion, Orientacion, Psicologo, Publico
from turnos.models import DiaNoAtiende, DisponibilidadSemanal, Paciente, TipoSesion


class LoginForm(AuthenticationForm):
    # El mensaje default de Django para cuenta inactiva es genérico y en
    # inglés -- acá "inactiva" siempre significa "todavía no confirmó el
    # email" (ver portal/views.py::registro), así que el mensaje lo dice
    # directo en vez de un "cuenta inactiva" que no explica qué hacer.
    error_messages = {
        **AuthenticationForm.error_messages,
        'inactive': (
            'Todavía no confirmaste tu email. Revisá tu correo (y la carpeta de spam) '
            'o pedí que te reenviemos el link desde la página de registro.'
        ),
    }


class RegistroForm(HoneypotMixin, forms.Form):
    nombre = forms.CharField(label='Nombre y apellido', max_length=150)
    email = forms.EmailField(label='Email')
    whatsapp = forms.CharField(label='WhatsApp', max_length=30)
    password = forms.CharField(label='Contraseña', widget=forms.PasswordInput, min_length=8)
    # dLocal Go pidió consentimiento explícito, no implícito por el solo
    # hecho de registrarse -- checkbox propio, sin marcar por defecto.
    acepto_terminos = forms.BooleanField(
        required=True,
        error_messages={'required': 'Tenés que aceptar los Términos y la Política de Privacidad para crear tu cuenta.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['acepto_terminos'].label = format_html(
            'Leí y acepto los <a href="{}" target="_blank" rel="noopener">Términos y Condiciones</a> '
            'y la <a href="{}" target="_blank" rel="noopener">Política de Privacidad</a>.',
            reverse('terminos'), reverse('privacidad'),
        )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con ese email.')
        return email


class _ChecksConPendientes(forms.ModelMultipleChoiceField):
    """Casillas de orientaciones/públicos: lo que el profesional propuso a
    mano y todavía no aprobó la dueña se ve marcado, solo en SU formulario."""

    def label_from_instance(self, obj):
        return obj.nombre if obj.aprobado else f'{obj.nombre} (pendiente de aprobación)'


class PerfilForm(forms.ModelForm):
    # Campos que no son del modelo -- si el profesional escribe algo acá, la
    # vista (portal/views.py::editar_perfil) crea una propuesta PENDIENTE (o
    # reusa la que ya exista con ese nombre): la ve solo él hasta que la
    # dueña la apruebe desde el admin, y recién ahí pasa a la lista de todos.
    # `field_order` los deja pegados a la lista a la que corresponden (si no,
    # Django los manda al final del formulario).
    ciudad_nueva = forms.CharField(
        label='¿Tu ciudad no está en la lista? Escribila acá', max_length=100, required=False,
        help_text='La revisamos y la sumamos a la lista. Mientras tanto no se muestra en tu perfil público.'
    )
    orientacion_nueva = forms.CharField(
        label='¿Tu orientación no está en la lista? Escribila acá', max_length=60, required=False,
        help_text='Ej: "Gestalt", "EMDR". La revisamos y, si corresponde, la sumamos para todos; mientras tanto la ves solo vos.'
    )
    publico_nuevo = forms.CharField(
        label='¿El público que atendés no está en la lista? Escribilo acá', max_length=60, required=False,
        help_text='Ej: "Adultos mayores", "Deportistas". Lo revisamos y, si corresponde, lo sumamos para todos; mientras tanto lo ves solo vos.'
    )

    class Meta:
        model = Psicologo
        fields = [
            'nombre', 'matricula', 'whatsapp', 'ciudad', 'modalidad',
            'foto', 'bio', 'docencia', 'precio_sesion', 'sesiones_atendidas',
            'orientaciones', 'publicos',
        ]
        field_classes = {
            'orientaciones': _ChecksConPendientes,
            'publicos': _ChecksConPendientes,
        }
        widgets = {
            'orientaciones': forms.CheckboxSelectMultiple,
            'publicos': forms.CheckboxSelectMultiple,
            'bio': forms.Textarea(attrs={'rows': 4}),
            'docencia': forms.Textarea(attrs={'rows': 3}),
        }

    field_order = [
        'nombre', 'matricula', 'whatsapp', 'ciudad', 'ciudad_nueva', 'modalidad',
        'foto', 'bio', 'docencia', 'precio_sesion', 'sesiones_atendidas',
        'orientaciones', 'orientacion_nueva', 'publicos', 'publico_nuevo',
    ]

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

        psicologo = self.instance if self.instance.pk else None

        # Orientaciones y públicos: las aprobadas, más las que propuso este
        # profesional, más las que ya tiene tildadas (por si otra persona
        # propuso lo mismo antes y se le reusó esa).
        for campo, Modelo in (('orientaciones', Orientacion), ('publicos', Publico)):
            visibles = Q(aprobado=True)
            if psicologo:
                visibles |= Q(propuesto_por=psicologo) | Q(psicologos=psicologo)
            self.fields[campo].queryset = Modelo.objects.filter(visibles).distinct()

        # Ciudad: desplegable con las del país en vez de texto libre.
        opciones = [('', 'Elegí tu ciudad')]
        ciudad_actual = (self.instance.ciudad or '').strip() if psicologo else ''
        if pais:
            visibles = Q(aprobado=True)
            if psicologo:
                visibles |= Q(propuesto_por=psicologo)
            for c in Ciudad.objects.filter(visibles, pais=pais):
                opciones.append((c.nombre, c.nombre if c.aprobado else f'{c.nombre} (pendiente de aprobación)'))
        if ciudad_actual and ciudad_actual not in [v for v, _ in opciones]:
            opciones.append((ciudad_actual, ciudad_actual))
        self.fields['ciudad'] = forms.ChoiceField(
            label='Ciudad', choices=opciones, required=False,
            initial=ciudad_actual,
            help_text='Si atendés solo online y no querés mostrar una ciudad, dejalo en blanco.',
        )

    def clean_foto(self):
        """Redimensiona y comprime la foto recién subida (no la ya guardada,
        esa ya pasó por acá una vez) -- un celular moderno sube fotos de
        varios MB, y eso pesa la carga de cada página del buscador."""
        foto = self.cleaned_data.get('foto')
        if foto and hasattr(foto, 'file'):
            foto = _comprimir_foto(foto)
        return foto


def _comprimir_foto(archivo, lado_maximo=1200, calidad=82):
    archivo.seek(0)
    imagen = ImageOps.exif_transpose(Image.open(archivo))
    if imagen.mode not in ('RGB', 'L'):
        imagen = imagen.convert('RGB')
    ancho, alto = imagen.size
    lado_mayor = max(ancho, alto)
    if lado_mayor > lado_maximo:
        factor = lado_maximo / lado_mayor
        imagen = imagen.resize((round(ancho * factor), round(alto * factor)), Image.LANCZOS)
    buffer = io.BytesIO()
    imagen.save(buffer, format='JPEG', quality=calidad, optimize=True)
    tamano = buffer.tell()
    buffer.seek(0)
    nombre = archivo.name.rsplit('.', 1)[0] + '.jpg'
    return InMemoryUploadedFile(buffer, 'ImageField', nombre, 'image/jpeg', tamano, None)


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
