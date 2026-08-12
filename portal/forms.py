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
    class Meta:
        model = Psicologo
        fields = [
            'nombre', 'matricula', 'whatsapp', 'ciudad', 'modalidad',
            'foto', 'bio', 'docencia', 'precio_sesion',
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


FormacionFormSet = inlineformset_factory(
    Psicologo, Formacion,
    fields=['descripcion'],
    extra=1, can_delete=True,
)
