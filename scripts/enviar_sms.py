"""Manda la invitación por SMS, uno por uno y con el nombre de cada invitado, usando Twilio. Solo usa la biblioteca estándar.

    python scripts/enviar_sms.py contactos.csv --url https://tu-dominio.com            # ensayo: enseña qué mandaría, no manda nada
    python scripts/enviar_sms.py contactos.csv --url https://tu-dominio.com --enviar    # manda de verdad

`contactos.csv` lleva una fila por invitado y un encabezado con las columnas `nombre` y `telefono`
(también valen `name`, `phone`, `celular`…; el separador puede ser coma, punto y coma o tabulador, como lo exporta Excel):

    nombre,telefono
    Ana Torres,55 1234 5678
    Luis,+52 1 33 9876 5432

El nombre sale tal cual en el mensaje: escríbelo como quieres que le hablen. Los teléfonos de México se escriben como sea (espacios,
guiones, 044, +52 1…) y se convierten a +52XXXXXXXXXX; los de otro país, con su "+" (o dime el país con --pais).

Las credenciales van en variables de entorno, nunca en el repo ni en la página:
    TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN
    y una de estas dos: TWILIO_FROM (el número desde el que mandas, +1…) o TWILIO_MESSAGING_SERVICE_SID (MG…)

Junto al CSV queda `<csv>.envios.csv` con lo que pasó con cada número: si lo vuelves a correr, a quien ya se le mandó se le salta.
Los teléfonos son datos personales: ni el CSV ni el registro se suben al repo (el .gitignore ya los ignora).
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

# El tono de la invitación en una línea, quién la manda (a un número desconocido hay que dejárselo claro) y el enlace con su nombre.
# No lleva la dirección: el servidor no la suelta hasta la hora que fijes, y por SMS no habría quien la protegiera.
MENSAJE = 'Mariela cumple 29: hay fiesta en la CDMX y alguien no va a salir viva. XOXO\n{nombre}, tu invitación: {url}'
TOPE = 40  # más mensajes que esto en una corrida pide confirmarlo con --max: lo normal en una fiesta son 20
API = 'https://api.twilio.com'
PAUSA = 1.1  # Twilio manda un mensaje por segundo por número; ir más rápido solo los encola

NOMBRES = {'nombre', 'name', 'invitado'}
TELEFONOS = {'telefono', 'celular', 'movil', 'phone', 'tel', 'whatsapp', 'numero'}
ENVIADO, FALLO, INCIERTO = 'enviado', 'fallo', 'incierto'

# Lo que Twilio contesta cuando algo no cuadra, con la pista de qué hacer. El mensaje original de Twilio se muestra siempre.
PISTAS = {
    '20003': 'las credenciales no son válidas: revisa TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN',
    '21211': 'ese número no es válido',
    '21408': 'tu cuenta no tiene permiso de mandar a ese país: en Twilio, Messaging → Settings → Geo permissions',
    '21606': 'el número de TWILIO_FROM no puede mandar SMS',
    '21608': 'cuenta de prueba: solo puede mandar a números que verificaste en la consola de Twilio',
    '21610': 'esa persona respondió STOP: no le puedes escribir',
    '21614': 'ese número no puede recibir SMS',
}


# ------------------------------------------------------------------------------------------------- teléfonos
def normalizar_telefono(crudo: str, pais: str = '52') -> str | None:
    """Un teléfono como lo escribe la gente → E.164 (+525512345678), o None si no se puede."""
    texto = crudo.strip()
    internacional = texto.startswith('+')
    digitos = re.sub(r'\D', '', texto)
    if not internacional and digitos.startswith('00'):  # 001 415…: el prefijo para marcar al extranjero
        digitos, internacional = digitos[2:], True
    if not digitos:
        return None
    if not internacional:
        if pais == '52':
            if digitos.startswith(('044', '045')):  # el marcado viejo de celular
                digitos = digitos[3:]
            if len(digitos) == 10:
                digitos = '52' + digitos
            elif not (len(digitos) in (12, 13) and digitos.startswith('52')):
                return None
        elif not (len(digitos) > 10 and digitos.startswith(pais)):
            digitos = pais + digitos.lstrip('0')
    if digitos.startswith('521') and len(digitos) == 13:  # el 1 de los celulares (+52 1 …) ya no se marca desde 2019
        digitos = '52' + digitos[3:]
    if digitos.startswith('52') and len(digitos) != 12:
        return None
    return f'+{digitos}' if re.fullmatch(r'[1-9]\d{7,14}', digitos) else None


def bonito(telefono: str) -> str:
    """+525512345678 → +52 55 1234 5678 (México; el resto se deja como está)."""
    if telefono.startswith('+52') and len(telefono) == 13:
        n = telefono[3:]
        if n[:2] in ('55', '33', '81'):  # CDMX, Guadalajara y Monterrey tienen lada de dos cifras
            return f'+52 {n[:2]} {n[2:6]} {n[6:]}'
        return f'+52 {n[:3]} {n[3:6]} {n[6:]}'
    return telefono


# ------------------------------------------------------------------------------------------------- mensaje
_GSM7 = frozenset('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà')
_GSM7_DOBLES = frozenset('\f^{}\\[~]|€')


def segmentos(texto: str) -> tuple[str, int]:
    """(codificación, cuántos SMS cobra el operador). Con una sola letra fuera del alfabeto GSM (una "á", un emoji) todo el mensaje
    pasa a UCS-2 y caben 70 caracteres por SMS en vez de 160 (67 y 153 cuando se parte en varios)."""
    if all(c in _GSM7 or c in _GSM7_DOBLES for c in texto):
        septetos = sum(2 if c in _GSM7_DOBLES else 1 for c in texto)
        return 'GSM-7', 1 if septetos <= 160 else math.ceil(septetos / 153)
    unidades = len(texto.encode('utf-16-le')) // 2
    return 'UCS-2', 1 if unidades <= 70 else math.ceil(unidades / 67)


def armar_mensaje(plantilla: str, nombre: str, url: str) -> str:
    return plantilla.replace('{nombre}', nombre).replace('{url}', url)


# ------------------------------------------------------------------------------------------------- contactos y registro
@dataclass
class Contacto:
    fila: int
    nombre: str
    crudo: str
    telefono: str | None = None
    problema: str = ''


def _clave(texto: str) -> str:
    sin_acentos = ''.join(c for c in unicodedata.normalize('NFD', texto) if not unicodedata.combining(c))
    return re.sub(r'[^a-z]', '', sin_acentos.lower())


def leer_contactos(ruta: Path, pais: str = '52') -> list[Contacto]:
    """Lee el CSV (con o sin BOM de Excel; coma, punto y coma o tabulador) y marca los que no se pueden mandar."""
    texto = ruta.read_text(encoding='utf-8-sig')
    lineas = texto.splitlines()
    primera = lineas[0] if lineas else ''
    delimitador = max(',;\t', key=primera.count) if any(d in primera for d in ',;\t') else ','
    lector = csv.DictReader(lineas, delimiter=delimitador)
    columnas = {_clave(c): c for c in (lector.fieldnames or []) if c}
    col_nombre = next((columnas[k] for k in columnas if k in NOMBRES), None)
    col_telefono = next((columnas[k] for k in columnas if k in TELEFONOS), None)
    if not col_nombre or not col_telefono:
        fallar(
            f'No encontré las columnas `nombre` y `telefono` en {ruta.name} (vi: {", ".join(lector.fieldnames or []) or "nada"}).\n'
            'La primera línea tiene que ser el encabezado:\n\n    nombre,telefono\n    Ana Torres,55 1234 5678'
        )
    contactos: list[Contacto] = []
    vistos: dict[str, str] = {}
    for fila, registro in enumerate(lector, start=2):
        nombre = (registro.get(col_nombre) or '').strip()
        crudo = (registro.get(col_telefono) or '').strip()
        if not nombre and not crudo:
            continue
        c = Contacto(fila, nombre, crudo)
        if not nombre:
            c.problema = 'falta el nombre'
        else:
            c.telefono = normalizar_telefono(crudo, pais)
            if not c.telefono:
                c.problema = f'el teléfono «{crudo}» no es válido' if crudo else 'falta el teléfono'
            elif c.telefono in vistos:
                c.problema = f'repetido (es el mismo número de {vistos[c.telefono]})'
                c.telefono = None
            else:
                vistos[c.telefono] = nombre
        contactos.append(c)
    return contactos


def leer_registro(ruta: Path) -> dict[str, str]:
    """teléfono → último estado (enviado, fallo o incierto) de lo que se intentó en corridas anteriores."""
    if not ruta.exists():
        return {}
    with ruta.open(encoding='utf-8', newline='') as f:
        return {fila['telefono']: fila['estado'] for fila in csv.DictReader(f) if fila.get('telefono')}


def anotar(ruta: Path, c: Contacto, estado: str, sid: str = '', detalle: str = '') -> None:
    nuevo = not ruta.exists()
    with ruta.open('a', encoding='utf-8', newline='') as f:
        escritor = csv.writer(f)
        if nuevo:
            escritor.writerow(['telefono', 'nombre', 'estado', 'sid', 'detalle', 'cuando'])
        escritor.writerow([c.telefono, c.nombre, estado, sid, detalle, dt.datetime.now().isoformat(timespec='seconds')])


# ------------------------------------------------------------------------------------------------- Twilio
@dataclass
class Twilio:
    sid: str
    token: str
    desde: str = ''
    servicio: str = ''
    base: str = API


@dataclass
class Resultado:
    estado: str  # ENVIADO, FALLO o INCIERTO
    sid: str = ''
    segmentos: int = 0
    error: str = ''


def mandar(cfg: Twilio, para: str, cuerpo: str) -> Resultado:
    """Un SMS por la API REST de Twilio. Sin respuesta (se cortó la red a medias) no se sabe si salió: eso es INCIERTO, no FALLO."""
    datos = {'To': para, 'Body': cuerpo}
    if cfg.servicio:
        datos['MessagingServiceSid'] = cfg.servicio
    else:
        datos['From'] = cfg.desde
    credencial = base64.b64encode(f'{cfg.sid}:{cfg.token}'.encode()).decode()
    peticion = urllib.request.Request(
        f'{cfg.base}/2010-04-01/Accounts/{urllib.parse.quote(cfg.sid)}/Messages.json',
        data=urllib.parse.urlencode(datos).encode(),
        headers={'Authorization': f'Basic {credencial}', 'Accept': 'application/json', 'User-Agent': 'mariela-invitacion'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            cuerpo_json = json.load(respuesta)
    except urllib.error.HTTPError as error:
        try:
            detalle = json.load(error)
        except (ValueError, OSError):
            detalle = {}
        codigo = str(detalle.get('code') or error.code)
        texto = explicar(codigo, str(detalle.get('message') or error.reason))
        if error.code >= 500:  # el servidor se cayó a medias: puede que el mensaje sí haya salido
            return Resultado(INCIERTO, error=f'{texto}: mira en la consola de Twilio si salió antes de reenviar')
        return Resultado(FALLO, error=texto)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return Resultado(INCIERTO, error=f'sin respuesta ({getattr(error, "reason", error)}): mira en la consola de Twilio si salió antes de reenviar')
    if cuerpo_json.get('status') in ('failed', 'undelivered', 'canceled'):
        return Resultado(FALLO, sid=cuerpo_json.get('sid', ''), error=explicar(str(cuerpo_json.get('error_code') or ''), str(cuerpo_json.get('error_message') or cuerpo_json['status'])))
    try:
        n = int(cuerpo_json.get('num_segments') or 0)
    except (TypeError, ValueError):
        n = 0
    return Resultado(ENVIADO, sid=cuerpo_json.get('sid', ''), segmentos=n)


def explicar(codigo: str, mensaje: str) -> str:
    pista = PISTAS.get(codigo)
    return f'{codigo}: {mensaje}' + (f' → {pista}' if pista else '')


# ------------------------------------------------------------------------------------------------- línea de comandos
def fallar(mensaje: str) -> NoReturn:
    print(mensaje, file=sys.stderr)
    raise SystemExit(2)


def credenciales(base: str) -> Twilio | None:
    sid, token = os.environ.get('TWILIO_ACCOUNT_SID', '').strip(), os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    desde, servicio = os.environ.get('TWILIO_FROM', '').strip(), os.environ.get('TWILIO_MESSAGING_SERVICE_SID', '').strip()
    if not sid or not token or not (desde or servicio):
        return None
    return Twilio(sid, token, desde, servicio, base.rstrip('/'))


def elegir(contactos: list[Contacto], solo: str) -> list[Contacto]:
    """--solo "Ana,Luis": quienes tengan eso en el nombre, o terminen en esos dígitos (sin acentos ni mayúsculas)."""
    pedidos = [p.strip() for p in solo.split(',') if p.strip()]
    if not pedidos:
        return contactos

    def coincide(c: Contacto, pedido: str) -> bool:
        digitos = re.sub(r'\D', '', pedido)
        return _clave(pedido) in _clave(c.nombre) if _clave(pedido) else bool(digitos and c.telefono and c.telefono.endswith(digitos))

    return [c for c in contactos if any(coincide(c, p) for p in pedidos)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('contactos', type=Path, help='el CSV con las columnas nombre y telefono')
    ap.add_argument('--url', default=os.environ.get('VITE_SITE_URL', ''), help='el enlace de la invitación (por defecto, VITE_SITE_URL si la tienes puesta)')
    ap.add_argument('--enviar', action='store_true', help='mandar de verdad; sin esto solo se enseña qué se mandaría')
    ap.add_argument('--mensaje', help='el texto, con {nombre} y {url}; "\\n" es un salto de línea')
    ap.add_argument('--mensaje-archivo', type=Path, help='lo mismo, leído de un archivo de texto')
    ap.add_argument('--solo', default='', help='mandar solo a quienes coincidan, por nombre o por final del teléfono: --solo "Ana,Luis"')
    ap.add_argument('--pais', default='52', help='código de país de los teléfonos que no traen "+" (por defecto 52, México)')
    ap.add_argument('--max', type=int, default=TOPE, dest='tope', help=f'tope de mensajes por corrida (por defecto {TOPE}): frena un CSV equivocado')
    ap.add_argument('--reenviar', action='store_true', help='mandar también a quienes ya se les mandó (o quedaron "inciertos")')
    ap.add_argument('--si', action='store_true', help='no pedir confirmación antes de mandar')
    ap.add_argument('--registro', type=Path, help='dónde anotar lo enviado (por defecto <csv>.envios.csv)')
    ap.add_argument('--pausa', type=float, default=PAUSA, help='segundos entre un mensaje y el siguiente')
    ap.add_argument('--api-base', default=API, help=argparse.SUPPRESS)  # para las pruebas, que no hablan con Twilio
    args = ap.parse_args(argv)

    if not args.contactos.exists():
        fallar(f'No existe {args.contactos}.')
    url = args.url.strip()
    if not re.match(r'https?://[^\s/]+', url):
        fallar('Falta el enlace de la invitación: agrega --url https://tu-dominio.com')
    if args.enviar and re.match(r'https?://(localhost|127\.|0\.0\.0\.0|\[::1\])', url):
        fallar(f'{url} apunta a tu computadora: nadie más podría abrirlo. Usa el dominio de la invitación (el de Vercel).')

    if args.enviar and not re.match(r'https://|http://(127\.0\.0\.1|localhost)[:/]', args.api_base + '/'):
        fallar('--api-base tiene que ser https (o tu computadora, para pruebas): las credenciales de Twilio no viajan sin cifrar.')

    plantilla = MENSAJE
    if args.mensaje_archivo:
        plantilla = args.mensaje_archivo.read_text(encoding='utf-8').strip()
    elif args.mensaje:
        plantilla = args.mensaje.replace('\\n', '\n')
    if '{url}' not in plantilla:
        fallar('El mensaje no lleva {url}: nadie vería la invitación.')

    contactos = leer_contactos(args.contactos, args.pais)
    registro = args.registro or args.contactos.with_suffix('.envios.csv')
    anteriores = leer_registro(registro)
    elegidos = elegir(contactos, args.solo)
    if args.solo and not elegidos:
        fallar(f'Nadie en {args.contactos.name} coincide con --solo "{args.solo}".')

    validos = [c for c in elegidos if c.telefono]
    malos = [c for c in elegidos if not c.telefono]
    ya = [c for c in validos if anteriores.get(c.telefono or '') in (ENVIADO, INCIERTO) and not args.reenviar]
    pendientes = [c for c in validos if c not in ya]

    cuerpos = {c.telefono: armar_mensaje(plantilla, c.nombre, url) for c in pendientes if c.telefono}
    total = sum(segmentos(cuerpo)[1] for cuerpo in cuerpos.values())
    ucs2 = any(segmentos(cuerpo)[0] == 'UCS-2' for cuerpo in cuerpos.values())

    print(('Mandando de verdad.' if args.enviar else 'Ensayo: no se manda nada. Para mandar de verdad agrega --enviar.') + '\n')
    for c in pendientes:
        print(f'  {c.nombre[:30]:<30} {bonito(c.telefono or ""):<18} {segmentos(cuerpos[c.telefono or ""])[1]} SMS')
    for c in ya:
        estado = anteriores[c.telefono or '']
        print(f'  {c.nombre[:30]:<30} {bonito(c.telefono or ""):<18} se salta: ya {"se le mandó" if estado == ENVIADO else "quedó incierto (mira la consola de Twilio)"}')
    for c in malos:
        print(f'  fila {c.fila}: {c.nombre or "(sin nombre)"} · {c.problema} → se salta')
    if pendientes:
        ejemplo = pendientes[0]
        print(f'\nAsí le llega a {ejemplo.nombre}:\n')
        print('    ' + cuerpos[ejemplo.telefono or ''].replace('\n', '\n    '))
    print(f'\n{len(pendientes)} por mandar · {total} SMS en total · {len(ya)} ya enviados · {len(malos)} con datos malos')
    if ucs2:
        print('Los acentos y símbolos pasan el mensaje a UCS-2: caben 70 caracteres por SMS en vez de 160, y cada SMS se cobra aparte.')

    if len(pendientes) > args.tope:
        fallar(f'\nSon {len(pendientes)} mensajes y el tope de seguridad es {args.tope}. Si es lo que quieres, agrega --max {len(pendientes)}.')
    if not args.enviar:
        return 1 if malos else 0
    if not pendientes:
        print('\nNo hay nadie a quien mandarle.')
        return 1 if malos else 0

    cfg = credenciales(args.api_base)
    if not cfg:
        fallar(
            '\nFaltan credenciales de Twilio. Pon en el entorno TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN y una de estas: '
            'TWILIO_FROM (tu número de Twilio) o TWILIO_MESSAGING_SERVICE_SID. Están en la consola de Twilio.'
        )
    if sys.stdin.isatty() and not args.si and input(f'\n¿Mandar {len(pendientes)} mensajes ({total} SMS)? [s/N] ').strip().lower() not in ('s', 'si', 'sí'):
        print('No se mandó nada.')
        return 0

    enviados = fallidos = inciertos = 0
    print()
    try:
        for i, c in enumerate(pendientes):
            if i and args.pausa:
                time.sleep(args.pausa)
            r = mandar(cfg, c.telefono or '', cuerpos[c.telefono or ''])
            anotar(registro, c, r.estado, r.sid, r.error)
            if r.estado == ENVIADO:
                enviados += 1
                print(f'  ✓ {c.nombre[:30]:<30} {bonito(c.telefono or "")}  {r.sid}', flush=True)
            else:
                fallidos += r.estado == FALLO
                inciertos += r.estado == INCIERTO
                print(f'  ✗ {c.nombre[:30]:<30} {bonito(c.telefono or "")}  {r.error}', flush=True)
    except KeyboardInterrupt:
        print('\nInterrumpido. Lo que ya salió quedó anotado: si lo corres otra vez, sigue donde se quedó.')
        return 130

    print(f'\n{enviados} enviados · {fallidos} con error · {inciertos} inciertos · registro en {registro}')
    if enviados:
        print('Twilio los recibió; que lleguen depende del operador. Los estados de entrega salen en la consola de Twilio → Monitor → Logs → Messaging.')
    return 1 if fallidos or inciertos or malos else 0


if __name__ == '__main__':
    sys.exit(main())
