from django import forms
from django.contrib.auth.models import User
from django.forms import inlineformset_factory

from directorio.models import Formacion, Psicologo


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
        label='¿No está en la lista? Escribilo acá', max_length=60, required=False,
        help_text='Ej: "Adultos mayores", "Deportistas" -- se agrega a las opciones para todos'
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
