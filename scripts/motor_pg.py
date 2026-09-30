"""Un Postgres temporal con las migraciones puestas, y un cliente que llama a la API como lo hace PostgREST.

Sirve a las pruebas del motor (probar_motor.py) y al servidor local (servidor_local.py).

Postgres: usa los binarios de PG_BIN, o los de /usr/lib/postgresql/<versión>/bin, o los que estén en el PATH.
Si ya tienes una base, pasa su cadena de conexión en DATABASE_URL y no se levanta nada (las migraciones
se aplican encima; úsala solo con una base de pruebas).
"""

from __future__ import annotations

import contextlib
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

RAIZ = Path(__file__).resolve().parent.parent
MIGRACIONES = sorted(Path(os.environ.get('MIGRACIONES_DIR') or RAIZ / 'supabase' / 'migrations').glob('*.sql'))

# Lo que Supabase ya trae y las migraciones dan por hecho.
PREPARAR = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant usage on schema public to anon, authenticated, service_role;
"""

REINICIAR = """
truncate app.players, app.games, app.push_queue, app.settings, app.admin_sessions restart identity cascade;
delete from app.event;
insert into app.event (id) values (1);
update app.admin set failed_attempts = 0, locked_until = null;
"""


class ErrorApi(Exception):
    """Un error de juego: `codigo` es el hint de la función y `mensaje` el texto para la persona."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f'{codigo}: {mensaje}')
        self.codigo = codigo
        self.mensaje = mensaje


