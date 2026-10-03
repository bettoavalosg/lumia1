"""Pruebas de scripts/enviar_sms.py contra un Twilio de mentiras en tu computadora: no mandan ningún SMS ni piden cuenta.

    python scripts/probar_sms.py
    python scripts/probar_sms.py -k telefonos     # solo las pruebas cuyo nombre contiene "telefonos"

Revisan cómo se escriben los teléfonos, el conteo de SMS, que el ensayo no mande nada, el formato exacto de lo que recibe Twilio
(ruta, autenticación y campos), que no se repita un envío, que un error no frene a los demás y que los números nunca terminen en el repo.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import http.server
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path

import enviar_sms
from enviar_sms import MENSAJE, armar_mensaje, normalizar_telefono, segmentos

RAIZ = Path(__file__).resolve().parent.parent
URL = 'https://mariela29.example.com'
SID = 'AC' + 'a' * 32
TOKEN = 'token-secreto-de-prueba'
DESDE = '+15005550006'
CRED = {'TWILIO_ACCOUNT_SID': SID, 'TWILIO_AUTH_TOKEN': TOKEN, 'TWILIO_FROM': DESDE}
CONTACTOS = 'nombre,telefono\nAna Torres,55 1234 5678\nLuis,+52 1 33 9876 5432\n'

PRUEBAS: list[Callable[[], None]] = []


def prueba(fn: Callable[[], None]) -> Callable[[], None]:
    PRUEBAS.append(fn)
    return fn


# ------------------------------------------------------------------------------------------------- un Twilio de mentiras
class TwilioFalso:
    """Un servidor local que contesta como la API de mensajes de Twilio y apunta lo que le llega. `reglas[número]` cambia su respuesta:
    (estado, json) o 'cortar' (cuelga sin contestar, como una red que se cae a medias)."""

    def __init__(self) -> None:
        self.peticiones: list[dict] = []
        self.reglas: dict[str, tuple[int, dict] | str] = {}
        falso = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                crudo = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
                datos = {k: v[0] for k, v in urllib.parse.parse_qs(crudo).items()}
                falso.peticiones.append({'ruta': self.path, 'auth': self.headers.get('Authorization'), 'datos': datos})
                regla = falso.reglas.get(datos.get('To', ''))
                if regla == 'cortar':
                    return  # sin responder: el cliente ve la conexión cerrada
                estado, cuerpo = regla or (201, {'sid': 'SM' + secrets.token_hex(16), 'status': 'queued', 'num_segments': '2', 'error_code': None})
                bytes_ = json.dumps(cuerpo).encode()
                self.send_response(estado)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(bytes_)))
                self.end_headers()
                self.wfile.write(bytes_)

            def log_message(self, *args: object) -> None:
                pass

        self.servidor = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Manejador)
        self.url = f'http://127.0.0.1:{self.servidor.server_address[1]}'

    def __enter__(self) -> TwilioFalso:
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *args: object) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()


@contextlib.contextmanager
def entorno(**extra: str) -> Iterator[None]:
    """Un entorno limpio de credenciales de verdad, y sin proxy para hablar con el servidor local."""
    previo = dict(os.environ)
    for k in list(os.environ):
        if k.startswith('TWILIO_') or k == 'VITE_SITE_URL':
            del os.environ[k]
    os.environ.update({'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1', **extra})
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previo)


def correr(*argv: object, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Corre el script como lo haría la terminal (en el mismo proceso) y devuelve (código de salida, todo lo que imprimió)."""
    salida = io.StringIO()
    with entorno(**(env or {})), contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
        try:
            codigo = enviar_sms.main([str(a) for a in argv])
        except SystemExit as fin:
            codigo = fin.code if isinstance(fin.code, int) else 1
    return codigo, salida.getvalue()


def enviar(tw: TwilioFalso, ruta: Path, *extra: object, env: dict[str, str] | None = None) -> tuple[int, str]:
    return correr(ruta, '--url', URL, '--enviar', '--si', '--pausa', 0, '--api-base', tw.url, *extra, env=CRED if env is None else env)


def registro(carpeta: Path, nombre: str = 'contactos.envios.csv') -> list[dict[str, str]]:
    with (carpeta / nombre).open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def archivo(carpeta: str, texto: str, nombre: str = 'contactos.csv') -> Path:
    ruta = Path(carpeta) / nombre
    ruta.write_bytes(texto.encode('utf-8'))
    return ruta


