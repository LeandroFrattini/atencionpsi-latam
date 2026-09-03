from django import forms


class ContactoForm(forms.Form):
    nombre = forms.CharField(label='Nombre', max_length=150)
    email = forms.EmailField(label='Email')
    mensaje = forms.CharField(label='Mensaje', widget=forms.Textarea(attrs={'rows': 5}))
