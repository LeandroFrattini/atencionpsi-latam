from django import forms


class HoneypotMixin(forms.Form):
    """Campo trampa contra spam para los formularios públicos sin login
    (contacto, registro de profesional, reserva de turno). No hace falta
    reCAPTCHA para un sitio de este tamaño: alcanza con un campo que ningún
    humano completa (está oculto por CSS, no por HTML, para que los bots que
    solo evitan los `type="hidden"` igual caigan) pero que un script que
    llena todos los inputs sí rellena. Si llega con algo, se descarta como
    spam. El nombre del campo (`sitio_web`) y su id (`id_sitio_web`) están
    hardcodeados en el CSS (`.hp-trampa`) -- si se renombra acá, actualizar
    también static/css/base.css."""
    sitio_web = forms.CharField(
        label='Sitio web', required=False,
        widget=forms.TextInput(attrs={'class': 'hp-trampa', 'tabindex': '-1', 'autocomplete': 'off'}),
    )

    def clean_sitio_web(self):
        valor = self.cleaned_data.get('sitio_web')
        if valor:
            raise forms.ValidationError('No se pudo procesar el formulario.')
        return valor


class ContactoForm(HoneypotMixin, forms.Form):
    nombre = forms.CharField(label='Nombre', max_length=150)
    email = forms.EmailField(label='Email')
    mensaje = forms.CharField(label='Mensaje', widget=forms.Textarea(attrs={'rows': 5}))