# ------------------------------------------------------------------------------------------------- pruebas
@prueba
def los_telefonos_se_normalizan() -> None:
    # Los mismos casos que usa la prueba de la interfaz (la tarjeta del admin tiene su propia versión en TypeScript).
    casos = json.loads((RAIZ / 'scripts' / 'casos_telefonos.json').read_text(encoding='utf-8'))
    for crudo, esperado in casos['validos'].items():
        assert normalizar_telefono(crudo) == esperado, (crudo, normalizar_telefono(crudo))
    for malo in ['', '   ', *casos['invalidos']]:
        assert normalizar_telefono(malo) is None, malo
    assert normalizar_telefono('415 555 0100', pais='1') == '+14155550100'
    assert normalizar_telefono('1 415 555 0100', pais='1') == '+14155550100'
    assert enviar_sms.bonito('+525512345678') == '+52 55 1234 5678'
    assert enviar_sms.bonito('+522221234567') == '+52 222 123 4567'
    assert enviar_sms.bonito('+14155550100') == '+14155550100'


@prueba
def el_script_y_la_tarjeta_del_admin_mandan_el_mismo_mensaje() -> None:
    # La tarjeta «Mandar la invitación» (TypeScript) y este script arman el mismo texto: si uno cambia, la prueba obliga a cambiar el otro.
    fuente = (RAIZ / 'src' / 'lib' / 'invitacionSms.ts').read_text(encoding='utf-8')
    primera, segunda = MENSAJE.split('\n')
    assert primera in fuente, 'la primera línea del mensaje ya no coincide con src/lib/invitacionSms.ts'
    assert segunda == '{nombre}, tu invitación: {url}', 'cambió el saludo del script: revisa también la tarjeta'
    assert "${quien ? `${quien}, tu invitación` : 'Tu invitación'}: ${enlace}`" in fuente, 'el saludo y el enlace ya no coinciden con los del script'


@prueba
def los_sms_se_cuentan_como_los_cobra_el_operador() -> None:
    assert segmentos('a' * 160) == ('GSM-7', 1)
    assert segmentos('a' * 161) == ('GSM-7', 2)
    assert segmentos('a' * 306) == ('GSM-7', 2)  # 153 × 2
    assert segmentos('a' * 307) == ('GSM-7', 3)
    assert segmentos('{' * 80) == ('GSM-7', 1)  # las llaves ocupan dos septetos
    assert segmentos('{' * 81) == ('GSM-7', 2)
    assert segmentos('é' * 160) == ('GSM-7', 1)  # la é y la ñ sí están en el alfabeto GSM…
    assert segmentos('ñ' * 160) == ('GSM-7', 1)
    assert segmentos('á' * 70) == ('UCS-2', 1)  # …la á, la í, la ó y la ú no
    assert segmentos('á' * 71) == ('UCS-2', 2)
    assert segmentos('á' * 134) == ('UCS-2', 2)  # 67 × 2
    assert segmentos('á' * 135) == ('UCS-2', 3)
    assert segmentos('🎂' * 35) == ('UCS-2', 1)  # un emoji son dos unidades
    assert segmentos('🎂' * 36) == ('UCS-2', 2)
    # El mensaje de siempre, con un nombre y un enlace corrientes, cabe en dos SMS.
    cuerpo = armar_mensaje(MENSAJE, 'Ana', 'https://mariela29.vercel.app')
    assert segmentos(cuerpo) == ('UCS-2', 2), (len(cuerpo), segmentos(cuerpo))
    assert 'Mariela' in cuerpo and cuerpo.endswith('https://mariela29.vercel.app'), 'quien lo recibe tiene que saber de quién es y ver el enlace'


@prueba
def el_ensayo_no_manda_nada() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, CONTACTOS)
        codigo, salida = correr(ruta, '--url', URL, '--api-base', tw.url, env=CRED)
        assert codigo == 0, salida
        assert not tw.peticiones, 'el ensayo no debe tocar Twilio'
        assert 'no se manda nada' in salida and 'Ana Torres' in salida and 'Luis' in salida
        assert '+52 55 1234 5678' in salida and '+52 33 9876 5432' in salida
        assert f'Ana Torres, tu invitación: {URL}' in salida, 'tiene que enseñar cómo le llega el mensaje'
        assert '2 por mandar' in salida
        assert not (Path(d) / 'contactos.envios.csv').exists(), 'un ensayo no deja registro'
        assert TOKEN not in salida
        # Sin credenciales también se puede ensayar: solo hacen falta para mandar.
        codigo, salida = correr(ruta, '--url', URL, env={})
        assert codigo == 0, salida


