from django import forms


class ReservaDatosForm(forms.Form):
    nombres = forms.CharField(label='Nombres', max_length=100)
    apellidos = forms.CharField(label='Apellidos', max_length=100)
    telefono = forms.CharField(label='Teléfono', max_length=30)
    email = forms.EmailField(label='Email')
    edad = forms.IntegerField(label='Edad (opcional)', required=False, min_value=0, max_value=120)
    motivo_consulta = forms.CharField(
        label='Motivo de consulta (opcional)', required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describí brevemente por qué querés una consulta...'})
    )
