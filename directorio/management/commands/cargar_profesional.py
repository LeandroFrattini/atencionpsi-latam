"""Carga a mano a una profesional (usuario + perfil) que no pasó por el registro, por ejemplo una que ya pagó.

Los datos viajan en un JSON codificado en base64 (`--datos`), así se pegan en una sola línea sin problemas de
comillas ni de tildes, y NO quedan en el repositorio. Qué hace:

* crea el usuario (ya activo) SIN contraseña y le manda un mail de bienvenida con un link para crear la suya
  (así nunca circula una contraseña); `--sin-mail` no manda ese mail;
* crea el perfil con sus orientaciones, motivos de consulta y público (los nombres tienen que existir ya y
  estar aprobados; ignora mayúsculas y tildes). Si algo no coincide no crea nada y lista las opciones;
* consulta a dLocal Go: si encuentra su suscripción con ese mismo email, la deja activa. Con `--marcar-pagado`
  la activa a mano si dLocal no la encuentra;
* con `--publicar` deja dicho que quiere publicar (se muestra apenas el perfil esté completo; falta la foto,
  que se sube desde el admin).

Campos del JSON: email, nombre, pais (slug), matricula, whatsapp, bio, plan (basico|premium) y, opcionales,
ciudad, modalidad (online|presencial|ambas), instagram, orientaciones, especialidades, publicos (listas).
"""
import base64
import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from directorio import dlocal_go, suscripciones
from directorio.models import Especialidad, Orientacion, Pais, Psicologo, Publico
from directorio.taxonomia import clave
from portal import contrasenas

OBLIGATORIOS = ('email', 'nombre', 'pais', 'matricula', 'whatsapp', 'bio', 'plan')


def _buscar(modelo, nombres, etiqueta):
    """Los objetos aprobados que corresponden a esos nombres. Si alguno no existe, error con las opciones."""
    por_clave = {clave(o.nombre): o for o in modelo.objects.filter(aprobado=True)}
    encontrados, faltan = [], []
    for nombre in nombres:
        objeto = por_clave.get(clave(nombre))
        (encontrados if objeto else faltan).append(objeto or nombre)
    if faltan:
        disponibles = ', '.join(sorted(o.nombre for o in por_clave.values()))
        raise CommandError(f'No existe en {etiqueta}: {", ".join(faltan)}. Opciones: {disponibles}')
    return encontrados