@prueba
def manda_con_el_formato_de_twilio() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, CONTACTOS)
        codigo, salida = enviar(tw, ruta)
        assert codigo == 0, salida
        assert len(tw.peticiones) == 2, tw.peticiones
        p = tw.peticiones[0]
        assert p['ruta'] == f'/2010-04-01/Accounts/{SID}/Messages.json'
        assert p['auth'] == 'Basic ' + base64.b64encode(f'{SID}:{TOKEN}'.encode()).decode()
        assert p['datos'] == {'To': '+525512345678', 'From': DESDE, 'Body': armar_mensaje(MENSAJE, 'Ana Torres', URL)}
        assert tw.peticiones[1]['datos']['To'] == '+523398765432', 'el +52 1 de los celulares se quita'
        assert tw.peticiones[1]['datos']['Body'].startswith('Mariela cumple 29') and 'Luis, tu invitación' in tw.peticiones[1]['datos']['Body']
        filas = registro(Path(d))
        assert [(f['telefono'], f['nombre'], f['estado']) for f in filas] == [('+525512345678', 'Ana Torres', 'enviado'), ('+523398765432', 'Luis', 'enviado')]
        assert all(f['sid'].startswith('SM') for f in filas)
        assert '2 enviados · 0 con error · 0 inciertos' in salida
        assert TOKEN not in salida, 'el token no se imprime nunca'


@prueba
def con_un_servicio_de_mensajes_manda_el_servicio_y_no_el_numero() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        servicio = 'MG' + 'b' * 32
        codigo, salida = enviar(tw, archivo(d, CONTACTOS), env={'TWILIO_ACCOUNT_SID': SID, 'TWILIO_AUTH_TOKEN': TOKEN, 'TWILIO_MESSAGING_SERVICE_SID': servicio})
        assert codigo == 0, salida
        assert [p['datos'].get('MessagingServiceSid') for p in tw.peticiones] == [servicio, servicio]
        assert all('From' not in p['datos'] for p in tw.peticiones)


@prueba
def no_vuelve_a_mandar_a_quien_ya_se_le_mando() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, CONTACTOS)
        assert enviar(tw, ruta)[0] == 0
        assert len(tw.peticiones) == 2
        codigo, salida = enviar(tw, ruta)
        assert codigo == 0, salida
        assert len(tw.peticiones) == 2, 'la segunda corrida no debe mandar nada'
        assert salida.count('se salta: ya se le mandó') == 2 and 'No hay nadie a quien mandarle' in salida
        # Un contacto nuevo sí sale; los de antes, no.
        archivo(d, CONTACTOS + 'Marisol,55 8888 8888\n')
        assert enviar(tw, ruta)[0] == 0
        assert [p['datos']['To'] for p in tw.peticiones[2:]] == ['+525588888888']
        # Y con --reenviar, todos otra vez.
        assert enviar(tw, ruta, '--reenviar')[0] == 0
        assert len(tw.peticiones) == 2 + 1 + 3


@prueba
def un_error_de_twilio_se_cuenta_y_no_frena_a_los_demas() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\nAna,55 1111 1111\nBeto,55 0000 0400\nCarla,55 3333 3333\n')
        tw.reglas['+525500000400'] = (400, {'code': 21211, 'message': "The 'To' number +525500000400 is not a valid phone number.", 'status': 400})
        codigo, salida = enviar(tw, ruta)
        assert codigo == 1, salida
        assert len(tw.peticiones) == 3, 'un error no debe frenar a los demás'
        assert '2 enviados · 1 con error · 0 inciertos' in salida
        assert '21211' in salida and 'ese número no es válido' in salida, salida
        assert {f['nombre']: f['estado'] for f in registro(Path(d))} == {'Ana': 'enviado', 'Beto': 'fallo', 'Carla': 'enviado'}
        # Al repetir solo se reintenta al que falló (que ahora sí sale).
        del tw.reglas['+525500000400']
        codigo, salida = enviar(tw, ruta)
        assert codigo == 0, salida
        assert [p['datos']['To'] for p in tw.peticiones[3:]] == ['+525500000400']
        assert registro(Path(d))[-1]['estado'] == 'enviado'


