# Levantar el proyecto en local

Notas para arrancar a trabajar en otra máquina (Windows / macOS / Linux).

## Requisitos

- **Python 3.12** &nbsp;→ importante, **no uses 3.13 ni 3.14**:
  - `pillow==10.3.0` y `psycopg2-binary==2.9.9` (los pins de `requirements.txt`)
    no tienen wheel para 3.13+ y fallan al compilar.
  - `Django==5.0.4` además se rompe al renderar templates en los tests bajo 3.14.
  - Si tenés solo 3.14 instalado: `winget install -e --id Python.Python.3.12`
    (Windows) o `brew install python@3.12` (macOS).
- Git.

## Pasos

```bash
# 1. Traer el código
git clone https://github.com/LeandroFrattini/atencionpsi-latam.git
cd atencionpsi-latam
git checkout portal-agenda-pacientes      # rama donde está el portal (agenda / turnos / pacientes)

# 2. Entorno virtual con Python 3.12
py -3.12 -m venv venv                      # Windows
#   python3.12 -m venv venv                # macOS / Linux

venv\Scripts\activate                      # Windows (PowerShell/CMD)
#   source venv/bin/activate               # macOS / Linux

python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Base de datos local (SQLite, se crea sola)
python manage.py migrate

# 4. Datos de prueba (países, orientaciones, profesionales, agenda, pacientes y turnos)
python manage.py seed_demo

# 5. Levantar el server
python manage.py runserver
```

Queda en http://127.0.0.1:8000/

## Accesos de demo (los crea `seed_demo`)

| Qué | Usuario | Clave |
|---|---|---|
| Portal de un profesional | `lucia.fernandez@demo.atencionpsi.lat` | `DemoPsi12345` |
| Django admin (`/admin/`) | `admin@demo.atencionpsi.lat` | `DemoPsi12345` |

Otros profesionales de demo: `martin.rodriguez@demo.atencionpsi.lat`,
`camila.torres@demo.atencionpsi.lat` (misma clave).

- `python manage.py seed_demo` es idempotente: se puede correr las veces que quieras.
- `python manage.py seed_demo --wipe` borra **solo** lo de demo (todo lo que
  usa mails `@demo.atencionpsi.lat`) sin tocar datos reales.

## Cosas a tener en cuenta

- **SQLite en local, Postgres en Render.** `settings.py` usa SQLite salvo que exista
  la variable de entorno `RENDER`. El archivo `db.sqlite3` está en `.gitignore`, así
  que cada máquina tiene su propia base — sincronizás por `seed_demo`, no por la DB.
- **Mails a consola.** En local `EMAIL_BACKEND` es el de consola: los mails
  (recordatorios, aviso de reserva, formulario de contacto) se imprimen en la
  terminal del `runserver`, no se mandan.
- **`SECRET_KEY`** tiene un default de desarrollo; no hace falta setear nada.
- **dLocal Go** todavía no está integrado de verdad. En `DEBUG` hay un botón de
  "simular pago" en el checkout para probar el flujo completo.
- La carpeta `.claude/` está en `.gitignore` (config local de la herramienta, no se versiona).

## Tests

```bash
python manage.py test
```