def _binarios() -> Path:
    if os.environ.get('PG_BIN'):
        return Path(os.environ['PG_BIN'])
    versiones = sorted(Path('/usr/lib/postgresql').glob('*/bin'), key=lambda p: int(p.parent.name), reverse=True)
    for ruta in versiones:
        if (ruta / 'postgres').exists():
            return ruta
    encontrado = shutil.which('pg_ctl')
    if encontrado:
        return Path(encontrado).parent
    sys.exit('No encontré Postgres. Instálalo (apt install postgresql) o define PG_BIN / DATABASE_URL.')


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class BaseDeDatos:
    """Una base lista para usar. Úsala con `with`."""

    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get('DATABASE_URL')
        self._temporal: Path | None = None
        self._bin: Path | None = None
        self._prefijo: list[str] = []
        self._admin: psycopg.Connection | None = None
        self._firmas: dict[str, list[tuple[str, str]]] = {}
        self._pin_hash = ''

    # -- ciclo de vida ------------------------------------------------------------------------------
    def __enter__(self) -> BaseDeDatos:
        if not self.url:
            self._levantar()
        self.psql(PREPARAR)
        for migracion in MIGRACIONES:
            self.psql(migracion.read_text(), f'{migracion.name}')
        self._admin = psycopg.connect(self.url, autocommit=True)
        self._admin.execute("select app.set_admin_pin('123456')")
        self._pin_hash = self._admin.execute('select pin_hash from app.admin').fetchone()[0]
        return self

    def __exit__(self, *_: object) -> None:
        if self._admin:
            self._admin.close()
        if self._temporal:
            with contextlib.suppress(Exception):
                self._ejecutar([str(self._bin / 'pg_ctl'), '-D', str(self._temporal / 'datos'), '-m', 'immediate', '-w', 'stop'])
            shutil.rmtree(self._temporal, ignore_errors=True)

    def _ejecutar(self, comando: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(self._prefijo + comando, capture_output=True, text=True, **kw)

    def _levantar(self) -> None:
        self._bin = _binarios()
        self._temporal = Path(tempfile.mkdtemp(prefix='mariela-pg-'))
        if os.geteuid() == 0:
            # Postgres se niega a correr como root: usa el usuario del sistema `postgres`.
            usuario = pwd.getpwnam('postgres')
            os.chown(self._temporal, usuario.pw_uid, usuario.pw_gid)
            self._prefijo = ['runuser', '-u', 'postgres', '--']
        datos = self._temporal / 'datos'
        r = self._ejecutar([str(self._bin / 'initdb'), '-D', str(datos), '-U', 'postgres', '--auth=trust', '-E', 'UTF8', '--no-locale'])
        if r.returncode:
            sys.exit(f'initdb falló:\n{r.stdout}\n{r.stderr}')
        puerto = _puerto_libre()
        r = self._ejecutar([
            str(self._bin / 'pg_ctl'), '-D', str(datos), '-l', str(self._temporal / 'log.txt'), '-w',
            '-o', f"-p {puerto} -k {self._temporal} -c listen_addresses='' -c fsync=off -c synchronous_commit=off -c full_page_writes=off",
            'start',
        ])
        if r.returncode:
            sys.exit(f'pg_ctl start falló:\n{r.stdout}\n{r.stderr}\n{(self._temporal / "log.txt").read_text()}')
        self.url = f'host={self._temporal} port={puerto} dbname=postgres user=postgres'

    # -- SQL directo (como el dueño de la base) -----------------------------------------------------
    def psql(self, sql: str, nombre: str = 'sql') -> None:
        psql = str(self._bin / 'psql') if self._bin and (self._bin / 'psql').exists() else 'psql'
        comando = [psql, '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-d', self.url, '-f', '-']
        r = subprocess.run(comando, input=sql, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'{nombre} falló:\n{r.stderr}')

    def sql(self, consulta: str, *params):
        assert self._admin is not None
        cur = self._admin.execute(consulta, params or None)
        return cur.fetchall() if cur.description else []

    def filas(self, consulta: str, *params) -> list[dict]:
        assert self._admin is not None
        cur = self._admin.execute(consulta, params or None)
        nombres = [c.name for c in cur.description]
        return [dict(zip(nombres, fila)) for fila in cur.fetchall()]

    def fila(self, consulta: str, *params) -> dict | None:
        filas = self.filas(consulta, *params)
        return filas[0] if filas else None

    def valor(self, consulta: str, *params):
        filas = self.sql(consulta, *params)
        return filas[0][0] if filas else None

    def reiniciar(self) -> None:
        """Deja la base como recién migrada, con el PIN de pruebas (123456)."""
        assert self._admin is not None
        self._admin.execute(REINICIAR)
        self._admin.execute('update app.admin set pin_hash = %s', (self._pin_hash,))

    def adelantar(self, segundos: float) -> None:
        """Mueve el reloj del servidor hacia adelante (como el ensayo, pero sin pasar por el admin)."""
        self.sql("update app.event set clock_offset = clock_offset + make_interval(secs => %s)", segundos)

    def ahora(self):
        return self.valor('select app.now()')

    # -- la API, como la ve un cliente ---------------------------------------------------------------
    def conexion(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=False)

    def _firma(self, conn: psycopg.Connection, funcion: str) -> list[tuple[str, str]]:
        if funcion not in self._firmas:
            filas = conn.execute(
                """select unnest(p.proargnames), unnest(string_to_array(p.proargtypes::text, ' '))::oid::regtype::text
                     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'public' and p.proname = %s""",
                (funcion,),
            ).fetchall()
            conn.rollback()
            self._firmas[funcion] = [(nombre, tipo) for nombre, tipo in filas]
        return self._firmas[funcion]

    def llamar(self, funcion: str, rol: str = 'anon', conn: psycopg.Connection | None = None, **args):
        """Ejecuta `public.<funcion>` con el rol de la API. Devuelve el JSON o lanza ErrorApi."""
        propia = conn is None
        conn = conn or self.conexion()
        try:
            firma = dict(self._firma(conn, funcion))
            if not firma and args:
                raise ErrorApi('funcion_desconocida', f'No existe public.{funcion}')
            partes, valores = [], {}
            for nombre, valor in args.items():
                if nombre not in firma:
                    raise ErrorApi('argumento_desconocido', f'{funcion} no tiene el argumento {nombre}')
                partes.append(f'{nombre} := %({nombre})s::{firma[nombre]}')
                valores[nombre] = Jsonb(valor) if isinstance(valor, (dict, list)) and firma[nombre].startswith('json') else valor
            try:
                with conn.transaction():
                    conn.execute(f'set local role {rol}')
                    fila = conn.execute(f'select public.{funcion}({", ".join(partes)})', valores).fetchone()
            except psycopg.errors.RaiseException as e:
                raise ErrorApi(e.diag.message_hint or 'error', e.diag.message_primary or str(e)) from None
            return fila[0]
        finally:
            if propia:
                conn.close()


@contextlib.contextmanager
def base_de_datos() -> Iterator[BaseDeDatos]:
    with BaseDeDatos() as db:
        yield db