@prueba
def sin_respuesta_queda_incierto_y_no_se_reintenta_solo() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\nAna,55 1111 1111\nBeto,55 2222 2222\nCarla,55 3333 3333\n')
        tw.reglas['+525511111111'] = 'cortar'  # la red se cae sin que Twilio conteste
        tw.reglas['+525522222222'] = (503, {'message': 'Service Unavailable'})  # un error del servidor tampoco dice si salió
        codigo, salida = enviar(tw, ruta)
        assert codigo == 1, salida
        assert '1 enviados · 0 con error · 2 inciertos' in salida, salida
        assert 'consola de Twilio' in salida
        assert {f['nombre']: f['estado'] for f in registro(Path(d))} == {'Ana': 'incierto', 'Beto': 'incierto', 'Carla': 'enviado'}
        # Reenviar a ciegas podría mandar el mensaje dos veces: hay que pedirlo.
        antes = len(tw.peticiones)
        tw.reglas.clear()
        codigo, salida = enviar(tw, ruta)
        assert len(tw.peticiones) == antes and 'quedó incierto' in salida, salida
        assert enviar(tw, ruta, '--reenviar')[0] == 0
        assert len(tw.peticiones) == antes + 3


@prueba
def lo_que_ya_salio_queda_anotado_aunque_se_interrumpa() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\nAna,55 1111 1111\nBeto,55 2222 2222\nCarla,55 3333 3333\n')
        original = enviar_sms.time.sleep

        def interrumpir(_: float) -> None:
            raise KeyboardInterrupt

        enviar_sms.time.sleep = interrumpir
        try:
            codigo, salida = correr(ruta, '--url', URL, '--enviar', '--si', '--pausa', 1, '--api-base', tw.url, env=CRED)
        finally:
            enviar_sms.time.sleep = original
        assert codigo == 130, salida
        assert [f['nombre'] for f in registro(Path(d))] == ['Ana'], 'Ana salió antes de la interrupción'
        assert enviar(tw, ruta)[0] == 0
        assert [p['datos']['To'] for p in tw.peticiones] == ['+525511111111', '+525522222222', '+525533333333'], 'al repetir sigue donde se quedó'


@prueba
def sin_lo_necesario_no_manda_nada() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, CONTACTOS)
        casos = [
            (['--enviar', '--si', '--url', URL, '--api-base', tw.url], {}, 'TWILIO_ACCOUNT_SID'),  # sin credenciales
            (['--enviar', '--si', '--url', URL, '--api-base', tw.url], {'TWILIO_ACCOUNT_SID': SID, 'TWILIO_AUTH_TOKEN': TOKEN}, 'TWILIO_FROM'),  # sin remitente
            (['--enviar', '--si', '--url', 'http://localhost:5173', '--api-base', tw.url], CRED, 'apunta a tu computadora'),
            (['--enviar', '--si', '--api-base', tw.url], CRED, 'Falta el enlace'),
            (['--enviar', '--si', '--url', URL, '--mensaje', 'Hola {nombre}', '--api-base', tw.url], CRED, 'no lleva {url}'),
            (['--enviar', '--si', '--url', URL, '--api-base', 'http://ejemplo.com'], CRED, 'sin cifrar'),  # las credenciales no viajan en claro
        ]
        for argv, env, texto in casos:
            codigo, salida = correr(ruta, *argv, env=env)
            assert codigo == 2 and texto in salida, (argv, codigo, salida)
        codigo, salida = correr(Path(d) / 'no-existe.csv', '--url', URL, env=CRED)
        assert codigo == 2 and 'No existe' in salida, salida
        assert not tw.peticiones, 'ninguno de esos casos debió llegar a Twilio'
        assert not (Path(d) / 'contactos.envios.csv').exists()


@prueba
def el_tope_frena_un_csv_equivocado() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\n' + ''.join(f'Invitado {i},55 1000 00{i:02d}\n' for i in range(5)))
        codigo, salida = enviar(tw, ruta, '--max', 3)
        assert codigo == 2 and 'tope de seguridad es 3' in salida and '--max 5' in salida, salida
        assert not tw.peticiones
        assert correr(ruta, '--url', URL, '--max', 3, env=CRED)[0] == 2, 'ni siquiera el ensayo se queda callado'
        codigo, salida = enviar(tw, ruta, '--max', 5)
        assert codigo == 0 and len(tw.peticiones) == 5, salida