class Command(BaseCommand):
    help = 'Carga a mano a una profesional (usuario + perfil). Los datos van en --datos (JSON en base64).'

    def add_arguments(self, parser):
        parser.add_argument('--datos', required=True, help='JSON en base64 con los datos de la profesional.')
        parser.add_argument('--marcar-pagado', action='store_true',
                            help='Si dLocal no encuentra su suscripción, la deja activa a mano.')
        parser.add_argument('--sin-mail', action='store_true', help='No mandar el mail de bienvenida con el link para crear la contraseña.')
        parser.add_argument('--publicar', action='store_true', help='Deja dicho que quiere publicar su perfil.')

    def handle(self, *args, **opciones):
        datos = self._leer(opciones['datos'])
        email = datos['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise CommandError(f'Ya existe un usuario con el email {email}. No se creó nada.')
        try:
            pais = Pais.objects.get(slug=datos['pais'])
        except Pais.DoesNotExist:
            raise CommandError(f'No existe el país "{datos["pais"]}".')
        if datos['plan'] not in dict(Psicologo.PLAN_CHOICES):
            raise CommandError('El plan tiene que ser "basico" o "premium".')
        modalidad = datos.get('modalidad', 'online')
        if modalidad not in dict(Psicologo.MODALIDAD_CHOICES):
            raise CommandError('La modalidad tiene que ser "online", "presencial" o "ambas".')
        orientaciones = _buscar(Orientacion, datos.get('orientaciones', []), 'orientaciones')
        especialidades = _buscar(Especialidad, datos.get('especialidades', []), 'motivos de consulta')
        publicos = _buscar(Publico, datos.get('publicos', []), 'público')

        with transaction.atomic():
            usuario = User.objects.create_user(username=email, email=email, password=None, is_active=True)
            psicologo = Psicologo.objects.create(
                usuario=usuario, pais=pais, nombre=datos['nombre'].strip(), matricula=datos['matricula'].strip(),
                whatsapp=datos['whatsapp'].strip(), bio=datos['bio'].strip(), plan=datos['plan'],
                ciudad=(datos.get('ciudad') or '').strip(), modalidad=modalidad,
                instagram=(datos.get('instagram') or '').strip().lstrip('@'),
                terminos_aceptados_en=timezone.now(), publicado_por_usuario=opciones['publicar'],
            )
            psicologo.orientaciones.set(orientaciones)
            psicologo.especialidades.set(especialidades)
            psicologo.publicos.set(publicos)

        self.stdout.write(self.style.SUCCESS(f'Creada: {psicologo.nombre} (id {psicologo.pk}, {pais.nombre}).'))
        self._pago(psicologo, opciones['marcar_pagado'])
        psicologo.refresh_from_db()
        faltan = psicologo.faltantes_perfil
        if faltan:
            self.stdout.write(self.style.WARNING('Para publicarse le falta: ' + ', '.join(faltan) + '. La foto se sube desde el admin.'))
        elif psicologo.publicado:
            self.stdout.write(self.style.SUCCESS('Su perfil ya está publicado.'))
        else:
            self.stdout.write('El perfil está completo: falta que ella (o vos desde el admin) toque «Publicar».')
        self._bienvenida(psicologo, opciones['sin_mail'])

    def _bienvenida(self, psicologo, sin_mail):
        email = psicologo.usuario.email
        if sin_mail:
            self.stdout.write(f'\nNo se mandó el mail de bienvenida (--sin-mail). Para que cree su contraseña, desde la pantalla de ingreso '
                              f'tiene que tocar «¿Olvidaste tu contraseña?» con {email}.')
            return
        try:
            contrasenas.enviar_bienvenida(psicologo)
        except Exception as error:
            self.stdout.write(self.style.WARNING(
                f'\nNo se pudo mandar el mail de bienvenida a {email} ({error}). Que entre a la pantalla de ingreso y toque '
                '«¿Olvidaste tu contraseña?» con ese email: le llega el link para crearla.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f'\nLe mandamos a {email} el mail de bienvenida con el link para crear su contraseña (vale '
            f'{contrasenas.dias_de_validez()} días). Si no lo ve, que revise el spam.'))

    def _leer(self, texto):
        try:
            datos = json.loads(base64.b64decode(texto.encode('ascii')).decode('utf-8'))
        except Exception:
            raise CommandError('No pude leer --datos: tiene que ser un JSON codificado en base64.')
        if not isinstance(datos, dict):
            raise CommandError('--datos tiene que ser un objeto JSON.')
        faltan = [c for c in OBLIGATORIOS if not str(datos.get(c, '')).strip()]
        if faltan:
            raise CommandError('Faltan datos: ' + ', '.join(faltan))
        return datos

    def _pago(self, psicologo, marcar_pagado):
        if dlocal_go.conectado():
            try:
                estado = suscripciones.sincronizar_psicologo(psicologo)
            except dlocal_go.DLocalError as error:
                estado = None
                self.stdout.write(self.style.WARNING(f'No pude consultar a dLocal Go ({error}).'))
            if estado:
                self.stdout.write(f'Pago según dLocal Go: {estado}.')
            psicologo.refresh_from_db()
        else:
            self.stdout.write(self.style.WARNING('dLocal Go no está conectado en este entorno: no se consultó el pago.'))
        if psicologo.suscripcion_activa:
            self.stdout.write(self.style.SUCCESS(f'Suscripción activa (plan {psicologo.get_plan_display()}).'))
        elif marcar_pagado:
            psicologo.activar_suscripcion(plan=psicologo.plan)
            self.stdout.write(self.style.SUCCESS('Suscripción marcada como activa a mano (--marcar-pagado).'))
        else:
            self.stdout.write(self.style.WARNING(
                'dLocal no encontró su pago con ese email: todavía NO figura activa. Si ya pagó (con otro mail, por '
                'ejemplo), tildá «Suscripción activa» en su ficha del admin. (La próxima vez, corré el comando con '
                '--marcar-pagado para que quede activa a mano.)'))
