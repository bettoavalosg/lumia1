"""La API de Supabase (PostgREST) sobre un Postgres de verdad, en tu máquina. Sin Docker, sin cuenta, sin internet.

    python scripts/servidor_local.py                 # levanta un Postgres temporal y sirve la API en :54321
    python scripts/servidor_local.py --puerto 8000
    DATABASE_URL=postgresql://... python scripts/servidor_local.py --pin 246810    # sobre una base tuya

Después, en otra terminal:

    VITE_SUPABASE_URL=http://127.0.0.1:54321 VITE_SUPABASE_ANON_KEY=local npm run dev

Es lo mismo que hace Supabase con las funciones de `public`: `POST /rest/v1/rpc/<función>` con el JSON de los
argumentos, ejecutada con el rol `anon`. No hay Realtime: la app consulta cada pocos segundos, que es justo el
plan B que usa cuando el canal en vivo no está disponible. Sirve para ensayar y para las pruebas.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import threading
from collections.abc import Iterator

import psycopg

from motor_pg import BaseDeDatos, ErrorApi

CLAVE_ANON = 'local-anon'
CLAVE_SERVICIO = 'local-service'

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'apikey, authorization, content-type, prefer, x-client-info',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Max-Age': '600',
}


class _Manejador(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, db: BaseDeDatos, **kwargs):
        self.db = db
        super().__init__(*args, **kwargs)

    def log_message(self, *args: object) -> None:
        pass

    def _responder(self, estado: int, cuerpo: object) -> None:
        datos = json.dumps(cuerpo, default=str, ensure_ascii=False).encode()
        self.send_response(estado)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(datos)))
        self.end_headers()
        try:
            self.wfile.write(datos)
        except (BrokenPipeError, ConnectionResetError):
            pass  # el navegador cortó la consulta (cerró la pestaña o perdió la red): no hay a quién contestarle

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith('/health'):
            self._responder(200, {'ok': True})
        else:
            self._responder(404, {'message': 'No existe. Esta API solo sirve /rest/v1/rpc/<función>.'})

    def do_POST(self) -> None:  # noqa: N802
        prefijo = '/rest/v1/rpc/'
        if not self.path.startswith(prefijo):
            self._responder(404, {'message': 'No existe. Esta API solo sirve /rest/v1/rpc/<función>.'})
            return
        clave = self.headers.get('apikey', '')
        if clave not in (CLAVE_ANON, CLAVE_SERVICIO):
            self._responder(401, {'message': 'Invalid API key', 'hint': 'Usa la anon key que imprime servidor_local.py'})
            return
        funcion = self.path[len(prefijo):].split('?')[0]
        try:
            largo = int(self.headers.get('Content-Length') or 0)
            args = json.loads(self.rfile.read(largo) or b'{}')
            if not isinstance(args, dict):
                raise ValueError('el cuerpo debe ser un objeto JSON')
        except ValueError as e:
            self._responder(400, {'code': 'PGRST102', 'message': f'Cuerpo inválido: {e}'})
            return
        rol = 'service_role' if clave == CLAVE_SERVICIO else 'anon'
        try:
            self._responder(200, self.db.llamar(funcion, rol=rol, **args))
        except ErrorApi as e:
            if e.codigo in ('funcion_desconocida', 'argumento_desconocido'):
                self._responder(404, {'code': 'PGRST202', 'message': e.mensaje, 'details': None, 'hint': None})
            else:
                self._responder(400, {'code': 'P0001', 'message': e.mensaje, 'details': None, 'hint': e.codigo})
        except psycopg.errors.InsufficientPrivilege as e:
            self._responder(403, {'code': '42501', 'message': e.diag.message_primary or 'permission denied', 'details': None, 'hint': None})
        except psycopg.Error as e:
            self._responder(400, {'code': e.sqlstate or 'XX000', 'message': e.diag.message_primary or str(e), 'details': None, 'hint': None})


class _Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # veinte teléfonos votando a la vez no caben en la cola de 5 que trae por defecto


@contextlib.contextmanager
def servir_api(db: BaseDeDatos, puerto: int = 0) -> Iterator[str]:
    """Sirve la API de `db` en 127.0.0.1 (puerto libre si es 0). Devuelve su URL."""
    servidor = _Servidor(('127.0.0.1', puerto), functools.partial(_Manejador, db=db))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f'http://127.0.0.1:{servidor.server_address[1]}'
    finally:
        servidor.shutdown()
        servidor.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--puerto', type=int, default=54321)
    parser.add_argument('--pin', default=None, help='PIN del admin (mínimo 6 caracteres). Con base temporal, por defecto 000000.')
    args = parser.parse_args()

    externa = bool(BaseDeDatos().url)
    with BaseDeDatos(pin=args.pin or (None if externa else '000000')) as db, servir_api(db, args.puerto) as url:
        print(f'API lista en {url}')
        print(f'  anon key:    {CLAVE_ANON}')
        print(f'  service key: {CLAVE_SERVICIO}   (solo para probar push_pending; no la uses en el front)')
        print(f'  PIN de admin: {args.pin or ("(el de tu base)" if externa else "000000")}')
        print()
        print(f'  VITE_SUPABASE_URL={url} VITE_SUPABASE_ANON_KEY={CLAVE_ANON} npm run dev')
        print('Ctrl+C para salir.')
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()


if __name__ == '__main__':
    main()