@prueba
def los_datos_malos_se_avisan_y_se_saltan() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\nAna,55 1234 5678\nSin número,\nMal número,abc\nAna otra vez,044 55 1234 5678\n,55 9999 9999\n\nBeto,55 2222 2222\n')
        codigo, salida = enviar(tw, ruta)
        assert codigo == 1, salida
        assert [p['datos']['To'] for p in tw.peticiones] == ['+525512345678', '+525522222222']
        for esperado in ('fila 3: Sin número · falta el teléfono', 'fila 4: Mal número · el teléfono «abc» no es válido',
                         'fila 5: Ana otra vez · repetido (es el mismo número de Ana)', 'fila 6: (sin nombre) · falta el nombre'):
            assert esperado in salida, (esperado, salida)
        assert '2 enviados' in salida


@prueba
def solo_manda_a_quien_se_pide() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        ruta = archivo(d, 'nombre,telefono\nAna Torres,55 1111 1111\nLuis Cárdenas,55 2222 2222\nMarisol,55 3333 8888\n')
        assert enviar(tw, ruta, '--solo', 'luis')[0] == 0  # sin mayúsculas
        assert [p['datos']['To'] for p in tw.peticiones] == ['+525522222222']
        assert enviar(tw, ruta, '--solo', 'ANA, 8888')[0] == 0  # por nombre y por el final del teléfono
        assert [p['datos']['To'] for p in tw.peticiones[1:]] == ['+525511111111', '+525533338888']
        codigo, salida = enviar(tw, ruta, '--solo', 'zzz')
        assert codigo == 2 and 'Nadie' in salida, salida
        assert len(tw.peticiones) == 3


@prueba
def acepta_el_csv_como_lo_exporta_excel() -> None:
    with TwilioFalso() as tw, tempfile.TemporaryDirectory() as d:
        # BOM, punto y coma, saltos de línea de Windows y encabezados con mayúscula y acento.
        ruta = archivo(d, '﻿Nombre;Teléfono\r\nAna Sofía;55 1234 5678\r\nLuis;33-9876-5432\r\n')
        codigo, salida = enviar(tw, ruta)
        assert codigo == 0, salida
        assert [p['datos']['To'] for p in tw.peticiones] == ['+525512345678', '+523398765432']
        assert 'Ana Sofía, tu invitación' in tw.peticiones[0]['datos']['Body']
        # Un encabezado en inglés también vale; y sin encabezado, el script lo dice en vez de adivinar.
        assert correr(archivo(d, 'name\tphone\nAna\t5512345678\n', 'otro.csv'), '--url', URL)[0] == 0
        codigo, salida = correr(archivo(d, 'Ana,5512345678\n', 'sin-encabezado.csv'), '--url', URL)
        assert codigo == 2 and 'No encontré las columnas' in salida, salida


@prueba
def los_numeros_no_se_suben_al_repo() -> None:
    def ignorado(ruta: str) -> bool:
        return subprocess.run(['git', 'check-ignore', '-q', ruta], cwd=RAIZ).returncode == 0

    for nombre in ('contactos.csv', 'contactos-fiesta.csv', 'invitados.csv', 'contactos.envios.csv', 'scripts/contactos.csv', 'cualquier.envios.csv'):
        assert ignorado(nombre), f'{nombre} tiene números de teléfono: tiene que estar en .gitignore'
    assert not ignorado('scripts/enviar_sms.py') and not ignorado('scripts/probar_sms.py')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-k', dest='filtro', default='', help='solo las pruebas cuyo nombre contiene este texto')
    parser.add_argument('-x', dest='parar', action='store_true', help='detenerse en la primera que falle')
    args = parser.parse_args()
    elegidas = [fn for fn in PRUEBAS if args.filtro in fn.__name__]
    fallas = 0
    print(f'· {len(elegidas)} pruebas')
    for fn in elegidas:
        inicio = time.perf_counter()
        try:
            fn()
        except Exception as error:  # noqa: BLE001
            fallas += 1
            print(f'  ✗ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
            detalle = traceback.format_exc(limit=-4) if not isinstance(error, AssertionError) or not str(error) else f'{error}\n' + ''.join(traceback.format_tb(error.__traceback__, limit=-2))
            print('      ' + detalle.strip().replace('\n', '\n      '))
            if args.parar:
                break
        else:
            print(f'  ✓ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
    print(f'{len(elegidas) - fallas} de {len(elegidas)} pasaron.')
    sys.exit(1 if fallas else 0)


if __name__ == '__main__':
    main()
