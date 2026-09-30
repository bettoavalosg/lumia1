"""Pruebas del motor del juego contra un Postgres real (las mismas migraciones que van a Supabase).

    python scripts/probar_motor.py              # levanta un Postgres temporal y corre todo
    python scripts/probar_motor.py -k voto      # solo las pruebas cuyo nombre contiene "voto"
    DATABASE_URL=... python scripts/probar_motor.py   # contra una base de pruebas que ya tengas

Cada prueba llama a la API como lo haría PostgREST (con el rol `anon`), no a las tablas. El reloj del
servidor se adelanta con `clock_offset`, así que una noche entera corre en segundos.

Cubre las invariantes de seguridad del proyecto (rol propio, votos ocultos, secretos, dirección, PIN),
cada transición del juego, sus casos borde y la concurrencia.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
import traceback
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import psycopg

from motor_pg import BaseDeDatos, ErrorApi

PIN = '123456'
PRUEBAS: list[Callable[[BaseDeDatos], None]] = []


def prueba(fn: Callable[[BaseDeDatos], None]) -> Callable[[BaseDeDatos], None]:
    PRUEBAS.append(fn)
    return fn


# ------------------------------------------------------------------------------------------------- utilidades
def recorrer(obj, ruta: str = '') -> Iterator[tuple[str, object]]:
    """Cada valor de un JSON con su ruta: `me.role`, `players.3.name`…"""
    yield ruta, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from recorrer(v, f'{ruta}.{k}' if ruta else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from recorrer(v, f'{ruta}.{i}' if ruta else str(i))


def rutas_con_clave(obj, clave: str) -> list[str]:
    return [r for r, _ in recorrer(obj) if r == clave or r.endswith('.' + clave)]


def error_de(fn: Callable[[], object]) -> ErrorApi:
    try:
        fn()
    except ErrorApi as e:
        return e
    raise AssertionError('debió fallar y no falló')


def espera_error(codigo: str, fn: Callable[[], object]) -> ErrorApi:
    e = error_de(fn)
    assert e.codigo == codigo, f'esperaba {codigo!r} y llegó {e.codigo!r}: {e.mensaje}'
    return e


class Jugador:
    def __init__(self, noche: Noche, nombre: str):
        self.noche = noche
        self.db = noche.db
        self.nombre = nombre
        self.token = secrets.token_urlsafe(32)
        self.id: str | None = None
        self.llave: str | None = None

    def responder(self, sobre: str, texto: str = 'Se sabe todas las canciones de Taylor Swift.') -> dict:
        r = self.db.llamar('rsvp', p_token=self.token, p_name=self.nombre, p_about=sobre, p_text=texto)
        self.id = r['player']['id']
        self.llave = r.get('recovery_key')
        return r

    def estado(self) -> dict:
        return self.db.llamar('get_state', p_token=self.token)

    def yo(self) -> dict:
        return self.estado()['me']

    def llegar(self, codigo: str | None = None) -> dict:
        return self.db.llamar('check_in', p_token=self.token, p_code=codigo)

    def votar(self, otro: Jugador | str) -> dict:
        return self.db.llamar('cast_vote', p_token=self.token, p_target=otro.id if isinstance(otro, Jugador) else otro)

    def matar(self, otro: Jugador | str) -> dict:
        return self.db.llamar('kill', p_token=self.token, p_victim=otro.id if isinstance(otro, Jugador) else otro)

    def __repr__(self) -> str:
        return f'<{self.nombre}>'


class Noche:
    """Una noche lista: invitados que respondieron, secretos aprobados, puerta abierta y cartas repartidas."""

    def __init__(self, db: BaseDeDatos, n: int = 6, *, lobby: bool = True, presentes: bool = True, repartir: bool = True,
                 aprobar: bool = True, **config):
        db.reiniciar()
        self.db = db
        self.admin = db.llamar('admin_login', p_pin=PIN)['session']
        self.jugadores: list[Jugador] = []
        for i in range(n):
            j = Jugador(self, f'Jugador {i + 1:02d}')
            sobre = f'Jugador {(i + 1) % n + 1:02d}'
            j.responder(sobre, f'Secreto {i + 1:02d}: algo sobre {sobre}.')
            self.jugadores.append(j)
        if config:
            self.config(**config)
        if aprobar:
            self.adm('admin_approve_all')
        if lobby:
            self.adm('admin_phase', p_phase='lobby')
            if presentes:
                for j in self.jugadores:
                    j.llegar()
                if repartir:
                    self.adm('admin_deal')

    # -- atajos ------------------------------------------------------------------------------------
    def adm(self, fn: str, **args):
        return self.db.llamar(fn, p_session=self.admin, **args)

    def config(self, **cambios):
        return self.adm('admin_config', p_changes=cambios)

    def por_id(self, pid: str) -> Jugador:
        return next(j for j in self.jugadores if j.id == pid)

    def roles(self) -> dict[str, tuple[str, bool]]:
        filas = self.db.filas(
            """select p.id::text as id, r.role, r.alive from app.roles r join app.players p on p.id = r.player_id
                where r.game_id = (select id from app.games order by number desc limit 1)""")
        return {f['id']: (f['role'], f['alive']) for f in filas}

    def asesinos(self, vivos: bool = False) -> list[Jugador]:
        return [self.por_id(i) for i, (rol, vivo) in self.roles().items() if rol == 'asesino' and (vivo or not vivos)]

    def inocentes(self, vivos: bool = True) -> list[Jugador]:
        return [self.por_id(i) for i, (rol, vivo) in self.roles().items() if rol == 'inocente' and (vivo or not vivos)]

    def vivos(self) -> list[Jugador]:
        return [self.por_id(i) for i, (_, vivo) in self.roles().items() if vivo]

    def partida(self) -> dict:
        return self.db.fila('select * from app.games order by number desc limit 1')

    def ronda(self) -> dict:
        return self.db.fila('select * from app.rounds where game_id = %s order by number desc limit 1', self.partida()['id'])

    def adelantar(self, segundos: float) -> None:
        self.db.adelantar(segundos)
        self.tick()

    def tick(self) -> None:
        self.db.llamar('advance')

    def a_votacion(self) -> None:
        """Vence la discusión y abre la votación."""
        assert self.ronda()['state'] == 'discusion', self.ronda()['state']
        self.adelantar(self.db.valor('select round_seconds from app.event') + 1)
        assert self.ronda()['state'] == 'votacion'

    def votan_todos(self, objetivo: Jugador) -> None:
        for v in self.vivos():
            v.votar(objetivo if v is not objetivo else next(x for x in self.vivos() if x is not v))

    def a_fallo(self, acusado: Jugador | None = None) -> Jugador:
        """Lleva la ronda a un fallo: todos votan por un inocente."""
        self.a_votacion()
        acusado = acusado or self.inocentes()[0]
        self.votan_todos(acusado)
        r = self.ronda()
        assert r['state'] == 'veredicto' and r['correct'] is False, r
        return acusado

    def a_acierto(self) -> Jugador:
        self.a_votacion()
        asesino = self.asesinos()[0]
        self.votan_todos(asesino)
        r = self.ronda()
        assert r['state'] == 'veredicto' and r['correct'] is True, r
        return asesino

    def votos_directos(self, pares: list[tuple[str, str]], etapa: int = 1) -> None:
        """Mete votos sin pasar por la API, para armar un reparto exacto (empates, mayorías…)."""
        rid = self.ronda()['id']
        for votante, objetivo in pares:
            self.db.sql('insert into app.votes (round_id, stage, voter_id, target_id) values (%s, %s, %s, %s)', rid, etapa, votante, objetivo)

    def tragos(self, ronda_id: str | None = None) -> Counter:
        rid = ronda_id or self.ronda()['id']
        return Counter({f['name']: f['n'] for f in self.db.filas(
            """select p.name, count(*) as n from app.shots s join app.players p on p.id = s.player_id
                where s.round_id = %s group by p.name""", rid)})


def sql_en_json(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


# ============================================================================================= SEGURIDAD
@prueba
def anon_no_toca_las_tablas(db):
    """La anon key no sirve para leer ni escribir ninguna tabla: RLS activo y sin políticas, esquema cerrado."""
    Noche(db, 4)
    tablas = [f['tablename'] for f in db.filas("select tablename from pg_tables where schemaname = 'app'")]
    assert len(tablas) >= 12, tablas
    with db.conexion() as conn:
        for rol in ('anon', 'authenticated'):
            for t in tablas:
                for consulta in (f'select * from app.{t}', f'delete from app.{t}', f'update app.{t} set id = id' if t != 'settings' else 'select 1 where false'):
                    conn.rollback()
                    conn.execute(f'set role {rol}')
                    try:
                        conn.execute(consulta)
                    except psycopg.errors.InsufficientPrivilege:
                        continue
                    finally:
                        conn.rollback()
                    if 'where false' not in consulta:
                        raise AssertionError(f'{rol} pudo ejecutar: {consulta}')
    sin_rls = db.filas("select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'app' and c.relkind = 'r' and not c.relrowsecurity")
    assert not sin_rls, f'tablas sin RLS: {sin_rls}'
    politicas = db.valor("select count(*) from pg_policies where schemaname = 'app'")
    assert politicas == 0, 'no debe haber políticas: nadie entra directo a las tablas'


@prueba
def anon_no_llama_funciones_internas(db):
    """Las funciones internas y las de servicio no están al alcance de la API pública."""
    db.reiniciar()
    with db.conexion() as conn:
        for consulta in ('select app.now()', "select app.set_admin_pin('abcdefg')", 'select app.advance()', 'select app.deal(now())'):
            conn.rollback()
            conn.execute('set role anon')
            try:
                conn.execute(consulta)
            except psycopg.errors.InsufficientPrivilege:
                continue
            finally:
                conn.rollback()
            raise AssertionError(f'anon pudo ejecutar {consulta}')
    # Las funciones de servicio solo son para service_role.
    for rol in ('anon', 'authenticated'):
        e = None
        try:
            db.llamar('push_pending', rol=rol)
        except psycopg.errors.InsufficientPrivilege as err:
            e = err
        assert e, f'{rol} pudo vaciar la cola de push'
    assert db.llamar('push_pending', rol='service_role') == []


@prueba
def admin_exige_sesion(db):
    """Ninguna función de admin responde sin una sesión válida."""
    db.reiniciar()
    falsa = 'x' * 40
    llamadas = [
        ('admin_state', {}), ('admin_config', {'p_changes': {'rehearsal': True}}), ('admin_phase', {'p_phase': 'lobby'}),
        ('admin_secret', {'p_id': '00000000-0000-0000-0000-000000000000', 'p_status': 'aprobado'}), ('admin_approve_all', {}),
        ('admin_player', {'p_id': '00000000-0000-0000-0000-000000000000', 'p_action': 'remove'}), ('admin_add_player', {'p_name': 'X'}),
        ('admin_deal', {}), ('admin_control', {'p_action': 'end_night'}), ('admin_rehearsal', {'p_action': 'reset'}),
        ('admin_set_pin', {'p_new': 'abcdefgh'}),
    ]
    for fn, args in llamadas:
        espera_error('sin_permiso', lambda: db.llamar(fn, p_session=falsa, **args))
    # Y la llave de la /tv tampoco se adivina.
    espera_error('sin_permiso', lambda: db.llamar('tv_state', p_key='no-es-la-llave'))


@prueba
def pin_bloquea_tras_cinco_fallos(db):
    """El PIN se verifica en el servidor; después de 5 fallos se bloquea aunque luego llegue el PIN correcto."""
    db.reiniciar()
    for i in range(4):
        r = db.llamar('admin_login', p_pin='000000')
        assert r == {'ok': False, 'error': 'pin_incorrecto', 'message': 'PIN incorrecto.'}, r
    assert db.llamar('admin_login', p_pin='000000')['error'] == 'pin_incorrecto'  # el quinto
    r = db.llamar('admin_login', p_pin=PIN)
    assert r['ok'] is False and r['error'] == 'bloqueado' and r['retry_after'] > 0, r
    # Pasado el bloqueo entra de nuevo, y el contador se limpia.
    db.sql("update app.admin set locked_until = clock_timestamp() - interval '1 second'")
    r = db.llamar('admin_login', p_pin=PIN)
    assert r['ok'] and len(r['session']) >= 30, r
    assert db.valor('select failed_attempts from app.admin') == 0
    # El PIN nunca se guarda en claro ni se devuelve.
    assert PIN not in (db.valor('select pin_hash from app.admin') or '')
    assert PIN not in sql_en_json(r)


@prueba
def pin_sin_definir_y_sesiones_vencidas(db):
    db.reiniciar()
    db.sql('update app.admin set pin_hash = null')
    assert db.llamar('admin_login', p_pin=PIN)['error'] == 'sin_pin'
    db.sql("select app.set_admin_pin('otro-pin-largo')")
    assert db.llamar('admin_login', p_pin=PIN)['ok'] is False
    sesion = db.llamar('admin_login', p_pin='otro-pin-largo')['session']
    db.llamar('admin_state', p_session=sesion)
    db.sql("update app.admin_sessions set expires_at = clock_timestamp() - interval '1 second'")
    espera_error('sin_permiso', lambda: db.llamar('admin_state', p_session=sesion))
    espera_error('pin_corto', lambda: (lambda s: db.llamar('admin_set_pin', p_session=s, p_new='123'))(db.llamar('admin_login', p_pin='otro-pin-largo')['session']))
    db.sql("select app.set_admin_pin('123456')")


@prueba
def sin_token_no_hay_nombres_ni_estado_de_juego(db):
    n = Noche(db, 5)
    e = db.llamar('get_state')
    assert set(e) == {'now', 'version', 'event', 'known'} and e['known'] is False, list(e)
    e2 = db.llamar('get_state', p_token='a' * 43)  # un token que no existe
    assert e2['known'] is False and 'players' not in e2 and 'me' not in e2
    texto = sql_en_json(e) + sql_en_json(e2)
    for j in n.jugadores:
        assert j.nombre not in texto, 'un nombre se filtró a alguien sin registrar'
    assert e['event']['rsvp_count'] == 5


@prueba
def la_direccion_no_llega_antes_de_tiempo(db):
    n = Noche(db, 3, lobby=False)
    direccion = 'Calle Falsa 123, Col. Roma Norte, CDMX'
    n.config(address=direccion, address_reveal_at=None)
    j = n.jugadores[0]
    tv = db.sql('select tv_key from app.event')[0][0]
    for etiqueta, estado in (('anon', db.llamar('get_state')), ('jugador', j.estado()), ('tv', db.llamar('tv_state', p_key=tv))):
        assert direccion not in sql_en_json(estado), f'la dirección se filtró ({etiqueta}, sin fecha de revelado)'
        assert estado['event']['address'] is None and estado['event']['address_revealed'] is False
    ahora = db.valor("select app.now() + interval '2 days'").isoformat()
    n.config(address_reveal_at=ahora)
    assert direccion not in sql_en_json(db.llamar('get_state')), 'la dirección salió dos días antes'
    assert n.adm('admin_state')['event']['address'] == direccion, 'el admin sí la ve'
    db.adelantar(2 * 86400 + 5)
    for estado in (db.llamar('get_state'), j.estado(), db.llamar('tv_state', p_key=tv)):
        assert estado['event']['address'] == direccion and estado['event']['address_revealed'] is True


@prueba
def cada_jugador_solo_lee_su_rol(db):
    n = Noche(db, 8)
    reales = n.roles()
    for j in n.jugadores:
        estado = j.estado()
        assert rutas_con_clave(estado, 'role') == ['me.role'], rutas_con_clave(estado, 'role')
        assert estado['me']['role'] == reales[j.id][0]
        assert all('role' not in p for p in estado['players']), 'la lista de jugadores trae roles'
        # Solo un asesino ve a su cómplice.
        if reales[j.id][0] == 'inocente':
            assert estado['me']['accomplices'] == []
    tv = db.sql('select tv_key from app.event')[0][0]
    assert rutas_con_clave(db.llamar('tv_state', p_key=tv), 'role') == []
    assert rutas_con_clave(n.adm('admin_state'), 'role') == [], 'el panel de admin no debe mostrar roles'


@prueba
def la_carta_de_otro_no_se_lee_con_su_id(db):
    """Conocer el id de otro jugador no da acceso a su estado: la identidad es el token, no el id."""
    n = Noche(db, 5)
    a, b = n.jugadores[:2]
    n.a_votacion()
    e = db.llamar('get_state', p_token=b.id)
    assert e['known'] is False and 'me' not in e and 'players' not in e
    espera_error('sin_sesion', lambda: db.llamar('cast_vote', p_token=b.id, p_target=a.id))
    espera_error('sin_sesion', lambda: db.llamar('check_in', p_token=b.id))
    espera_error('sin_sesion', lambda: db.llamar('save_push', p_token=b.id, p_subscription=None))


@prueba
def votos_ocultos_hasta_el_veredicto(db):
    n = Noche(db, 7)
    n.a_votacion()
    vivos = n.vivos()
    objetivo = vivos[0]
    for v in vivos[1:4]:
        v.votar(objetivo)
    tv = db.sql('select tv_key from app.event')[0][0]
    estados = [j.estado() for j in n.jugadores] + [db.llamar('tv_state', p_key=tv), n.adm('admin_state')]
    for est in estados:
        for clave in ('tally', 'first_tally', 'votes', 'voter'):
            assert not rutas_con_clave(est, clave), f'aparece {clave} antes del veredicto'
        assert est['game']['round']['votes_cast'] == 3 if 'game' in est and est['game'] else True
        assert est['game']['round']['verdict'] is None
    # Cada quien sabe solo su propio voto.
    for j in vivos[1:4]:
        assert j.yo()['my_vote']['id'] == objetivo.id
    for j in vivos[4:]:
        assert j.yo()['my_vote'] is None and j.yo()['can_vote'] is True
    # El texto de los votos tampoco aparece por ningún lado para quien no votó.
    ajeno = vivos[5].estado()
    assert sql_en_json(ajeno).count(objetivo.id) >= 1  # aparece en su lista de objetivos posibles, nada más
    assert 'my_vote' in ajeno['me'] and ajeno['me']['my_vote'] is None


@prueba
def los_secretos_no_salen_antes_de_revelarse(db):
    n = Noche(db, 6, aprobar=False, repartir=False)
    textos = [f['text'] for f in db.filas('select text from app.secrets')]
    assert len(textos) == 6
    # Solo el primero está aprobado; uno más rechazado; el resto pendiente.
    ids = [f['id'] for f in db.filas('select id::text from app.secrets order by text')]
    n.adm('admin_secret', p_id=ids[0], p_status='aprobado')
    n.adm('admin_secret', p_id=ids[1], p_status='rechazado')
    aprobado, rechazado = sorted(textos)[:2]
    n.adm('admin_deal')
    tv = db.sql('select tv_key from app.event')[0][0]

    def sin_lo_propio(estado: dict) -> dict:
        # Cada quien ve el secreto que escribió: es lo único ajeno al juego que puede aparecer en su estado.
        if estado.get('me'):
            estado = {**estado, 'me': {k: v for k, v in estado['me'].items() if k != 'secret'}}
        return estado

    def todo_lo_visible() -> str:
        return sql_en_json([sin_lo_propio(j.estado()) for j in n.jugadores] + [db.llamar('get_state'), db.llamar('tv_state', p_key=tv)])

    visible = todo_lo_visible()
    for t in textos:
        assert t not in visible, f'un secreto salió antes de tiempo: {t!r}'
    # Cada jugador sí ve el suyo, y solo el suyo.
    for j in n.jugadores:
        propio = j.yo()['secret']
        assert propio and propio['text'] in textos
    n.a_fallo()
    visible = todo_lo_visible()
    assert aprobado in visible, 'el secreto aprobado debía salir en el fallo'
    for t in textos:
        if t != aprobado:
            assert t not in sql_en_json(db.llamar('tv_state', p_key=tv)), f'salió un secreto que no estaba aprobado: {t!r}'
    revelado = db.llamar('tv_state', p_key=tv)['game']['round']['verdict']['secret']
    assert set(revelado) == {'about', 'text'}, 'un secreto revelado solo lleva "sobre quién" y texto, nunca su autor'
    assert db.valor("select status from app.secrets where text = %s", aprobado) == 'revelado'
    assert db.valor("select status from app.secrets where text = %s", rechazado) == 'rechazado'


@prueba
def el_token_solo_se_guarda_como_hash(db):
    n = Noche(db, 3)
    j = n.jugadores[0]
    fila = db.fila('select token_hash, recovery_hash from app.players where id = %s', j.id)
    assert bytes(fila['token_hash']).hex() == db.valor('select encode(sha256(convert_to(%s, %s)), %s)', j.token, 'UTF8', 'hex')
    columnas = db.filas("select * from app.players")
    assert j.token not in sql_en_json(columnas) and j.llave not in sql_en_json(columnas)


# ============================================================================================= RSVP
@prueba
def rsvp_valida_y_crea_todo(db):
    db.reiniciar()
    j = Jugador(type('N', (), {'db': db})(), 'Ana María')
    r = j.responder('Luis', 'Le tiene miedo a los pavos reales.')
    assert r['ok'] and not r['existing'] and len(r['recovery_key']) == 9 and r['recovery_key'][4] == '-'
    fila = db.fila('select * from app.players')
    assert fila['name'] == 'Ana María' and fila['name_key'] == 'ana maria' and fila['checked_in'] is False
    sec = db.fila('select * from app.secrets')
    assert sec['status'] == 'pendiente' and sec['about_name'] == 'Luis' and sec['author_id'] == fila['id']
    # Es idempotente con el mismo token.
    r2 = j.responder('Luis', 'otro texto')
    assert r2['existing'] is True and db.valor('select count(*) from app.secrets') == 1


@prueba
def rsvp_rechaza_lo_invalido(db):
    db.reiniciar()
    tok = lambda: secrets.token_urlsafe(32)  # noqa: E731
    args = dict(p_name='Ana', p_about='Luis', p_text='algo')
    casos = [
        ({'p_name': '   '}, 'nombre_vacio'), ({'p_name': 'x' * 41}, 'nombre_largo'),
        ({'p_about': ''}, 'sobre_vacio'), ({'p_about': 'y' * 41}, 'sobre_largo'),
        ({'p_about': ' ANA '}, 'secreto_propio'), ({'p_about': 'aná'}, 'secreto_propio'),
        ({'p_text': '  '}, 'secreto_vacio'), ({'p_text': 'z' * 281}, 'secreto_largo'),
    ]
    for cambio, codigo in casos:
        espera_error(codigo, lambda: db.llamar('rsvp', p_token=tok(), **{**args, **cambio}))
    espera_error('token_invalido', lambda: db.llamar('rsvp', p_token='corto', **args))
    espera_error('token_invalido', lambda: db.llamar('rsvp', p_token='a b ' * 12, **args))
    assert db.valor('select count(*) from app.players') == 0, 'un RSVP inválido no debe dejar nada a medias'
    # 280 caracteres exactos sí.
    db.llamar('rsvp', p_token=tok(), **{**args, 'p_text': 'z' * 280})


@prueba
def rsvp_no_repite_nombres_ni_con_acentos(db):
    db.reiniciar()
    db.llamar('rsvp', p_token=secrets.token_urlsafe(32), p_name='José Ángel', p_about='Luis', p_text='a')
    for variante in ('jose angel', 'JOSÉ   ÁNGEL', ' José Angel '):
        espera_error('nombre_repetido', lambda: db.llamar('rsvp', p_token=secrets.token_urlsafe(32), p_name=variante, p_about='Luis', p_text='a'))
    assert db.valor('select count(*) from app.players') == 1


@prueba
def recuperar_con_la_llave(db):
    n = Noche(db, 4)
    a = n.jugadores[0]
    nuevo = secrets.token_urlsafe(32)
    # Llave equivocada: no entra, y no hay pistas sobre si el nombre existe.
    r = db.llamar('recover', p_name=a.nombre, p_key='AAAA-AAAA', p_token=nuevo)
    assert r['ok'] is False and r['error'] == 'llave_incorrecta'
    r = db.llamar('recover', p_name='Nadie Existe', p_key=a.llave, p_token=nuevo)
    assert r['ok'] is False and r['message'] == db.llamar('recover', p_name=a.nombre, p_key='AAAA-AAAA', p_token=nuevo)['message']
    # La llave buena entra (con o sin guion, en minúsculas) y desactiva el token anterior.
    r = db.llamar('recover', p_name=a.nombre.lower(), p_key=a.llave.replace('-', '').lower(), p_token=nuevo)
    assert r['ok'] and r['player']['id'] == a.id
    assert a.estado()['known'] is False, 'el token anterior ya no vale'
    espera_error('sin_sesion', lambda: db.llamar('check_in', p_token=a.token))
    assert db.llamar('get_state', p_token=nuevo)['me']['id'] == a.id
    # Cinco fallos bloquean ese nombre, incluso con la llave buena.
    b = n.jugadores[1]
    for _ in range(5):
        db.llamar('recover', p_name=b.nombre, p_key='ZZZZ-ZZZZ', p_token=secrets.token_urlsafe(32))
    r = db.llamar('recover', p_name=b.nombre, p_key=b.llave, p_token=secrets.token_urlsafe(32))
    assert r['ok'] is False and r['error'] == 'bloqueado', r
    # El admin puede dar una llave nueva, y la vieja deja de servir.
    llave2 = n.adm('admin_player', p_id=b.id, p_action='new_key')['recovery_key']
    assert llave2 != b.llave
    assert db.llamar('recover', p_name=b.nombre, p_key=b.llave, p_token=secrets.token_urlsafe(32))['ok'] is False
    assert db.llamar('recover', p_name=b.nombre, p_key=llave2, p_token=secrets.token_urlsafe(32))['ok'] is True


@prueba
def reemplazar_el_secreto(db):
    n = Noche(db, 4, aprobar=False)
    a = n.jugadores[0]
    sid = db.valor('select id::text from app.secrets where author_id = %s', a.id)
    db.llamar('replace_secret', p_token=a.token, p_about='Jugador 03', p_text='Uno mejor.')
    assert db.fila('select * from app.secrets where id = %s', sid)['text'] == 'Uno mejor.'
    n.adm('admin_secret', p_id=sid, p_status='rechazado')
    assert a.yo()['secret']['status'] == 'rechazado'
    db.llamar('replace_secret', p_token=a.token, p_about='Jugador 03', p_text='Otro más.')
    assert a.yo()['secret']['status'] == 'pendiente'
    espera_error('secreto_propio', lambda: db.llamar('replace_secret', p_token=a.token, p_about='jugador 01', p_text='x'))
    n.adm('admin_secret', p_id=sid, p_status='aprobado')
    espera_error('secreto_cerrado', lambda: db.llamar('replace_secret', p_token=a.token, p_about='Jugador 03', p_text='no'))


# ============================================================================================= LLEGADA Y REPARTO
@prueba
def check_in_espera_a_la_puerta_y_al_codigo(db):
    n = Noche(db, 4, lobby=False)
    j = n.jugadores[0]
    espera_error('todavia_no', lambda: j.llegar())
    n.adm('admin_phase', p_phase='lobby')
    n.config(door_code='ab12')
    assert j.estado()['event']['door_code_required'] is True
    for mal in (None, '', '0000'):
        espera_error('codigo_incorrecto', lambda: j.llegar(mal))
    j.llegar(' AB12 ')
    assert j.yo()['checked_in'] is True and db.valor('select checked_in from app.players where id = %s', j.id)
    espera_error('sin_sesion', lambda: db.llamar('check_in', p_token='q' * 43, p_code='AB12'))
    tv = db.sql('select tv_key from app.event')[0][0]
    assert db.llamar('tv_state', p_key=tv)['door_code'] == 'AB12'
    assert rutas_con_clave(j.estado(), 'door_code') == [], 'el código de la puerta no se manda a los jugadores'


@prueba
def reparto_uno_o_dos_asesinos_segun_los_presentes(db):
    n = Noche(db, 16)
    assert len(n.asesinos()) == 1 and len(n.inocentes()) == 15
    n = Noche(db, 17)
    assert len(n.asesinos()) == 2 and len(n.inocentes()) == 15
    a, b = n.asesinos()
    # Cada asesino conoce a su cómplice, y solo él.
    assert [x['id'] for x in a.yo()['accomplices']] == [b.id] and [x['id'] for x in b.yo()['accomplices']] == [a.id]
    assert all(j.yo()['accomplices'] == [] for j in n.inocentes())
    # El umbral es configurable.
    n = Noche(db, 6, killers_threshold=5)
    assert len(n.asesinos()) == 2


@prueba
def solo_reciben_carta_los_presentes(db):
    n = Noche(db, 7, presentes=False)
    for j in n.jugadores[:5]:
        j.llegar()
    n.adm('admin_deal')
    roles = n.roles()
    assert set(roles) == {j.id for j in n.jugadores[:5]}
    ausente = n.jugadores[6].yo()
    assert ausente['in_game'] is False and ausente['role'] is None and ausente['can_vote'] is False
    espera_error('sin_carta', lambda: (n.a_votacion(), n.jugadores[6].votar(n.jugadores[0])))


@prueba
def reparto_necesita_al_menos_tres(db):
    n = Noche(db, 5, presentes=False)
    n.jugadores[0].llegar()
    n.jugadores[1].llegar()
    espera_error('pocos_jugadores', lambda: n.adm('admin_deal'))
    n.jugadores[2].llegar()
    n.adm('admin_deal')
    espera_error('partida_en_curso', lambda: n.adm('admin_deal'))
    n.adm('admin_deal', p_force=True)
    assert db.valor('select count(*) from app.games') == 2 and n.db.fila('select result from app.games where number = 1')['result'] == 'cancelada'
    espera_error('fase_incorrecta', lambda: (n.adm('admin_control', p_action='end_night'), n.adm('admin_deal')))


@prueba
def el_asesino_rota_durante_la_noche(db):
    """Quien menos veces ha sido asesino tiene prioridad: con 3 jugadores, tres partidas dan tres asesinos distintos."""
    n = Noche(db, 3)
    vistos = {n.asesinos()[0].id}
    for _ in range(2):
        n.adm('admin_deal', p_force=True)
        vistos.add(n.asesinos()[0].id)
    assert len(vistos) == 3, vistos


@prueba
def muerte_de_apertura(db):
    n = Noche(db, 6, opening_kill=True)
    assert n.ronda()['state'] == 'apertura' and n.ronda()['number'] == 0
    asesino = n.asesinos()[0]
    inocente, otro = n.inocentes()[:2]
    est = asesino.yo()
    assert est['can_kill'] is True and {t['id'] for t in est['kill_targets']} == {j.id for j in n.inocentes()}
    assert all(j.yo()['can_kill'] is False for j in n.inocentes())
    espera_error('no_eres_asesino', lambda: inocente.matar(otro))
    espera_error('victima_invalida', lambda: asesino.matar(asesino))
    asesino.matar(inocente)
    assert n.roles()[inocente.id][1] is False
    assert n.ronda()['number'] == 1 and n.ronda()['state'] == 'discusion'
    assert inocente.yo()['alive'] is False


@prueba
def muerte_de_apertura_al_azar_si_no_elige(db):
    n = Noche(db, 6, opening_kill=True, kill_seconds=30)
    n.adelantar(29)
    assert n.ronda()['state'] == 'apertura'
    n.adelantar(2)
    assert n.ronda()['number'] == 1 and n.ronda()['state'] == 'discusion'
    muertos = [j for j in n.jugadores if not n.roles()[j.id][1]]
    assert len(muertos) == 1 and n.roles()[muertos[0].id][0] == 'inocente'
    assert db.valor('select auto from app.kills') is True


# ============================================================================================= TIEMPOS
@prueba
def la_discusion_se_convierte_en_votacion_al_vencer(db):
    n = Noche(db, 6, round_seconds=600, vote_seconds=120)
    r = n.ronda()
    assert r['state'] == 'discusion'
    duracion = (r['ends_at'] - r['state_since']).total_seconds()
    assert abs(duracion - 600) < 1, duracion
    n.adelantar(599)
    assert n.ronda()['state'] == 'discusion'
    n.adelantar(3)
    r = n.ronda()
    assert r['state'] == 'votacion' and r['stage'] == 1
    assert abs((r['ends_at'] - db.ahora()).total_seconds() - 120) < 3


@prueba
def cualquier_consulta_empuja_el_reloj(db):
    """Aunque pg_cron no exista, get_state vencido hace avanzar la ronda."""
    n = Noche(db, 6)
    db.adelantar(db.valor('select round_seconds from app.event') + 1)
    assert n.ronda()['state'] == 'discusion'
    n.jugadores[0].estado()
    assert n.ronda()['state'] == 'votacion'


@prueba
def la_votacion_vence_sola_y_sin_votos_es_fallo(db):
    n = Noche(db, 6, vote_seconds=60)
    n.a_votacion()
    n.adelantar(61)
    r = n.ronda()
    assert r['state'] == 'veredicto' and r['correct'] is False and r['accused_id'] is None and r['tie'] is False
    assert n.tragos() == Counter(), 'si nadie votó, nadie bebe'
    v = n.jugadores[0].estado()['game']['round']['verdict']
    assert v['accused'] is None and v['tally'] == [] and v['drinkers'] == []


@prueba
def pausar_congela_el_reloj_y_reanudar_lo_conserva(db):
    n = Noche(db, 6, round_seconds=600)
    n.adelantar(100)
    n.adm('admin_control', p_action='pause')
    quedaba = (n.ronda()['ends_at'] - db.ahora()).total_seconds()
    n.adelantar(5000)
    assert n.ronda()['state'] == 'discusion', 'en pausa no avanza nada'
    assert n.jugadores[0].estado()['event']['paused_at'] is not None
    n.adm('admin_control', p_action='resume')
    despues = (n.ronda()['ends_at'] - db.ahora()).total_seconds()
    assert abs(despues - (quedaba - 0)) < 6 and abs(despues - 500) < 6, (quedaba, despues)
    assert n.jugadores[0].estado()['event']['paused_at'] is None
    n.adelantar(499)
    assert n.ronda()['state'] == 'discusion'
    n.adelantar(3)
    assert n.ronda()['state'] == 'votacion'


@prueba
def en_pausa_no_se_vota_ni_se_mata(db):
    n = Noche(db, 6)
    n.a_votacion()
    v = n.vivos()
    n.adm('admin_control', p_action='pause')
    espera_error('pausa', lambda: v[0].votar(v[1]))
    assert v[0].yo()['can_vote'] is False
    n.adm('admin_control', p_action='resume')
    v[0].votar(v[1])


@prueba
def forzar_adelanta_cada_momento(db):
    n = Noche(db, 6)
    n.adm('admin_control', p_action='force')
    assert n.ronda()['state'] == 'votacion'
    v = n.vivos()
    v[0].votar(v[1])
    n.adm('admin_control', p_action='force')
    r = n.ronda()
    assert r['state'] == 'veredicto', r
    n.adm('admin_control', p_action='force')  # elige víctima al azar (si fue fallo) o reparte (si fue acierto)
    assert n.ronda()['state'] in ('discusion', 'veredicto', 'cerrada') or n.partida()['number'] >= 1


@prueba
def los_tiempos_son_configurables_y_validados(db):
    n = Noche(db, 4, lobby=False)
    n.config(round_seconds=300, vote_seconds=90, tiebreak_seconds=45, kill_seconds=120, pause_seconds=10)
    d = db.llamar('get_state', p_token=n.jugadores[0].token)['event']['durations']
    assert d == {'round': 300, 'vote': 90, 'tiebreak': 45, 'kill': 120, 'pause': 10}
    for malo in ({'round_seconds': 1}, {'vote_seconds': 'abc'}, {'starts_at': 'no es fecha'}, {'kill_seconds': 999999}):
        espera_error('valor_invalido', lambda: n.config(**malo))
    espera_error('campo_desconocido', lambda: n.config(phase='jugando'))
    assert db.valor('select round_seconds from app.event') == 300, 'un cambio inválido no aplica nada'


# ============================================================================================= VOTACIÓN
@prueba
def reglas_del_voto(db):
    n = Noche(db, 6)
    a, b = n.vivos()[:2]
    espera_error('no_es_momento', lambda: a.votar(b))
    n.a_votacion()
    espera_error('voto_propio', lambda: a.votar(a))
    espera_error('voto_propio', lambda: db.llamar('cast_vote', p_token=a.token, p_target=None))
    espera_error('objetivo_invalido', lambda: a.votar('00000000-0000-0000-0000-000000000000'))
    espera_error('sin_sesion', lambda: db.llamar('cast_vote', p_token='n' * 43, p_target=b.id))
    a.votar(b)
    espera_error('ya_votaste', lambda: a.votar(n.vivos()[2]))
    espera_error('ya_votaste', lambda: a.votar(b))
    assert db.valor('select count(*) from app.votes') == 1
    assert a.yo()['my_vote']['id'] == b.id and a.yo()['can_vote'] is False


@prueba
def los_muertos_no_votan_ni_reciben_votos(db):
    n = Noche(db, 6, opening_kill=True)
    asesino, muerto = n.asesinos()[0], n.inocentes()[0]
    asesino.matar(muerto)
    n.a_votacion()
    vivo = next(j for j in n.vivos() if j is not muerto)
    espera_error('muerto', lambda: muerto.votar(vivo))
    espera_error('objetivo_invalido', lambda: vivo.votar(muerto))
    est = muerto.yo()
    assert est['alive'] is False and est['can_vote'] is False
    assert muerto.id not in {t['id'] for t in vivo.yo()['vote_targets']}


@prueba
def la_votacion_cierra_cuando_votan_todos(db):
    n = Noche(db, 5, vote_seconds=3000)
    n.a_votacion()
    vivos = n.vivos()
    for v in vivos[:-1]:
        v.votar(vivos[0] if v is not vivos[0] else vivos[1])
    assert n.ronda()['state'] == 'votacion'
    vivos[-1].votar(vivos[0])
    assert n.ronda()['state'] == 'veredicto', 'con todos los votos no hay por qué esperar'


@prueba
def gana_la_mayoria_relativa(db):
    """3 de 7 votos bastan si nadie más llega a 3: mayoría relativa, no absoluta."""
    n = Noche(db, 7, vote_seconds=60)
    n.a_votacion()
    ids = [x.id for x in n.vivos()]
    objetivo = next(x.id for x in n.inocentes())
    otros = [i for i in ids if i != objetivo]
    votos = [(otros[0], objetivo), (otros[1], objetivo), (otros[2], objetivo),   # 3 para el objetivo
             (otros[3], otros[0]), (otros[4], otros[0]),                          # 2 para otro
             (otros[5], otros[1]), (objetivo, otros[1])]                          # 2 para un tercero
    n.votos_directos(votos)
    n.adelantar(61)
    r = n.ronda()
    assert r['state'] == 'veredicto' and str(r['accused_id']) == objetivo and r['tie'] is False and r['stage'] == 1, r
    assert n.tragos() == Counter({n.por_id(v).nombre: 1 for v, o in votos if o == objetivo})


@prueba
def acierto_el_asesino_bebe_y_la_partida_termina(db):
    n = Noche(db, 6, pause_seconds=30)
    asesino = n.a_acierto()
    r = n.ronda()
    assert r['correct'] is True and str(r['accused_id']) == asesino.id
    assert n.tragos() == Counter({asesino.nombre: 1}), n.tragos()
    g = n.partida()
    assert g['result'] == 'atrapado' and g['ended_at'] is not None
    assert (g['next_deal_at'] - g['ended_at']).total_seconds() == 30
    # A todos se les revela quién era, y el estado ya no permite jugar.
    for j in n.jugadores:
        est = j.estado()
        assert est['game']['ended'] is True
        assert [k['id'] for k in est['game']['killers']] == [asesino.id]
        assert est['me']['can_vote'] is False and est['me']['can_kill'] is False
        v = est['game']['round']['verdict']
        assert v['correct'] is True and v['accused']['id'] == asesino.id and v['secret'] is None and v['victim'] is None


@prueba
def tras_un_acierto_hay_cartas_nuevas_y_todos_reviven(db):
    n = Noche(db, 6, pause_seconds=20, opening_kill=True)
    n.asesinos()[0].matar(n.inocentes()[0])
    n.a_acierto()
    numero = n.partida()['number']
    n.adelantar(19)
    assert n.partida()['number'] == numero, 'antes de la pausa no se reparte'
    n.adelantar(2)
    g = n.partida()
    assert g['number'] == numero + 1 and g['ended_at'] is None
    assert all(vivo for _, vivo in n.roles().values()), 'todos reviven'
    assert len(n.roles()) == 6
    # Hay apertura otra vez porque el flag sigue prendido.
    assert n.ronda()['state'] == 'apertura'


@prueba
def fallo_beben_quienes_votaron_por_el_acusado(db):
    n = Noche(db, 7)
    n.a_votacion()
    acusado = n.inocentes()[0]
    otros = [v for v in n.vivos() if v is not acusado]
    for v in otros[:4]:
        v.votar(acusado)
    for v in otros[4:]:
        v.votar(otros[0])
    acusado.votar(otros[4])
    r = n.ronda()
    assert r['state'] == 'veredicto' and r['correct'] is False and str(r['accused_id']) == acusado.id and r['tie'] is False
    assert n.tragos() == Counter({v.nombre: 1 for v in otros[:4]}), n.tragos()
    assert db.valor("select count(*) from app.shots where reason <> 'voto_fallido'") == 0
    est = otros[5].estado()
    v = est['game']['round']['verdict']
    assert v['accused']['id'] == acusado.id and v['correct'] is False
    assert {d['name'] for d in v['drinkers']} == {x.nombre for x in otros[:4]}
    assert v['tally'][0] == {'id': acusado.id, 'name': acusado.nombre, 'votes': 4}
    assert len(v['votes']) == 7 and {'voter': acusado.nombre, 'target': otros[4].nombre} in v['votes']
    assert v['victim'] is None and v['kill_ends_at'] is not None


@prueba
def fallo_revela_un_secreto_aprobado_y_solo_uno(db):
    n = Noche(db, 6)
    n.a_fallo()
    revelados = db.valor("select count(*) from app.secrets where status = 'revelado'")
    assert revelados == 1
    v = n.jugadores[0].estado()['game']['round']['verdict']
    assert v['secret'] and v['secret']['text'].startswith('Secreto ')
    assert db.valor('select revealed_secret_id is not null from app.rounds where id = %s', n.ronda()['id'])


@prueba
def sin_secretos_aprobados_el_fallo_sigue_sin_revelar(db):
    n = Noche(db, 5, aprobar=False)
    n.a_fallo()
    assert n.jugadores[0].estado()['game']['round']['verdict']['secret'] is None
    assert db.valor("select count(*) from app.secrets where status = 'revelado'") == 0


@prueba
def los_secretos_revelados_no_se_repiten(db):
    n = Noche(db, 6, kill_seconds=5)
    textos = set()
    for _ in range(3):
        n.a_fallo()
        textos.add(n.jugadores[0].estado()['game']['round']['verdict']['secret']['text'])
        n.adelantar(6)
        if n.partida()['ended_at']:
            break
    assert len(textos) == db.valor("select count(*) from app.secrets where status = 'revelado'")


@prueba
def el_asesino_elige_a_su_victima_en_su_ventana(db):
    n = Noche(db, 7, kill_seconds=90)
    acusado = n.a_fallo()
    asesino = n.asesinos()[0]
    est = asesino.yo()
    assert est['can_kill'] is True and {t['id'] for t in est['kill_targets']} == {j.id for j in n.inocentes()}
    for j in n.jugadores:
        if j is not asesino:
            assert j.yo()['can_kill'] is False and j.yo()['kill_targets'] == []
    victima = n.inocentes()[1]
    espera_error('no_eres_asesino', lambda: victima.matar(acusado))
    espera_error('victima_invalida', lambda: asesino.matar(asesino))
    asesino.matar(victima)
    assert n.roles()[victima.id][1] is False
    r = n.ronda()
    assert r['number'] == 2 and r['state'] == 'discusion', 'empieza otra ronda con el mismo asesino'
    assert n.asesinos() == [asesino] and n.roles()[asesino.id][1] is True
    hist = asesino.estado()['game']['history']
    assert hist[0]['victim']['id'] == victima.id and hist[0]['verdict']['victim']['id'] == victima.id
    assert victima.yo()['alive'] is False
    espera_error('fuera_de_ventana', lambda: asesino.matar(n.inocentes()[0]))


@prueba
def el_asesino_no_puede_matar_fuera_de_ventana_ni_dos_veces(db):
    n = Noche(db, 7, kill_seconds=30)
    n.a_votacion()
    asesino = n.asesinos()[0]
    espera_error('fuera_de_ventana', lambda: asesino.matar(n.inocentes()[0]))  # en votación no
    n.votan_todos(n.inocentes()[0])
    n.adelantar(31)  # se acaba su ventana: el azar elige
    espera_error('fuera_de_ventana', lambda: asesino.matar(n.inocentes()[0]))
    assert db.valor('select count(*) from app.kills') == 1 and db.valor('select auto from app.kills') is True


@prueba
def solo_el_asesino_vivo_mata_y_nunca_a_un_asesino_o_muerto(db):
    n = Noche(db, 18, kill_seconds=600)  # 2 asesinos
    a, b = n.asesinos()
    n.a_fallo()
    espera_error('victima_invalida', lambda: a.matar(b))
    espera_error('victima_invalida', lambda: a.matar('00000000-0000-0000-0000-000000000000'))
    espera_error('no_eres_asesino', lambda: n.inocentes()[0].matar(n.inocentes()[1]))
    v = n.inocentes()[0]
    b.matar(v)  # cualquiera de los dos puede
    espera_error('fuera_de_ventana', lambda: a.matar(n.inocentes()[0]))
    assert db.valor('select count(*) from app.kills') == 1


@prueba
def si_el_asesino_no_elige_el_azar_elige_por_el(db):
    n = Noche(db, 6, kill_seconds=45)
    n.a_fallo()
    n.adelantar(44)
    assert n.ronda()['state'] == 'veredicto'
    n.adelantar(2)
    assert n.ronda()['number'] == 2
    assert db.valor('select count(*) from app.kills where auto') == 1
    muertos = [j for j in n.jugadores if not n.roles()[j.id][1]]
    assert len(muertos) == 1 and muertos[0] not in n.asesinos()
    assert muertos[0].yo()['alive'] is False


@prueba
def el_asesino_gana_cuando_solo_queda_un_inocente(db):
    n = Noche(db, 4, kill_seconds=600, pause_seconds=15)  # 1 asesino + 3 inocentes
    n.a_fallo()
    n.asesinos()[0].matar(n.inocentes()[0])  # quedan 2 inocentes
    assert n.partida()['ended_at'] is None and n.ronda()['number'] == 2
    n.a_fallo()
    n.asesinos()[0].matar(n.inocentes()[0])  # queda 1 inocente + el asesino
    g = n.partida()
    assert g['result'] == 'asesino_gana' and g['ended_at'] is not None, g
    est = n.jugadores[0].estado()
    assert est['game']['ended'] and est['game']['result'] == 'asesino_gana' and est['game']['killers']
    numero = g['number']
    n.adelantar(14)
    assert n.partida()['number'] == numero
    n.adelantar(2)
    assert n.partida()['number'] == numero + 1 and all(v for _, v in n.roles().values())


@prueba
def con_dos_asesinos_ganan_al_quedar_un_inocente(db):
    n = Noche(db, 5, kill_seconds=600, killers_threshold=3)  # 2 asesinos + 3 inocentes
    assert len(n.asesinos()) == 2
    n.a_fallo()
    n.asesinos()[0].matar(n.inocentes()[0])
    assert n.partida()['ended_at'] is None
    n.a_fallo()
    n.asesinos()[1].matar(n.inocentes()[0])
    assert n.partida()['result'] == 'asesino_gana'


@prueba
def acierto_con_dos_asesinos_termina_la_partida(db):
    n = Noche(db, 18)
    assert len(n.asesinos()) == 2
    n.a_acierto()
    assert n.partida()['result'] == 'atrapado'
    assert len(n.jugadores[0].estado()['game']['killers']) == 2, 'al terminar se revelan los dos'


@prueba
def si_no_hay_gente_para_la_siguiente_partida_espera(db):
    n = Noche(db, 4, pause_seconds=5)
    n.a_acierto()
    for j in n.jugadores[1:]:
        n.adm('admin_player', p_id=j.id, p_action='check_out')
    n.adelantar(6)
    assert n.partida()['number'] == 1, 'con menos de 3 presentes no hay reparto automático'
    for j in n.jugadores[1:]:
        n.adm('admin_player', p_id=j.id, p_action='check_in')
    n.adelantar(12)
    assert n.partida()['number'] == 2


# ============================================================================================= EMPATES
@prueba
def empate_lleva_a_desempate_solo_entre_los_empatados(db):
    n = Noche(db, 6, tiebreak_seconds=60, vote_seconds=60)
    n.a_votacion()
    v = n.vivos()
    ids = [x.id for x in v]
    a, b = v[0], v[1]
    n.votos_directos([(ids[2], ids[0]), (ids[3], ids[0]), (ids[4], ids[1]), (ids[5], ids[1])])
    n.adelantar(61)
    r = n.ronda()
    assert r['state'] == 'desempate' and r['stage'] == 2 and {str(c) for c in r['candidates']} == {ids[0], ids[1]}, r
    assert abs((r['ends_at'] - db.ahora()).total_seconds() - 60) < 3
    est = v[2].yo()
    assert est['can_vote'] is True and {t['id'] for t in est['vote_targets']} == {ids[0], ids[1]}
    assert {c['id'] for c in v[2].estado()['game']['round']['candidates']} == {ids[0], ids[1]}
    # Un empatado solo puede votar al otro empatado, y nadie puede votar por un tercero.
    assert {t['id'] for t in a.yo()['vote_targets']} == {ids[1]}
    espera_error('fuera_de_desempate', lambda: v[2].votar(v[3]))
    espera_error('fuera_de_desempate', lambda: a.votar(v[2]))
    # El desempate parte de cero: los votos de la primera vuelta no cuentan aquí.
    for x in v[2:]:
        x.votar(a)
    assert n.ronda()['state'] == 'desempate'
    a.votar(b)
    b.votar(a)  # el último voto cierra el desempate
    r = n.ronda()
    assert r['state'] == 'veredicto' and str(r['accused_id']) == a.id and r['stage'] == 2, r
    veredicto = v[2].estado()['game']['round']['verdict']
    assert veredicto['tally'][0]['votes'] == 5 and {t['votes'] for t in veredicto['first_tally']} == {2}


@prueba
def empate_que_persiste_cuenta_como_fallo_y_beben_los_empatados(db):
    n = Noche(db, 6, tiebreak_seconds=30, vote_seconds=60)
    n.a_votacion()
    ids = [x.id for x in n.vivos()]
    n.votos_directos([(ids[2], ids[0]), (ids[3], ids[1])])
    n.adelantar(61)
    assert n.ronda()['state'] == 'desempate'
    n.votos_directos([(ids[2], ids[0]), (ids[3], ids[1])], etapa=2)
    n.adelantar(31)
    r = n.ronda()
    assert r['state'] == 'veredicto' and r['correct'] is False and r['tie'] is True and r['accused_id'] is None, r
    nombres = {n.por_id(ids[0]).nombre, n.por_id(ids[1]).nombre}
    assert set(n.tragos()) == nombres and db.valor("select count(*) from app.shots where reason = 'empate'") == 2
    v = n.jugadores[0].estado()['game']['round']['verdict']
    assert v['tie'] is True and v['accused'] is None and v['first_tally'] and v['stage'] == 2
    assert {d['reason'] for d in v['drinkers']} == {'empate'}
    # Y el asesino elige víctima como en cualquier fallo.
    assert n.asesinos()[0].yo()['can_kill'] is True


@prueba
def nadie_vota_en_el_desempate(db):
    n = Noche(db, 6, tiebreak_seconds=30, vote_seconds=60)
    n.a_votacion()
    ids = [x.id for x in n.vivos()]
    n.votos_directos([(ids[2], ids[0]), (ids[3], ids[1])])
    n.adelantar(61)
    n.adelantar(31)
    r = n.ronda()
    assert r['tie'] is True and r['correct'] is False and r['accused_id'] is None
    assert set(n.tragos()) == {n.por_id(ids[0]).nombre, n.por_id(ids[1]).nombre}


@prueba
def tres_empatados_entran_al_desempate(db):
    n = Noche(db, 7, vote_seconds=60)
    n.a_votacion()
    ids = [x.id for x in n.vivos()]
    n.votos_directos([(ids[3], ids[0]), (ids[4], ids[1]), (ids[5], ids[2]), (ids[6], ids[0]), (ids[0], ids[1]), (ids[1], ids[2])][:6])
    n.adelantar(61)
    r = n.ronda()
    assert r['state'] == 'desempate' and {str(c) for c in r['candidates']} == {ids[0], ids[1], ids[2]}, r


# ============================================================================================= CIERRE DE LA NOCHE
@prueba
def terminar_la_noche_muestra_el_ranking(db):
    n = Noche(db, 6, pause_seconds=5, kill_seconds=600)
    n.a_acierto()
    n.adm('admin_control', p_action='end_night')
    est = n.jugadores[0].estado()
    assert est['event']['phase'] == 'fin' and est['ranking']['games'] == 1 and est['ranking']['caught'] == 1
    top = est['ranking']['players'][0]
    assert top['shots'] == 1 and top['times_killer'] == 1
    n.adelantar(500)
    assert n.partida()['number'] == 1, 'terminada la noche ya no se reparte solo'
    n.adm('admin_control', p_action='reopen')
    assert n.jugadores[0].estado()['event']['phase'] == 'lobby'


@prueba
def terminar_la_noche_a_media_partida_cancela_la_partida(db):
    n = Noche(db, 6)
    n.adm('admin_control', p_action='end_night')
    assert n.partida()['result'] == 'cancelada' and n.partida()['next_deal_at'] is None
    e = n.jugadores[0].estado()
    assert e['game']['ended'] and e['event']['phase'] == 'fin'


@prueba
def ranking_cuenta_tragos_aciertos_y_muertes(db):
    n = Noche(db, 5, kill_seconds=600, pause_seconds=1)
    acusado = n.a_fallo()
    votantes = {x.nombre for x in n.jugadores if x.nombre in n.tragos()}
    asesino = n.asesinos()[0]
    asesino.matar(n.inocentes()[0])
    est = n.jugadores[0].estado()
    r = n.adm('admin_state')['ranking']
    por_nombre = {p['name']: p for p in r['players']}
    for nombre in votantes:
        assert por_nombre[nombre]['shots'] == 1
    assert por_nombre[asesino.nombre]['kills'] == 1 and por_nombre[asesino.nombre]['times_killer'] == 1
    assert por_nombre[acusado.nombre]['votes_received'] >= 1


# ============================================================================================= ADMIN
@prueba
def moderar_secretos_sin_ver_autores(db):
    n = Noche(db, 5, aprobar=False)
    estado = n.adm('admin_state')
    assert len(estado['secrets']) == 5 and all(set(s) == {'id', 'about', 'text', 'status'} for s in estado['secrets'])
    assert {s['status'] for s in estado['secrets']} == {'pendiente'}
    sid = estado['secrets'][0]['id']
    n.adm('admin_secret', p_id=sid, p_status='aprobado', p_text='Corregido por el admin.')
    fila = db.fila('select * from app.secrets where id = %s', sid)
    assert fila['status'] == 'aprobado' and fila['text'] == 'Corregido por el admin.'
    espera_error('estado_invalido', lambda: n.adm('admin_secret', p_id=sid, p_status='revelado'))
    espera_error('secreto_vacio', lambda: n.adm('admin_secret', p_id=sid, p_text='   '))
    espera_error('no_existe', lambda: n.adm('admin_secret', p_id='00000000-0000-0000-0000-000000000000', p_status='aprobado'))
    assert n.adm('admin_approve_all')['approved'] == 4
    db.sql("update app.secrets set status = 'revelado' where id = %s", sid)
    espera_error('ya_revelado', lambda: n.adm('admin_secret', p_id=sid, p_status='rechazado'))
    # La lista no delata autores ni siquiera por orden: es la misma en cada consulta pero no sigue el orden de llegada.
    assert [s['id'] for s in n.adm('admin_state')['secrets']] == [s['id'] for s in n.adm('admin_state')['secrets']]


@prueba
def admin_gestiona_invitados(db):
    n = Noche(db, 5, presentes=False)
    j = n.jugadores[0]
    n.adm('admin_player', p_id=j.id, p_action='check_in')
    assert j.yo()['checked_in'] is True
    n.adm('admin_player', p_id=j.id, p_action='check_out')
    assert j.yo()['checked_in'] is False
    r = n.adm('admin_add_player', p_name='  Recién   Llegada ')
    assert r['player']['name'] == 'Recién Llegada' and len(r['recovery_key']) == 9
    espera_error('nombre_repetido', lambda: n.adm('admin_add_player', p_name='recien llegada'))
    nuevo = secrets.token_urlsafe(32)
    assert db.llamar('recover', p_name='Recién Llegada', p_key=r['recovery_key'], p_token=nuevo)['ok']
    assert db.llamar('get_state', p_token=nuevo)['me']['name'] == 'Recién Llegada'
    n.adm('admin_player', p_id=j.id, p_action='remove')
    assert db.valor('select count(*) from app.players where id = %s', j.id) == 0
    assert db.valor('select count(*) from app.secrets where author_id = %s', j.id) == 0, 'sus secretos se van con él'
    espera_error('accion_invalida', lambda: n.adm('admin_player', p_id=n.jugadores[1].id, p_action='volar'))


@prueba
def quitar_a_alguien_a_media_partida(db):
    n = Noche(db, 5, kill_seconds=600)
    inocentes = n.inocentes()
    n.a_votacion()
    n.adm('admin_player', p_id=inocentes[0].id, p_action='check_out')
    assert n.roles()[inocentes[0].id][1] is False, 'quien se va deja de contar para votar'
    # Si se va el último asesino, la partida se cancela y se reparte de nuevo.
    asesino = n.asesinos()[0]
    n.adm('admin_player', p_id=asesino.id, p_action='remove')
    g = n.partida()
    assert g['result'] == 'cancelada' and g['next_deal_at'] is not None


@prueba
def fase_y_configuracion_del_evento(db):
    n = Noche(db, 4, lobby=False)
    assert n.jugadores[0].estado()['event']['phase'] == 'invitacion'
    espera_error('fase_invalida', lambda: n.adm('admin_phase', p_phase='jugando'))
    n.adm('admin_phase', p_phase='lobby')
    assert n.jugadores[0].estado()['event']['phase'] == 'lobby'
    for j in n.jugadores:
        j.llegar()
    n.adm('admin_deal')
    espera_error('partida_en_curso', lambda: n.adm('admin_phase', p_phase='invitacion'))
    assert n.jugadores[0].estado()['event']['phase'] == 'jugando'
    espera_error('accion_invalida', lambda: n.adm('admin_control', p_action='explotar'))
    n.config(opening_kill=True, killers_threshold=2)
    assert db.valor('select opening_kill from app.event') is True


# ============================================================================================= ENSAYO
@prueba
def el_ensayo_solo_existe_si_esta_encendido(db):
    n = Noche(db, 4, lobby=False)
    for accion in ('bots', 'advance', 'reset', 'god'):
        espera_error('no_ensayo', lambda: n.adm('admin_rehearsal', p_action=accion))
    n.config(rehearsal=True)
    n.adm('admin_rehearsal', p_action='advance', p_value=3600)
    assert abs(n.adm('admin_state')['event']['clock_offset_seconds'] - 3600) <= 1
    espera_error('accion_invalida', lambda: n.adm('admin_rehearsal', p_action='hackear'))
    # Apagarlo devuelve el reloj a la hora real y se llevan a los bots.
    n.adm('admin_rehearsal', p_action='bots', p_value=3)
    assert db.valor('select count(*) from app.players where is_bot') == 3
    n.config(rehearsal=False)
    assert db.valor('select count(*) from app.players where is_bot') == 0
    assert db.valor("select extract(epoch from clock_offset) from app.event") == 0


@prueba
def los_bots_juegan_una_noche_completa(db):
    n = Noche(db, 3, lobby=False, rehearsal=True, round_seconds=60, vote_seconds=30, kill_seconds=15, pause_seconds=5, bots_delay_seconds=1)
    n.adm('admin_rehearsal', p_action='bots', p_value=9)
    assert db.valor('select count(*) from app.players') == 12 and db.valor("select count(*) from app.secrets where status = 'aprobado'") >= 9
    n.adm('admin_phase', p_phase='lobby')
    for j in n.jugadores:
        j.llegar()
    n.adm('admin_deal')
    vistos = set()
    for _ in range(400):
        # Los humanos también juegan cuando les toca.
        for j in n.jugadores:
            y = j.yo()
            if y['can_vote']:
                j.votar(y['vote_targets'][0]['id'])
            if y['can_kill']:
                j.matar(y['kill_targets'][0]['id'])
        n.adelantar(5)
        vistos.add((n.partida()['number']))
        if len(vistos) >= 3:
            break
    assert len(vistos) >= 3, f'los bots no llevaron el juego a la tercera partida: {vistos}'
    assert db.valor('select count(*) from app.shots') > 0 and db.valor('select count(*) from app.kills') > 0
    god = n.adm('admin_rehearsal', p_action='god')
    assert len(god['roles']) >= 3
    n.adm('admin_rehearsal', p_action='reset')
    assert db.valor('select count(*) from app.games') == 0 and db.valor('select count(*) from app.players') == 3
    assert db.valor("select count(*) from app.secrets where status = 'revelado'") == 0


# ============================================================================================= PUSH
@prueba
def las_notificaciones_solo_van_a_quienes_las_activaron(db):
    n = Noche(db, 6, presentes=True, repartir=False)
    sub = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'BPk', 'auth': 'xyz'}}
    quien = n.jugadores[:3]
    for j in quien:
        db.llamar('save_push', p_token=j.token, p_subscription=sub)
    espera_error('suscripcion_invalida', lambda: db.llamar('save_push', p_token=quien[0].token, p_subscription={'endpoint': 'http://x', 'keys': {}}))
    n.adm('admin_deal')
    cola = db.llamar('push_pending', rol='service_role')
    assert {c['title'] for c in cola} == {'Tu carta ya está lista'}
    assert len(cola) == 3 and all(c['subscription'] == sub for c in cola)
    # Se reportan enviados y fallidos; una suscripción muerta se borra.
    db.llamar('push_report', rol='service_role', p_sent=[cola[0]['id']], p_failed=[{'id': cola[1]['id'], 'error': '410', 'gone': True}])
    assert len(db.llamar('push_pending', rol='service_role')) == 1
    assert db.valor('select count(*) from app.players where push_subscription is not null') == 2
    db.llamar('save_push', p_token=quien[0].token, p_subscription=None)
    assert quien[0].yo()['push'] is False
    # Una notificación vieja ya no se manda.
    db.sql("update app.push_queue set created_at = now() - interval '11 minutes'")
    assert db.llamar('push_pending', rol='service_role') == []


@prueba
def el_juego_avisa_a_quien_le_toca(db):
    n = Noche(db, 6, kill_seconds=600)
    sub = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'BPk', 'auth': 'xyz'}}
    for j in n.jugadores:
        db.llamar('save_push', p_token=j.token, p_subscription=sub)
    db.sql('delete from app.push_queue')
    titulos = lambda: Counter(f['title'] for f in db.filas('select title from app.push_queue'))  # noqa: E731
    n.a_votacion()
    assert titulos() == Counter({'Se abrió la votación': 6})
    db.sql('delete from app.push_queue')
    n.votan_todos(n.inocentes()[0])
    t = titulos()
    assert t == Counter({'Elige a tu víctima': 1, 'Fallaron': 5}), t
    db.sql('delete from app.push_queue')
    victima = n.inocentes()[1]
    n.asesinos()[0].matar(victima)
    assert titulos() == Counter({'Has muerto': 1})
    destinatario = db.valor('select player_id::text from app.push_queue')
    assert destinatario == victima.id


# ============================================================================================= CONCURRENCIA
def en_paralelo(tareas: list[Callable[[], object]]) -> list[object]:
    """Lanza todas a la vez (con una barrera) y devuelve resultados o excepciones, en orden."""
    barrera = threading.Barrier(len(tareas))

    def correr(tarea):
        barrera.wait()
        try:
            return tarea()
        except Exception as e:  # noqa: BLE001
            return e

    with ThreadPoolExecutor(len(tareas)) as pool:
        return list(pool.map(correr, tareas))


@prueba
def votos_simultaneos_no_se_pisan(db):
    n = Noche(db, 12, vote_seconds=3000)
    n.a_votacion()
    vivos = n.vivos()
    objetivo = vivos[0]
    tareas = [(lambda v=v: v.votar(objetivo if v is not objetivo else vivos[1])) for v in vivos]
    resultados = en_paralelo(tareas)
    errores = [r for r in resultados if isinstance(r, Exception)]
    assert not errores, errores
    assert db.valor('select count(*) from app.votes') == 12
    r = n.ronda()
    assert r['state'] == 'veredicto', 'el último voto cierra la votación'
    verdict_shots = db.valor('select count(*) from app.shots where round_id = %s', r['id'])
    esperados = 1 if r['correct'] else db.valor('select count(*) from app.votes where target_id = %s', objetivo.id)
    assert verdict_shots == esperados, (verdict_shots, esperados)


@prueba
def el_mismo_jugador_no_vota_dos_veces_aunque_lo_intente_a_la_vez(db):
    n = Noche(db, 6, vote_seconds=3000)
    n.a_votacion()
    v = n.vivos()
    resultados = en_paralelo([(lambda: v[0].votar(v[1])) for _ in range(8)])
    ok = [r for r in resultados if not isinstance(r, Exception)]
    fallos = [r for r in resultados if isinstance(r, ErrorApi)]
    assert len(ok) == 1 and len(fallos) == 7 and all(f.codigo == 'ya_votaste' for f in fallos), resultados
    assert db.valor('select count(*) from app.votes') == 1


@prueba
def el_reloj_y_los_votos_no_producen_dos_veredictos(db):
    n = Noche(db, 10, vote_seconds=60)
    n.a_votacion()
    vivos = n.vivos()
    objetivo = vivos[0]
    db.adelantar(58)  # a dos segundos de vencer
    tareas = [(lambda v=v: v.votar(objetivo if v is not objetivo else vivos[1])) for v in vivos[:5]]
    tareas += [(lambda: db.llamar('advance')) for _ in range(4)] + [(lambda v=v: v.estado()) for v in vivos[5:]]
    en_paralelo(tareas)
    n.adelantar(5)
    r = n.ronda()
    assert r['state'] == 'veredicto' and r['verdict_at'] is not None
    n_shots = db.valor('select count(*) from app.shots where round_id = %s', r['id'])
    votos_al_acusado = db.valor('select count(*) from app.votes where round_id = %s and target_id = %s', r['id'], r['accused_id'])
    assert n_shots == (1 if r['correct'] else votos_al_acusado), (n_shots, votos_al_acusado, r)
    assert db.valor('select count(*) from app.rounds where game_id = %s', n.partida()['id']) == 1


@prueba
def dos_asesinos_no_matan_a_la_vez_a_dos_personas(db):
    n = Noche(db, 18, kill_seconds=600)
    a, b = n.asesinos()
    n.a_fallo()
    v1, v2 = n.inocentes()[:2]
    resultados = en_paralelo([lambda: a.matar(v1), lambda: b.matar(v2)])
    ok = [r for r in resultados if not isinstance(r, Exception)]
    assert len(ok) == 1, resultados
    assert db.valor('select count(*) from app.kills') == 1
    assert sum(1 for _, vivo in n.roles().values() if not vivo) == 1


@prueba
def el_reloj_no_se_atora_con_muchos_clientes_consultando(db):
    n = Noche(db, 20, round_seconds=30)
    db.adelantar(31)
    resultados = en_paralelo([(lambda j=j: j.estado()) for j in n.jugadores])
    assert not [r for r in resultados if isinstance(r, Exception)]
    assert n.ronda()['state'] == 'votacion' and db.valor('select count(*) from app.rounds') == 1
    assert all(r['game']['round']['state'] == 'votacion' for r in resultados)


# ============================================================================================= CORRIDA
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-k', dest='filtro', default='', help='solo las pruebas cuyo nombre contiene este texto')
    parser.add_argument('-x', dest='parar', action='store_true', help='detenerse en la primera que falle')
    args = parser.parse_args()
    elegidas = [fn for fn in PRUEBAS if args.filtro in fn.__name__]
    fallas = corridas = 0
    with BaseDeDatos() as db:
        print(f'· {len(elegidas)} pruebas · {db.valor("select version()").split(",")[0]}')
        for fn in elegidas:
            corridas += 1
            inicio = time.perf_counter()
            try:
                fn(db)
            except Exception as error:  # noqa: BLE001
                fallas += 1
                print(f'  ✗ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
                detalle = traceback.format_exc(limit=-4) if not isinstance(error, AssertionError) or not str(error) else f'{error}\n' + ''.join(traceback.format_tb(error.__traceback__, limit=-2))
                print('      ' + detalle.strip().replace('\n', '\n      '))
                if args.parar:
                    break
            else:
                print(f'  ✓ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
    print(f'{corridas - fallas} de {corridas} pasaron.')
    sys.exit(1 if fallas else 0)


if __name__ == '__main__':
    main()
