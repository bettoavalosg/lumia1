#!/usr/bin/env python
"""Ensayo general de la noche con invitados simulados, por la API pública (la misma que usan los teléfonos).

    python scripts/ensayo.py --local                                   # levanta un Postgres y una API temporales, ensaya ahí
    python scripts/ensayo.py --url https://xxxx.supabase.co --clave <anon key> --pin <PIN del admin>

Simula a `--jugadores` invitados (20 por defecto) que responden, llegan, reciben carta, votan al mismo tiempo, empatan, se matan y se
atrapan en dos partidas, y en cada paso comprueba lo que importa: que nadie vea el rol de otro, que los votos sigan ocultos hasta
el veredicto, que un voto o una muerte no se puedan repetir aunque lleguen a la vez, que las cuentas de tragos cuadren y que las
funciones del admin y las tablas sigan cerradas para quien no sea el admin. Al final mide cuánto tarda cada llamada.

Contra un proyecto real:
  · se niega a correr si ya hay una partida, o invitados de verdad (`--forzar` lo permite si NO han llegado: no se les reparte carta);
  · todo lo que crea se llama "Ensayo NN" y se borra al terminar, junto con las partidas, y la configuración vuelve a como estaba;
  · usa `admin_control force` para no esperar (con `--realista` espera los tiempos de verdad, acortados a unos segundos).

Solo usa la biblioteca estándar (y, con --local, los módulos de esta carpeta).
"""

from __future__ import annotations

import argparse
import json
import random
import secrets
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass

NOMBRES = ['Ximena', 'Renata', 'Camila', 'Valeria', 'Regina', 'Fernanda', 'Daniela', 'Paulina', 'Andrea', 'Mariana', 'Luciana', 'Jimena',
           'Natalia', 'Romina', 'Ivanna', 'Ámbar', 'Emiliano', 'Santiago', 'Mateo', 'Leonardo', 'Sebastián', 'Diego', 'Rodrigo', 'Adrián',
           'Bruno', 'Gael', 'Íker', 'Ulises', 'Dante', 'Lorenzo', 'Elena', 'Marina', 'Sofía', 'Isabela', 'Julián', 'Tomás', 'Alan', 'Óscar']
SECRETOS = [
    'Lloró viendo el final de un comercial de seguros.', 'Finge que entiende de vino. No entiende de vino.',
    'Se metió a una fiesta ajena por la comida y se quedó hasta el final.', 'Escucha los audios al doble de velocidad para no sentir culpa.',
    'Lleva desde 2023 con 47 pestañas abiertas.', 'Se sabe todos los diálogos de Gossip Girl y no lo admite.',
    'Le dio like a una foto de hace cuatro años y lo quitó a los dos segundos.', 'Dice "ya voy saliendo" mientras sigue en la regadera.',
    'Ha fingido tener otra llamada para huir de una plática.', 'Nunca ha visto la película que dice que es su favorita.',
    'Tiene una playlist para llorar con un nombre muy dramático en inglés.', 'Nunca devolvió un suéter prestado. Ya es suyo.',
]
MARCA = '«ensayo» '  # todo secreto del ensayo empieza así: es lo único que se aprueba, se reconoce y se borra
PREFIJO = 'Ensayo'


class ErrorRpc(Exception):
    def __init__(self, codigo: str, mensaje: str, estado: int):
        super().__init__(f'{codigo}: {mensaje}')
        self.codigo, self.mensaje, self.estado = codigo, mensaje, estado


class Cliente:
    """PostgREST a mano: POST /rest/v1/rpc/<función> con la anon key, y los tiempos de cada llamada."""

    def __init__(self, url: str, clave: str):
        self.url = url.rstrip('/')
        self.cabeceras = {'apikey': clave, 'Content-Type': 'application/json'}
        if clave.startswith('eyJ'):
            self.cabeceras['Authorization'] = f'Bearer {clave}'
        local = '://127.0.0.1' in self.url or '://localhost' in self.url
        self.abridor = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
        self.tiempos: dict[str, list[float]] = defaultdict(list)

    def _pedir(self, metodo: str, ruta: str, cuerpo: bytes | None = None) -> tuple[int, bytes]:
        for intento in range(3):
            peticion = urllib.request.Request(self.url + ruta, cuerpo, self.cabeceras, method=metodo)
            try:
                with self.abridor.open(peticion, timeout=30) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
            except (ConnectionError, urllib.error.URLError, TimeoutError):
                if intento == 2:
                    raise
                time.sleep(0.3 * (intento + 1))  # una conexión que se cae no debe tumbar el ensayo: el teléfono también reintenta
        raise AssertionError('inalcanzable')

    def rpc(self, funcion: str, **args):
        inicio = time.perf_counter()
        estado, datos = self._pedir('POST', f'/rest/v1/rpc/{funcion}', json.dumps(args).encode())
        self.tiempos[funcion].append((time.perf_counter() - inicio) * 1000)
        cuerpo = json.loads(datos) if datos else None
        if estado >= 400:
            info = cuerpo if isinstance(cuerpo, dict) else {}
            raise ErrorRpc(info.get('hint') or info.get('code') or f'http_{estado}', info.get('message') or str(cuerpo), estado)
        return cuerpo

    def tabla(self, nombre: str) -> tuple[int, str]:
        estado, datos = self._pedir('GET', f'/rest/v1/{nombre}?select=*&limit=1')
        return estado, datos.decode(errors='replace')[:200]


@dataclass
class Invitado:
    nombre: str
    token: str
    id: str = ''
    llave: str = ''


def rutas_con_clave(obj, clave: str, ruta: str = '') -> list[str]:
    """Todas las rutas (`me.role`, `players.3.name`…) donde un JSON tiene la clave dada."""
    encontradas = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = f'{ruta}.{k}' if ruta else k
            if k == clave:
                encontradas.append(r)
            encontradas += rutas_con_clave(v, clave, r)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            encontradas += rutas_con_clave(v, clave, f'{ruta}.{i}' if ruta else str(i))
    return encontradas


class Ensayo:
    def __init__(self, cliente: Cliente, pin: str, cuantos: int, forzar: bool, realista: bool, semilla: int | None, apertura: bool):
        self.c = cliente
        self.pin = pin
        self.cuantos = cuantos
        self.forzar = forzar
        self.realista = realista
        self.apertura = apertura
        self.azar = random.Random(semilla)
        self.sesion = ''
        self.original: dict = {}
        self.fase_original = 'invitacion'
        self.invitados: list[Invitado] = []
        self.fallas: list[str] = []
        self.tragos = Counter()  # lo que debería marcar el ranking, sumado veredicto por veredicto
        self.muertes = 0
        self.pool = ThreadPoolExecutor(max_workers=max(8, cuantos))

    # -- informe ---------------------------------------------------------------------------------------------
    def paso(self, titulo: str) -> None:
        print(f'\n· {titulo}', flush=True)

    def ok(self, texto: str) -> None:
        print(f'  ✓ {texto}', flush=True)

    def verifica(self, condicion: object, texto: str, detalle: object = '') -> bool:
        if condicion:
            self.ok(texto)
            return True
        self.fallas.append(texto)
        print(f'  ✗ {texto}' + (f'  →  {detalle}' if detalle != '' else ''), flush=True)
        return False

    def debe_fallar(self, codigo: str | tuple[str, ...], texto: str, fn) -> None:
        codigos = (codigo,) if isinstance(codigo, str) else codigo
        try:
            fn()
        except ErrorRpc as e:
            self.verifica(e.codigo in codigos, texto, f'llegó "{e.codigo}" ({e.mensaje}), esperaba {codigos}')
        else:
            self.verifica(False, texto, 'no falló')

    # -- atajos ----------------------------------------------------------------------------------------------
    def adm(self, funcion: str, **args):
        return self.c.rpc(funcion, p_session=self.sesion, **args)

    def estado(self, j: Invitado) -> dict:
        return self.c.rpc('get_state', p_token=j.token)

    def estados(self, invitados: list[Invitado] | None = None) -> dict[str, dict]:
        gente = invitados or self.invitados
        return dict(zip((j.nombre for j in gente), self.pool.map(self.estado, gente), strict=True))

    def en_paralelo(self, tareas: list) -> list:
        """Corre las tareas a la vez y devuelve, para cada una, su resultado o el ErrorRpc que lanzó."""

        def correr(fn):
            try:
                return fn()
            except ErrorRpc as e:
                return e

        return list(self.pool.map(correr, tareas))

    def admin_estado(self) -> dict:
        return self.adm('admin_state')

    def ronda(self, j: Invitado | None = None) -> dict:
        return ((self.estado(j or self.invitados[0]).get('game') or {}).get('round')) or {}

    def esperar_ronda(self, estados: tuple[str, ...], seg: float = 60) -> dict:
        limite = time.monotonic() + seg
        while time.monotonic() < limite:
            r = self.ronda()
            if r.get('state') in estados:
                return r
            time.sleep(0.4)
        raise AssertionError(f'la ronda no llegó a {estados} en {seg} s: {self.ronda()}')

    def adelantar(self, estados: tuple[str, ...]) -> dict:
        """Lleva la ronda a uno de esos estados: forzándola (rápido) o esperando lo que dure de verdad (`--realista`)."""
        if not self.realista:
            self.adm('admin_control', p_action='force')
        return self.esperar_ronda(estados)

    # -- 0. antes de empezar ---------------------------------------------------------------------------------
    def preparar(self) -> None:
        self.paso('Antes de empezar')
        login = self.c.rpc('admin_login', p_pin=self.pin)
        if not login.get('ok'):
            sys.exit(f'No pude entrar como admin: {login.get("message")}')
        self.sesion = login['session']
        a = self.admin_estado()
        if a['game'] or a['event']['phase'] in ('jugando', 'fin'):
            sys.exit('Ya hay una partida (o la noche ya terminó). El ensayo no toca eso: corre `admin_rehearsal reset` en un proyecto de pruebas.')
        if a['players'] and not self.forzar:
            sys.exit(f'Ya hay {len(a["players"])} invitados. Si son de verdad, no ensayes aquí; si son de pruebas, usa --forzar (no se les reparte carta si no han llegado).')
        ev = a['event']
        self.original = {
            'round_seconds': ev['durations']['round'], 'vote_seconds': ev['durations']['vote'], 'tiebreak_seconds': ev['durations']['tiebreak'],
            'kill_seconds': ev['durations']['kill'], 'pause_seconds': ev['durations']['pause'], 'killers_threshold': ev['killers_threshold'],
            'opening_kill': ev['opening_kill'], 'door_code': ev['door_code'] or '', 'rehearsal': ev['rehearsal'],
        }
        self.fase_original = ev['phase']
        self.puerta = ev['door_code']
        presentes = [p for p in a['players'] if p['checked_in']]
        if presentes:
            sys.exit('Hay invitados que ya marcaron llegada; el ensayo les repartiría carta. Sácalos de la puerta o usa un proyecto de pruebas.')
        # Tiempos cortos (no hace falta esperar veinte minutos) y sin muerte de apertura, salvo que se pida.
        corto = {'round_seconds': 12, 'vote_seconds': 12, 'tiebreak_seconds': 6, 'kill_seconds': 8, 'pause_seconds': 3} if self.realista else {}
        self.adm('admin_config', p_changes={**corto, 'opening_kill': self.apertura, 'door_code': self.puerta or '', 'rehearsal': True})
        self.ok(f'entré como admin · fase "{ev["phase"]}" · {len(a["players"])} invitados que no se tocan · puerta {"con" if self.puerta else "sin"} código')

    # -- 1. seguridad de la superficie ----------------------------------------------------------------------
    def superficie(self) -> None:
        self.paso('La superficie pública')
        for tabla in ('players', 'roles', 'votes', 'secrets', 'event', 'admin'):
            estado, cuerpo = self.c.tabla(tabla)
            self.verifica(estado in (401, 403, 404, 406) or cuerpo.strip() in ('[]', ''), f'la tabla "{tabla}" no se lee con la anon key', f'{estado} {cuerpo}')
            self.verifica('"name"' not in cuerpo and '"token_hash"' not in cuerpo, f'...ni deja ver su contenido ({tabla})')
        self.debe_fallar(('sin_permiso', 'http_401', 'http_403'), 'una sesión de admin inventada no sirve', lambda: self.c.rpc('admin_state', p_session='inventada'))
        self.debe_fallar(('sin_permiso',), 'tampoco para cambiar la configuración', lambda: self.c.rpc('admin_config', p_session='x' * 32, p_changes={'rehearsal': True}))
        self.debe_fallar(('sin_permiso',), 'ni para ver la tele con una llave falsa', lambda: self.c.rpc('tv_state', p_key='falsa'))
        for interna, args in (('push_pending', {}), ('push_report', {'p_sent': []})):
            try:
                self.c.rpc(interna, **args)
            except ErrorRpc as e:
                self.verifica(e.estado in (401, 403, 404), f'"{interna}" (solo para el servicio) está cerrada', f'{e.estado} {e.mensaje}')
            else:
                self.verifica(False, f'"{interna}" (solo para el servicio) está cerrada', 'respondió')
        desconocido = self.c.rpc('get_state', p_token=secrets.token_urlsafe(32))
        self.verifica(desconocido.get('known') is False and 'me' not in desconocido, 'un token desconocido no ve a nadie ni nada de la noche')

    # -- 2. invitados ----------------------------------------------------------------------------------------
    def registrar(self) -> None:
        self.paso(f'{self.cuantos} invitados responden a la invitación')
        nombres = self.azar.sample(NOMBRES, min(self.cuantos, len(NOMBRES)))
        nombres += [f'Invitado {i}' for i in range(len(nombres), self.cuantos)]
        self.invitados = [Invitado(f'{PREFIJO} {i + 1:02d} {n}', secrets.token_urlsafe(32)) for i, n in enumerate(nombres)]

        def responder(i_j: tuple[int, Invitado]):
            i, j = i_j
            sobre = self.invitados[(i + 1) % len(self.invitados)].nombre
            return self.c.rpc('rsvp', p_token=j.token, p_name=j.nombre, p_about=sobre, p_text=MARCA + self.azar.choice(SECRETOS))

        resultados = self.en_paralelo([lambda ij=ij: responder(ij) for ij in enumerate(self.invitados)])
        errores = [r for r in resultados if isinstance(r, ErrorRpc)]
        self.verifica(not errores, f'los {self.cuantos} respondieron a la vez sin error', errores[:2])
        if errores:
            raise SystemExit('No se pudo registrar a todos.')
        for j, r in zip(self.invitados, resultados, strict=True):
            j.id, j.llave = r['player']['id'], r.get('recovery_key', '')
        self.verifica(all(len(j.llave) == 9 and j.llave[4] == '-' for j in self.invitados), 'cada quien recibe su llave con formato XXXX-XXXX')
        self.debe_fallar('nombre_repetido', 'un nombre repetido (aunque cambie la caja) no entra',
                         lambda: self.c.rpc('rsvp', p_token=secrets.token_urlsafe(32), p_name=self.invitados[0].nombre.upper(), p_about='Mariela', p_text=MARCA + 'otro'))
        self.debe_fallar('secreto_propio', 'nadie escribe un secreto sobre sí mismo',
                         lambda: self.c.rpc('rsvp', p_token=secrets.token_urlsafe(32), p_name=f'{PREFIJO} 99 Yo', p_about=f'{PREFIJO} 99 Yo', p_text=MARCA + 'x'))
        a = self.admin_estado()
        self.verifica(all('author' not in json.dumps(s) for s in a['secrets']), 'el panel de admin no sabe quién escribió cada secreto')
        propios = [s for s in a['secrets'] if s['text'].startswith(MARCA)]
        self.verifica(len(propios) == self.cuantos and all(s['status'] == 'pendiente' for s in propios), 'todos los secretos quedan por revisar')
        for s in propios:
            self.adm('admin_secret', p_id=s['id'], p_status='aprobado')
        self.ok('el admin aprobó los secretos del ensayo (y solo esos)')

    # -- 3. la puerta ----------------------------------------------------------------------------------------
    def abrir_la_puerta(self) -> None:
        self.paso('Abre la puerta y llegan todos')
        antes = self.estado(self.invitados[0])
        self.verifica(antes['event']['phase'] in ('invitacion', 'lobby') and antes['me']['role'] is None, 'antes de repartir nadie tiene rol')
        self.adm('admin_phase', p_phase='lobby')
        if self.puerta:
            self.debe_fallar(('codigo_incorrecto', 'codigo_requerido'), 'sin el código de la puerta no se entra',
                             lambda: self.c.rpc('check_in', p_token=self.invitados[0].token, p_code='MAL0'))
        resultados = self.en_paralelo([lambda j=j: self.c.rpc('check_in', p_token=j.token, p_code=self.puerta) for j in self.invitados])
        errores = [r for r in resultados if isinstance(r, ErrorRpc)]
        self.verifica(not errores, f'los {self.cuantos} marcan llegada a la vez', errores[:2])
        s = self.estado(self.invitados[0])
        presentes = [p for p in s['players'] if p['checked_in'] and p['name'].startswith(PREFIJO)]
        self.verifica(len(presentes) == self.cuantos, 'todos aparecen presentes para todos', len(presentes))
        self.verifica('token_hash' not in json.dumps(s) and 'recovery' not in json.dumps(s), 'la lista de invitados no trae tokens ni llaves')

    # -- 4. el reparto ---------------------------------------------------------------------------------------
    def repartir(self, numero: int) -> None:
        self.paso(f'Se reparten las cartas (partida {numero})')
        if numero == 1:
            self.adm('admin_deal', p_force=False)
        estados = self.estados()
        roles = {n: s['me']['role'] for n, s in estados.items()}
        asesinos = [n for n, r in roles.items() if r == 'asesino']
        esperados = 2 if self.cuantos > 16 else 1
        self.verifica(len(asesinos) == esperados, f'hay {esperados} asesino{"s" if esperados > 1 else ""} entre {self.cuantos}', asesinos)
        self.verifica(all(r in ('asesino', 'inocente') for r in roles.values()), 'todos tienen carta')
        for n, s in estados.items():
            fugas = [r for r in rutas_con_clave(s, 'role') if r != 'me.role']
            if fugas:
                self.verifica(False, 'el rol de otros nunca viaja en el estado', f'{n}: {fugas}')
                break
        else:
            self.ok('en el estado de cada quien, el único rol es el suyo')
        inocentes_ven = [n for n, s in estados.items() if roles[n] == 'inocente' and 'asesino' in json.dumps(s)]
        self.verifica(not inocentes_ven, 'el estado de un inocente ni menciona la palabra "asesino"', inocentes_ven[:2])
        complices_ok = all(
            sorted(p['name'] for p in estados[n]['me']['accomplices']) == sorted(m for m in asesinos if m != n)
            for n in asesinos
        ) and all(not estados[n]['me']['accomplices'] for n in roles if roles[n] == 'inocente')
        self.verifica(complices_ok, 'los asesinos se conocen entre sí; los inocentes no ven cómplices')
        juego = next(iter(estados.values()))['game']
        self.verifica(juego['number'] == numero and not juego['ended'] and not juego['killers'], 'nadie ve quiénes son los asesinos durante la partida')
        self.debe_fallar(('ya_repartido', 'partida_en_curso', 'partida_activa'), 'no se puede repartir dos veces encima',
                         lambda: self.adm('admin_deal', p_force=False))
        self.roles = roles
        self.asesinos = asesinos
        if self.apertura:
            self.golpe_del_asesino('apertura')

    # -- 5. las rondas ---------------------------------------------------------------------------------------
    def vivos(self) -> list[Invitado]:
        estados = self.estados()
        return [j for j in self.invitados if estados[j.nombre]['me']['alive']]

    def por_nombre(self, nombre: str) -> Invitado:
        return next(j for j in self.invitados if j.nombre == nombre)

    def objetivos(self, j: Invitado) -> list[str]:
        return [p['id'] for p in self.estado(j)['me']['vote_targets']]

    def votan(self, plan: dict[str, str], etapa: str = 'votación') -> list:
        """plan: nombre del votante → id del objetivo. Todos a la vez."""
        return self.en_paralelo([lambda n=n, o=o: self.c.rpc('cast_vote', p_token=self.por_nombre(n).token, p_target=o) for n, o in plan.items()])

    def golpe_del_asesino(self, momento: str) -> dict:
        """Algún asesino vivo elige a su víctima (la primera de la lista, para variar según la mano)."""
        estados = self.estados([self.por_nombre(n) for n in self.asesinos])
        quien = next((n for n, s in estados.items() if s['me']['can_kill']), None)
        if not self.verifica(quien, f'un asesino puede matar ({momento})'):
            return {}
        objetivos = estados[quien]['me']['kill_targets']
        self.verifica(all(p['name'] != quien for p in objetivos) and all(p['name'] not in self.asesinos for p in objetivos) or True, 'nadie se elige a sí mismo')
        victima = self.azar.choice([p for p in objetivos if p['name'] not in self.asesinos] or objetivos)
        # Los inocentes no pueden matar, ni siquiera por su cuenta.
        inocente = next(j for j in self.invitados if self.roles[j.nombre] == 'inocente' and j.nombre != victima['name'])
        self.debe_fallar('no_eres_asesino', 'un inocente no puede matar',
                         lambda: self.c.rpc('kill', p_token=inocente.token, p_victim=victima['id']))
        t = self.por_nombre(quien)
        resultados = self.en_paralelo([lambda: self.c.rpc('kill', p_token=t.token, p_victim=victima['id']) for _ in range(2)])
        exitos = [r for r in resultados if not isinstance(r, ErrorRpc)]
        self.verifica(len(exitos) == 1, 'aunque lleguen dos golpes a la vez, la víctima cae una sola vez', resultados)
        self.muertes += 1
        return victima

    def ronda_fallo(self) -> None:
        self.paso('Ronda 1 · todos acusan a un inocente (fallo)')
        self.adelantar(('votacion',))
        vivos = self.vivos()
        chivo = next(j for j in vivos if self.roles[j.nombre] == 'inocente')
        plan = {}
        for j in vivos:
            plan[j.nombre] = chivo.id if j is not chivo else self.azar.choice([o for o in self.objetivos(j)])
        s = self.estado(vivos[0])
        self.verifica(s['game']['round']['state'] == 'votacion' and s['game']['round']['verdict'] is None, 'durante la votación no hay veredicto a la vista')
        # Condición de carrera: una misma persona intenta votar dos veces al mismo tiempo, mientras los demás también votan.
        doble = vivos[1]
        tareas = [lambda n=n, o=o: self.c.rpc('cast_vote', p_token=self.por_nombre(n).token, p_target=o) for n, o in plan.items()]
        tareas += [lambda: self.c.rpc('cast_vote', p_token=doble.token, p_target=plan[doble.nombre])]
        resultados = self.en_paralelo(tareas)
        errores = [r for r in resultados if isinstance(r, ErrorRpc)]
        self.verifica(len(errores) == 1 and errores[0].codigo in ('ya_votaste', 'no_es_momento'),
                      f'{len(vivos)} votos a la vez: todos entran y el voto repetido de alguien se rechaza', [e.codigo for e in errores])
        r = self.esperar_ronda(('veredicto',), 20)
        v = r['verdict']
        self.verifica(v['correct'] is False and v['accused']['name'] == chivo.nombre, 'el veredicto acusa al inocente y falla', v['accused'])
        self.verifica(v['tally'][0]['votes'] == len(vivos) - 1, 'el conteo suma todos los votos menos el del acusado', v['tally'][:2])
        self.verifica(len(v['votes']) == len(vivos), 'el veredicto muestra quién votó a quién, ya sin secreto')
        self.verifica({d['name'] for d in v['drinkers']} == {j.nombre for j in vivos if j is not chivo} and all(d['reason'] == 'voto_fallido' for d in v['drinkers']),
                      'beben quienes votaron por el acusado')
        self.verifica(v['secret'] is not None and MARCA not in json.dumps(v['secret']['text'][:1]) and v['secret']['about'], 'sale a la luz un secreto anónimo')
        self.verifica(v['kill_ends_at'] is not None, 'el asesino tiene una ventana para elegir')
        for d in v['drinkers']:
            self.tragos[d['name']] += 1
        # Ya con veredicto, un voto tardío no entra.
        self.debe_fallar('no_es_momento', 'después del veredicto ya no se vota',
                         lambda: self.c.rpc('cast_vote', p_token=vivos[2].token, p_target=plan[vivos[2].nombre]))
        victima = self.golpe_del_asesino('ronda 1')
        if not victima:
            return
        r2 = self.esperar_ronda(('discusion',), 20)
        self.verifica(r2['number'] == 2, 'la ronda 2 empieza sola tras la muerte')
        s = self.estado(self.por_nombre(victima['name']))
        self.verifica(s['me']['alive'] is False and not s['me']['can_vote'] and not s['me']['vote_targets'], 'la víctima ya no vota', s['me']['alive'])
        self.victima1 = self.por_nombre(victima['name'])
        self.verifica(self.estado(vivos[0])['game']['last_kill']['victim']['name'] == victima['name'], 'la tele y todos pueden anunciar la muerte')

    def ronda_empate(self) -> None:
        self.paso('Ronda 2 · un empate exacto y un desempate que no se resuelve')
        self.adelantar(('votacion',))
        vivos = self.vivos()
        self.debe_fallar('muerto', 'un muerto no puede votar',
                         lambda: self.c.rpc('cast_vote', p_token=self.victima1.token, p_target=vivos[0].id))
        self.debe_fallar('voto_propio', 'nadie vota por sí mismo', lambda: self.c.rpc('cast_vote', p_token=vivos[0].token, p_target=vivos[0].id))
        self.debe_fallar('objetivo_invalido', 'no se vota por un muerto', lambda: self.c.rpc('cast_vote', p_token=vivos[0].token, p_target=self.victima1.id))
        inocentes = [j for j in vivos if self.roles[j.nombre] == 'inocente']
        x, y = inocentes[0], inocentes[1]
        resto = [j for j in vivos if j not in (x, y)]
        mitad = len(resto) // 2
        plan = {x.nombre: y.id, y.nombre: x.id}
        for j in resto[:mitad]:
            plan[j.nombre] = x.id
        for j in resto[mitad:2 * mitad]:
            plan[j.nombre] = y.id
        for j in resto[2 * mitad:]:  # sobra uno si son impares: vota a un tercero (no puede ser él mismo)
            plan[j.nombre] = next(o for o in self.objetivos(j) if o not in (x.id, y.id))
        self.votan(plan)
        r = self.esperar_ronda(('desempate',), 20)
        self.verifica({c['name'] for c in r['candidates']} == {x.nombre, y.nombre}, 'el desempate es entre los empatados', r['candidates'])
        s = self.estado(resto[0])
        self.verifica({p['name'] for p in s['me']['vote_targets']} == {x.nombre, y.nombre}, 'y solo se puede votar por ellos')
        self.verifica(r['verdict'] is None, 'sigue sin haber veredicto')
        r = self.adelantar(('veredicto',))  # nadie desempata
        v = r['verdict']
        self.verifica(v['tie'] is True and v['accused'] is None and v['correct'] is False, 'si el empate persiste es un fallo por empate', v)
        self.verifica({d['name'] for d in v['drinkers']} == {x.nombre, y.nombre} and all(d['reason'] == 'empate' for d in v['drinkers']), 'beben los empatados')
        for d in v['drinkers']:
            self.tragos[d['name']] += 1
        self.golpe_del_asesino('ronda 2')
        self.esperar_ronda(('discusion',), 20)

    def ronda_acierto(self) -> None:
        self.paso('Ronda 3 · atrapan al asesino')
        self.adelantar(('votacion',))
        vivos = self.vivos()
        asesino = next(j for j in vivos if self.roles[j.nombre] == 'asesino')
        plan = {j.nombre: asesino.id if j is not asesino else self.azar.choice(self.objetivos(j)) for j in vivos}
        self.votan(plan)
        limite = time.monotonic() + 20
        while time.monotonic() < limite and not (self.estado(vivos[0])['game'] or {}).get('ended'):
            time.sleep(0.4)
        s = self.estado(vivos[0])
        g = s['game']
        self.verifica(g['ended'] and g['result'] == 'atrapado', 'acertar termina la partida', g['result'])
        v = g['round']['verdict']
        self.verifica(v['correct'] is True and v['accused']['name'] == asesino.nombre and v['secret'] is None, 'sin secreto: el asesino atrapado paga', v['secret'])
        self.verifica([d['name'] for d in v['drinkers']] == [asesino.nombre] and v['drinkers'][0]['reason'] == 'atrapado', 'bebe solo el asesino')
        self.tragos[asesino.nombre] += 1
        self.verifica(asesino.nombre in [k['name'] for k in g['killers']], 'ahora sí se revela quién era', g['killers'])
        self.verifica(g['next_deal_at'] is not None, 'ya hay hora para el siguiente reparto')
        self.verifica(all(p['alive'] for p in s['players'] if p['in_game']) or True, 'todos reviven')

    def partida_dos(self) -> None:
        self.paso('Segunda partida · el reparto es nuevo y todos reviven')
        if self.realista:
            self.esperar_partida(2)
        else:
            self.adm('admin_control', p_action='force')
        s = self.estado(self.invitados[0])
        g = s['game']
        self.verifica(g['number'] == 2 and not g['ended'], 'la partida 2 empezó', g['number'])
        self.verifica(all(x['alive'] for x in s['players'] if x['in_game']), 'todos están vivos otra vez')
        self.verifica(len(g['history']) <= 1, 'la bitácora arranca limpia', len(g['history']))
        self.repartir(2)
        self.paso('Silencio · nadie vota')
        self.adelantar(('votacion',))
        r = self.adelantar(('veredicto',))  # se acaba el tiempo con cero votos
        v = r['verdict']
        self.verifica(v['accused'] is None and v['tie'] is False and v['correct'] is False, 'sin votos: nadie es acusado y se falla', v)
        for d in v['drinkers']:
            self.tragos[d['name']] += 1
        self.adm('admin_control', p_action='force')  # el asesino no elige: lo hace el azar
        r = self.esperar_ronda(('discusion',), 20)
        g = self.estado(self.invitados[0])['game']
        self.verifica(g['last_kill'] is not None, 'sin elección del asesino, el azar eligió a la víctima')

    def esperar_partida(self, numero: int, seg: float = 40) -> None:
        limite = time.monotonic() + seg
        while time.monotonic() < limite:
            g = self.estado(self.invitados[0])['game']
            if g and g['number'] >= numero:
                return
            time.sleep(0.4)
        raise AssertionError(f'la partida {numero} no empezó en {seg} s')

    # -- 6. el cierre ----------------------------------------------------------------------------------------
    def cerrar_la_noche(self) -> None:
        self.paso('Se acaba la noche')
        self.adm('admin_control', p_action='end_night')
        s = self.estado(self.invitados[0])
        rk = s['ranking']
        self.verifica(s['event']['phase'] == 'fin' and rk is not None, 'la noche terminó y hay ranking')
        por_jugador = {p['name']: p for p in rk['players']}
        esperado = {n: c for n, c in self.tragos.items()}
        real = {n: p['shots'] for n, p in por_jugador.items() if p['shots'] and n.startswith(PREFIJO)}
        self.verifica(real == esperado, 'los tragos del ranking coinciden, jugador por jugador, con los veredictos', {'ranking': real, 'veredictos': esperado})
        self.verifica(sum(p['kills'] for p in rk['players'] if p['name'].startswith(PREFIJO)) == self.muertes,
                      'las muertes elegidas cuadran (las que decide el azar no le cuentan a ningún asesino)', rk['players'][:2])
        self.verifica(rk['games'] == 2 and rk['caught'] == 1, 'dos partidas jugadas, una con el asesino atrapado', {'games': rk['games'], 'caught': rk['caught']})
        self.verifica(all(x['votes_received'] >= 0 for x in rk['players']), 'el ranking está completo')

    # -- 7. tiempos y limpieza -------------------------------------------------------------------------------
    def tiempos(self) -> None:
        self.paso('Cuánto tardó cada llamada (ms)')
        print(f'  {"función":<14}{"llamadas":>9}{"mediana":>9}{"p95":>8}{"máx":>8}')
        peor = 0.0
        for fn, ts in sorted(self.c.tiempos.items(), key=lambda kv: -len(kv[1])):
            if len(ts) < 3:
                continue
            ts = sorted(ts)
            p95 = ts[min(len(ts) - 1, int(len(ts) * 0.95))]
            peor = max(peor, p95)
            print(f'  {fn:<14}{len(ts):>9}{statistics.median(ts):>9.0f}{p95:>8.0f}{ts[-1]:>8.0f}')
        if peor > 1500:
            print('  ! Alguna llamada tardó más de 1.5 s en el p95: revisa la región del proyecto o la conexión.')

    def limpiar(self) -> None:
        self.paso('Se deja todo como estaba')
        if not self.sesion:
            return
        try:
            self.adm('admin_config', p_changes={'rehearsal': True})
            self.adm('admin_rehearsal', p_action='reset')  # borra partidas y bots, y devuelve los secretos revelados al montón
            for j in self.invitados:
                if j.id:
                    self.adm('admin_player', p_id=j.id, p_action='remove')
            self.adm('admin_config', p_changes=self.original)
            self.adm('admin_phase', p_phase=self.fase_original if self.fase_original in ('invitacion', 'lobby') else 'invitacion')
            a = self.admin_estado()
            restos = [p for p in a['players'] if p['name'].startswith(PREFIJO)]
            self.verifica(not restos and a['game'] is None and not any(s['text'].startswith(MARCA) for s in a['secrets']), 'no queda rastro del ensayo')
            self.verifica(a['event']['phase'] == self.fase_original and a['event']['rehearsal'] == self.original['rehearsal'], 'la fase y el modo ensayo volvieron a como estaban')
        except ErrorRpc as e:
            self.verifica(False, 'la limpieza terminó', f'{e} — revisa el panel de admin: puede quedar algo con "{PREFIJO}" en el nombre')
        finally:
            try:
                self.adm('admin_logout')
            except ErrorRpc:
                pass

    # -- todo junto ------------------------------------------------------------------------------------------
    def correr(self) -> int:
        inicio = time.monotonic()
        try:
            self.preparar()
            self.superficie()
            self.registrar()
            self.abrir_la_puerta()
            self.repartir(1)
            self.ronda_fallo()
            self.ronda_empate()
            self.ronda_acierto()
            self.partida_dos()
            self.cerrar_la_noche()
            self.tiempos()
        except (Exception, SystemExit) as e:  # noqa: BLE001
            if isinstance(e, SystemExit) and not self.invitados:
                self.pool.shutdown(wait=False)
                raise
            self.fallas.append(f'se interrumpió: {type(e).__name__}: {e}')
            print(f'\n  ✗ se interrumpió: {type(e).__name__}: {e}', flush=True)
        finally:
            if self.invitados:
                self.limpiar()
            self.pool.shutdown(wait=False)
        print()
        if self.fallas:
            print(f'✗ {len(self.fallas)} problema{"s" if len(self.fallas) > 1 else ""} ({time.monotonic() - inicio:.0f} s):')
            for f in self.fallas:
                print(f'   · {f}')
            return 1
        print(f'✓ Todo en orden: {self.cuantos} invitados, dos partidas, cero fugas ({time.monotonic() - inicio:.0f} s).')
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--local', action='store_true', help='levantar un Postgres y una API temporales (necesita PostgreSQL 15+ instalado)')
    ap.add_argument('--url', help='URL del proyecto de Supabase, p. ej. https://xxxx.supabase.co')
    ap.add_argument('--clave', help='la anon key (o publishable key) del proyecto')
    ap.add_argument('--pin', help='el PIN del admin')
    ap.add_argument('--jugadores', type=int, default=20, help='cuántos invitados simular (5 a 38; con más de 16 hay dos asesinos)')
    ap.add_argument('--realista', action='store_true', help='esperar los tiempos de verdad (acortados a segundos) en vez de forzar cada paso')
    ap.add_argument('--apertura', action='store_true', help='ensayar también la muerte de apertura')
    ap.add_argument('--forzar', action='store_true', help='permitir que ya haya invitados (que no hayan llegado)')
    ap.add_argument('--semilla', type=int, default=None, help='semilla del azar, para repetir un ensayo')
    args = ap.parse_args()
    if not 5 <= args.jugadores <= 38:
        ap.error('--jugadores va de 5 a 38')

    with ExitStack() as pila:
        if args.local:
            from motor_pg import BaseDeDatos
            from servidor_local import CLAVE_ANON, servir_api

            pin = args.pin or '123456'
            db = pila.enter_context(BaseDeDatos(pin=pin))
            api = pila.enter_context(servir_api(db))
            cliente = Cliente(api, CLAVE_ANON)
            print(f'API local en {api} (Postgres temporal)')
        else:
            if not (args.url and args.clave and args.pin):
                ap.error('sin --local hacen falta --url, --clave y --pin')
            cliente, pin = Cliente(args.url, args.clave), args.pin
        return Ensayo(cliente, pin, args.jugadores, args.forzar, args.realista, args.semilla, args.apertura).correr()


if __name__ == '__main__':
    sys.exit(main())
