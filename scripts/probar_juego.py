"""Pruebas de interfaz de la noche: teléfonos, tele, admin y simulador, contra el mismo motor que usará la fiesta.

    python scripts/probar_juego.py                 # los dos entornos (compila la app dos veces)
    python scripts/probar_juego.py --modo supabase # el build de producción contra el servidor local (Postgres real)
    python scripts/probar_juego.py --modo demo     # el Postgres dentro del navegador
    python scripts/probar_juego.py -k carta -x     # solo las pruebas que contienen "carta", y para en la primera falla

En `supabase` cada teléfono, la tele y el admin son pestañas distintas hablando con un mismo servidor, como en la fiesta.
La noche se arma con la API (rápido) y se recorre con la interfaz (lo que importa); el reloj del servidor se adelanta con
`clock_offset`, así que una noche entera corre en segundos.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time

from playwright.sync_api import expect

from banco import SUPABASE_FALSO, Banco, Sesion, correr, esperar, prueba, texto
from comun import RAIZ
from motor_pg import ErrorApi
from probar_motor import Jugador, Noche, rutas_con_clave

expect.set_options(timeout=10_000)

TIEMPO = 15_000  # ms: lo que espera cualquier elemento antes de darse por perdido
CAMPO_LLAVE = re.compile(r'^[A-Z0-9]{4}-[A-Z0-9]{4}$')


# ------------------------------------------------------------------------------------------------- utilidades
def telefono(banco: Banco, jugador: Jugador | None = None, *, perfil: str = 'Pixel 7', realtime: bool = False, esperar_a: str = '.juego', **opciones) -> Sesion:
    """Un teléfono con la sesión de `jugador` (su token en localStorage, como si ya hubiera respondido desde ahí)."""
    s = banco.sesion(perfil, realtime=realtime, **opciones)
    s.pagina.set_default_timeout(TIEMPO)
    if jugador is not None:
        s.pagina.context.add_init_script(f"try {{ localStorage.setItem('mariela.token', {json.dumps(jugador.token)}) }} catch (e) {{}}")
    s.ir('', esperar_a=esperar_a)
    return s


def tele(banco: Banco, n: Noche, llave: str | None = None) -> Sesion:
    llave = llave or n.adm('admin_state')['event']['tv_key']
    s = banco.sesion('tele')
    s.pagina.set_default_timeout(TIEMPO)
    s.ir(f'tv#k={llave}', esperar_a='.tv')
    return s


def panel(banco: Banco, n: Noche, pestana: str | None = None) -> Sesion:
    """El panel de admin, ya adentro con el PIN."""
    s = banco.sesion('escritorio')
    s.pagina.set_default_timeout(TIEMPO)
    s.ir('admin', esperar_a='#pin')
    s.pagina.fill('#pin', banco.pin)
    s.pagina.keyboard.press('Enter')
    s.pagina.wait_for_selector('.admin')
    if pestana:
        pestana_admin(s, pestana)
    return s


def pestana_admin(s: Sesion, nombre: str) -> None:
    s.pagina.locator('.ad-pestanas button', has_text=re.compile(f'^{nombre}')).click()
    expect(s.pagina.locator('.ad-pestanas button[aria-current="page"]')).to_contain_text(nombre)


def pestana_juego(s: Sesion, nombre: str) -> None:
    s.tocar(f'.j-pestanas button:has-text("{nombre}")')
    expect(s.pagina.locator('.j-pestanas button[aria-current="page"]')).to_contain_text(nombre)


def ver(s: Sesion, selector: str, contiene: str | re.Pattern | None = None, seg: float = 10):
    """Espera (con reintentos) a que el elemento se vea, y opcionalmente a que diga algo."""
    lugar = s.pagina.locator(selector).first
    if contiene is None:
        expect(lugar).to_be_visible(timeout=seg * 1000)
    else:
        expect(lugar).to_contain_text(contiene, timeout=seg * 1000)
    return lugar


def hay(s: Sesion, selector: str, contiene: str | re.Pattern, seg: float = 10) -> None:
    """Entre todos los elementos que coinciden con el selector, alguno dice esto."""
    expect(s.pagina.locator(selector, has_text=contiene).first).to_be_visible(timeout=seg * 1000)


def guardar_ajustes(s: Sesion) -> None:
    """Guarda en Ajustes y espera a que el servidor conteste (el botón vuelve a "Todo guardado")."""
    s.tocar('#ad-guardar')
    expect(s.pagina.locator('#ad-guardar')).to_have_text('Todo guardado', timeout=8000)


def no_hay(s: Sesion, selector: str, seg: float = 10) -> None:
    expect(s.pagina.locator(selector)).to_have_count(0, timeout=seg * 1000)


def contar(banco: Banco, tabla: str, donde: str = 'true') -> int:
    return banco.db.valor(f'select count(*) from app.{tabla} where {donde}')


def ronda_actual(banco: Banco) -> dict:
    return banco.db.fila(
        """select r.* from app.rounds r where r.game_id = (select id from app.games order by number desc limit 1)
            order by r.number desc limit 1""")


def respuestas(s: Sesion, fn: str | None = None) -> list[dict]:
    """Lo que el servidor le respondió a esta pestaña (el vigía las junta en `window.__rpc`)."""
    return [r for r in s.pagina.evaluate('window.__rpc') if fn is None or r['fn'] == fn]


PROHIBIDAS = ('token_hash', 'recovery_hash', 'recovery_key', 'tv_key', 'push_subscription', 'author', 'service_role', '"pin', 'password')


def sin_filtraciones(banco: Banco, s: Sesion, n: Noche, yo: Jugador | None) -> int:
    """Revisa TODO lo que el servidor le contestó a esta pestaña: que no traiga lo que no le toca ver. Devuelve cuántas respuestas revisó."""
    funciones = ('get_state',) if yo else ('tv_state',)
    revisadas = respuestas(s)
    assert revisadas, 'la pestaña no recibió ninguna respuesta'
    llamadas = {r['fn'] for r in revisadas}
    assert not {f for f in llamadas if f.startswith('admin_')}, f'un teléfono o la tele no debe llamar al admin: {llamadas}'
    ajenos = [f['text'] for f in banco.db.filas('select text from app.secrets where author_id is distinct from %s', yo.id if yo else None)]
    revelados = {f['text'] for f in banco.db.filas("select text from app.secrets where status = 'revelado'")}
    direccion = banco.db.valor('select address from app.event')
    revisadas = [r for r in revisadas if r['fn'] in funciones]
    for r in revisadas:
        assert r['estado'] == 200, r
        crudo = r['cuerpo']
        datos = json.loads(crudo)
        for cosa in PROHIBIDAS + (('"door_code":',) if yo else ()):  # el código de la puerta solo lo lee la tele
            assert cosa not in crudo, f'la respuesta trae {cosa!r}'
        roles = rutas_con_clave(datos, 'role')
        assert set(roles) <= ({'me.role'} if yo else set()), f'roles a la vista: {roles}'
        juego = datos.get('game') or {}
        estado = (juego.get('round') or {}).get('state')
        if estado in ('votacion', 'desempate'):  # la bitácora sí trae los veredictos de las rondas pasadas; la ronda en curso, nada
            ronda = json.dumps(juego['round'])
            assert '"tally"' not in ronda and '"voter"' not in ronda and '"verdict": null' in ronda or '"verdict"' not in ronda, 'los votos se ven antes del veredicto'
        if yo and not juego.get('ended') and (datos.get('me') or {}).get('role') == 'inocente':
            assert 'asesino' not in crudo, 'el teléfono de un inocente recibió la palabra "asesino": algo delata quién es'
        if not juego.get('ended'):
            assert not juego.get('killers'), 'los asesinos se revelan hasta que termina la partida'
            if not yo:
                assert 'accomplices' not in crudo
        for t in ajenos:
            assert t not in crudo or t in revelados, f'un secreto sin revelar llegó al cliente: {t!r}'
        if direccion and not datos.get('event', {}).get('address_revealed'):
            assert direccion not in crudo, 'la dirección llegó antes de su hora'
    return len(revisadas)


def mantener(s: Sesion, selector: str = '#mi-carta') -> None:
    caja = s.pagina.locator(selector).bounding_box()
    assert caja, f'{selector} no está en pantalla'
    s.pagina.mouse.move(caja['x'] + caja['width'] / 2, caja['y'] + caja['height'] / 2)
    s.pagina.mouse.down()


def cara_montada(s: Sesion) -> int:
    return s.pagina.locator('#mi-carta .cm-frente svg').count()


def elegir_ficha(s: Sesion, nombre: str, verbo: str) -> None:
    s.tocar(f'.j-ficha[aria-label="{verbo} {nombre}"]')
    expect(s.pagina.locator(f'.j-ficha[aria-label="{verbo} {nombre}"]')).to_have_attribute('aria-pressed', 'true')


def hoja_abierta(s: Sesion):
    return s.pagina.locator('.hoja-capa.abierta .hoja')


def votar_por_ui(s: Sesion, nombre: str, sellado: bool = True) -> None:
    """Elegir, confirmar y ver el voto sellado. Con bots la ronda puede cerrarse antes de que se pinte el sello: ahí `sellado=False`."""
    elegir_ficha(s, nombre, 'Votar por')
    s.tocar('#j-votar')
    expect(hoja_abierta(s)).to_contain_text(f'¿Votas por {nombre}?')
    s.tocar('#j-confirmar-voto')
    if sellado:
        ver(s, '.j-sellado .j-titulo', 'Voto sellado.')
    no_hay(s, '.hoja-capa.abierta', seg=10)  # la hoja de confirmación se cierra al votar (o al fallar y avisar)


def golpear_por_ui(s: Sesion, nombre: str) -> None:
    elegir_ficha(s, nombre, 'Elegir a')
    s.tocar('#j-elegir-victima')
    expect(hoja_abierta(s)).to_contain_text(f'¿Será {nombre}?')
    s.tocar('#j-confirmar-victima')
    no_hay(s, '.hoja-capa.abierta', seg=10)


def revelacion_completa(s: Sesion, acierto: bool, seg: float = 14) -> None:
    """La revelación del veredicto entra por partes: la última es el secreto, y en un acierto (que no revela ninguno), quién bebe."""
    ver(s, '.rev-beb.on' if acierto else '.rev-sec.on', seg=seg)


# ============================================================================================ ANTESALA Y PUERTA
@prueba('supabase')
def antesala_llegada_y_codigo(banco: Banco) -> None:
    """La puerta con código: sin él no se entra; con él, el teléfono y la tele se enteran."""
    n = Noche(banco.db, 5, presentes=False, repartir=False)
    n.config(door_code='luna')
    j1, j2, j3 = n.jugadores[:3]

    s = telefono(banco, j1)
    ver(s, '.j-etiqueta', 'Antesala')
    ver(s, '.j-titulo', 'Ya estás dentro, Jugador 01.')
    boton = s.pagina.locator('#j-estoy-aqui')
    expect(boton).to_be_disabled()  # sin código no hay botón
    s.pagina.fill('#codigo-puerta', 'XXXX')
    s.tocar('#j-estoy-aqui')
    ver(s, '#codigo-error', 'código')
    assert banco.db.valor('select checked_in from app.players where id = %s', j1.id) is False
    s.pagina.fill('#codigo-puerta', 'LUNA')
    s.tocar('#j-estoy-aqui')
    ver(s, '.j-contador', '1 de 5 ya llegaron')
    expect(s.pagina.locator('.j-nombres li.yo')).to_have_text('Jugador 01')
    assert banco.db.valor('select checked_in from app.players where id = %s', j1.id) is True

    t = tele(banco, n)
    ver(t, '.tv-codigo b', 'LUNA')
    ver(t, '.tv-llegados', '1 de 5')
    ver(t, '.tv-nombres li', 'Jugador 01')
    j2.llegar('LUNA')  # otro invitado cruza la puerta: la tele y el otro teléfono lo ven solos
    ver(t, '.tv-llegados', '2 de 5', seg=9)
    ver(t, '.tv-ultima', 'Jugador 02 acaba de llegar')
    ver(s, '.j-contador', '2 de 5 ya llegaron', seg=9)

    # Sin código, todos entran de un toque.
    n.config(door_code='')
    s3 = telefono(banco, j3)
    expect(s3.pagina.locator('#codigo-puerta')).to_have_count(0)
    s3.tocar('#j-estoy-aqui')
    ver(s3, '.j-contador', '3 de 5 ya llegaron')

    assert sin_filtraciones(banco, s, n, j1) >= 2
    assert sin_filtraciones(banco, t, n, None) >= 2
    s.sin_errores(rechazos=True)
    s3.sin_errores()
    t.sin_errores()


@prueba('supabase')
def la_tele_pide_su_llave(banco: Banco) -> None:
    """Sin llave, o con una falsa, la tele no muestra nada de la fiesta."""
    n = Noche(banco.db, 4, presentes=False, repartir=False)
    s = banco.sesion('tele')
    s.ir('tv', esperar_a='.tv-aviso')
    ver(s, '.j-titulo', 'Falta la llave')
    s2 = banco.sesion('tele')
    s2.ir('tv#k=llave-falsa', esperar_a='.tv-aviso')
    ver(s2, '.j-titulo', 'no tiene permiso')
    assert 'Jugador' not in s2.pagina.inner_text('body')
    # Con la llave buena, la recibe y la recuerda aunque se abra sin el fragmento.
    llave = n.adm('admin_state')['event']['tv_key']
    s3 = banco.sesion('tele')
    s3.ir(f'tv#k={llave}', esperar_a='.tv-recibidor')
    ver(s3, '.tv-recibidor', 'La puerta está abierta')
    ver(s3, '.tv-gran-titulo', 'cumple 29')
    s3.ir('tv', esperar_a='.tv-recibidor')
    assert sin_filtraciones(banco, s3, n, None) >= 1
    for x in (s, s2, s3):
        x.sin_errores(rechazos=True)


# ================================================================================================== LA CARTA
@prueba('supabase')
def la_carta_solo_se_ve_mientras_se_sostiene(banco: Banco) -> None:
    """La cara de la carta no existe en la página salvo mientras la mantienes presionada. Un roce, un cambio de app o soltar la esconden."""
    n = Noche(banco.db, 6)
    asesino = n.asesinos()[0]
    inocente = n.inocentes()[0]

    s = telefono(banco, asesino)
    ver(s, '.j-etiqueta', 'Ronda 1')
    pestana_juego(s, 'Mi carta')
    ver(s, '#mi-carta')
    assert cara_montada(s) == 0
    visible = s.pagina.inner_text('body')
    html = s.pagina.content()
    for delator in ('Eres el asesino', 'Eres inocente', 'INOCENTE', 'La Muerte', 'El Loco'):
        assert delator not in visible and delator not in html, f'"{delator}" está en la página sin haber sostenido la carta'
    assert 'ASESINO' not in html, 'la cara está en el DOM con la carta boca abajo'

    # Un roce no la voltea.
    caja = s.pagina.locator('#mi-carta').bounding_box()
    s.pagina.mouse.move(caja['x'] + caja['width'] / 2, caja['y'] + caja['height'] / 2)
    s.pagina.mouse.down()
    s.pagina.wait_for_timeout(60)
    s.pagina.mouse.up()
    s.pagina.wait_for_timeout(500)
    assert cara_montada(s) == 0, 'un roce volteó la carta'

    # Sostenida, se ve; al soltar, desaparece del DOM.
    mantener(s)
    ver(s, '#mi-carta-nota', 'Eres el asesino.')
    expect(s.pagina.locator('#mi-carta .cm-frente svg')).to_have_count(1)
    assert 'ASESINO' in (s.pagina.locator('#mi-carta .cm-frente').text_content() or '')
    s.pagina.mouse.up()
    no_hay(s, '#mi-carta .cm-frente svg', seg=3)
    ver(s, '#mi-carta-nota', 'Mantén presionado')

    # Si la app pierde el foco a media sostenida (una llamada, una notificación), se esconde sola.
    mantener(s)
    ver(s, '#mi-carta-nota', 'Eres el asesino.')
    s.pagina.evaluate("window.dispatchEvent(new Event('blur'))")
    no_hay(s, '#mi-carta .cm-frente svg', seg=3)
    ver(s, '#mi-carta-nota', 'Mantén presionado')
    s.pagina.mouse.up()

    # También se puede con teclado: espacio sostenido.
    s.pagina.focus('#mi-carta')
    s.pagina.keyboard.down('Space')
    ver(s, '#mi-carta-nota', 'Eres el asesino.')
    s.pagina.keyboard.up('Space')
    no_hay(s, '#mi-carta .cm-frente svg', seg=3)

    sin_filtraciones(banco, s, n, asesino)
    s.sin_errores()

    # El inocente ve la suya, y su teléfono no sabe quién es el asesino.
    s2 = telefono(banco, inocente)
    pestana_juego(s2, 'Mi carta')
    mantener(s2)
    ver(s2, '#mi-carta-nota', 'Eres inocente.')
    assert 'cómplice' not in s2.pagina.inner_text('body')
    s2.pagina.mouse.up()
    sin_filtraciones(banco, s2, n, inocente)
    s2.sin_errores()


@prueba('supabase')
def los_dos_asesinos_se_conocen(banco: Banco) -> None:
    """Con más de 16 presentes hay dos asesinos, y cada uno lee el nombre de su cómplice en su carta (y solo ahí)."""
    n = Noche(banco.db, 17)
    a1, a2 = n.asesinos()
    s = telefono(banco, a1)
    pestana_juego(s, 'Mi carta')
    mantener(s)
    ver(s, '#mi-carta-nota', 'Eres el asesino.')
    ver(s, '.j-texto', f'Tu cómplice: {a2.nombre}.')
    s.pagina.mouse.up()
    ver(s, '.j-texto.chico', 'No se la enseñes a nadie')
    assert a2.nombre not in s.pagina.locator('#escena-juego').inner_text().replace(f'Tu cómplice: {a2.nombre}.', '').split('Con vida')[0]
    s.sin_errores()


@prueba('supabase')
def quien_llega_tarde_mira_pero_no_juega(banco: Banco) -> None:
    """Quien cruza la puerta con la partida en curso no tiene carta ni voto: la app se lo dice claro."""
    n = Noche(banco.db, 6, presentes=False, repartir=False)
    for j in n.jugadores[:5]:
        j.llegar()
    n.adm('admin_deal')
    tarde = n.jugadores[5]
    s = telefono(banco, tarde)
    ver(s, '.j-etiqueta', 'En la lista')
    ver(s, '#j-estoy-aqui')
    tarde.llegar()
    ver(s, '.j-texto', 'La partida ya empezó sin ti', seg=9)
    pestana_juego(s, 'Mi carta')
    ver(s, '.j-texto', 'empezó sin ti')
    assert cara_montada(s) == 0
    n.a_votacion()
    pestana_juego(s, 'Noche')
    ver(s, '.j-etiqueta', 'En la lista', seg=9)
    try:
        tarde.votar(n.jugadores[0])
    except ErrorApi as e:
        assert e.codigo in ('no_puede_votar', 'sin_carta', 'no_juega'), e.codigo
    else:
        raise AssertionError('quien no estaba en el reparto pudo votar')
    s.sin_errores()


# =============================================================================================== VOTAR Y VEREDICTO
@prueba('supabase')
def votar_por_la_interfaz_y_atrapar_al_asesino(banco: Banco) -> None:
    """Una ronda entera desde el teléfono: discusión, votación con confirmación, voto sellado, veredicto por partes y fin de partida."""
    n = Noche(banco.db, 6)
    asesino = n.asesinos()[0]
    yo = n.inocentes()[0]
    s = telefono(banco, yo)
    t = tele(banco, n)

    ver(s, '.j-etiqueta', 'Ronda 1')
    assert re.fullmatch(r'\d{1,2}:\d{2}', texto(s.pagina, '.j-ronda .cuenta .numeros')), texto(s.pagina, '.j-ronda .cuenta .numeros')
    ver(s, '.j-vivos', 'Con vida · 6')
    ver(t, '.tv-ronda .j-etiqueta', 'Ronda 1')
    ver(t, '.tv-vivos', 'Con vida · 6')

    n.a_votacion()  # vence la discusión: el teléfono se entera solo
    ver(s, '.j-votacion .j-etiqueta', 'Votación', seg=9)
    ver(s, '.j-titulo', '¿Quién es el asesino?')
    ver(t, '.tv-votacion .j-etiqueta', 'Votación', seg=9)
    assert s.pagina.locator('.j-ficha').count() == 5, 'se vota entre los otros cinco'
    assert texto(s.pagina, '#j-votar') == 'Elige a alguien'
    expect(s.pagina.locator('#j-votar')).to_be_disabled()

    # Elegir, arrepentirse, y luego votar de verdad.
    elegir_ficha(s, asesino.nombre, 'Votar por')
    expect(s.pagina.locator('#j-votar')).to_be_enabled()
    s.tocar('#j-votar')
    expect(hoja_abierta(s)).to_contain_text(f'¿Votas por {asesino.nombre}?')
    s.tocar('.hoja-capa.abierta .secundario')  # "Todavía no"
    expect(s.pagina.locator('.hoja-capa.abierta')).to_have_count(0)
    assert contar(banco, 'votes') == 0, 'arrepentirse no debe registrar nada'
    votar_por_ui(s, asesino.nombre)
    ver(s, '.j-sellado .j-texto', f'Votaste por {asesino.nombre}.')
    ver(s, '.j-progreso', 'Ya votaron 1 de 6.')
    assert contar(banco, 'votes') == 1
    assert banco.db.valor('select t.name from app.votes v join app.players t on t.id = v.target_id') == asesino.nombre
    expect(s.pagina.locator('#j-votar')).to_have_count(0)  # ya no hay cómo votar dos veces
    ver(t, '.tv-votacion .j-nota', 'Han votado 1 de 6', seg=9)
    assert 'Voto sellado' not in t.pagina.inner_text('body') and yo.nombre not in t.pagina.locator('.tv-votacion').inner_text(), 'la tele no debe saber quién votó'

    # Los demás votan (el asesino, por otro): ya con todos los votos, se cierra sola y el asesino queda al descubierto.
    for v in n.vivos():
        if v is not yo:
            v.votar(asesino if v is not asesino else yo)
    ver(s, '.j-fin-partida .j-titulo', 'La atraparon.', seg=9)
    ver(s, '.j-fin-partida .j-texto.destacado', f'El asesino era {asesino.nombre}.')
    revelacion_completa(s, acierto=True)
    ver(s, '.rev-acu', asesino.nombre)
    ver(s, '.j-sentencia.acierto', 'Era el asesino.')
    ver(s, '.rev-vot .j-votos', asesino.nombre)
    ver(s, '.rev-beb .bebedores', asesino.nombre)  # el asesino atrapado bebe
    ver(s, '.rev-beb .j-nota', 'el asesino paga')
    no_hay(s, '.rev-sec', seg=1)  # un acierto no revela ningún secreto
    s.pagina.locator('.j-quien summary').click()
    hay(s, '.j-quien li', f'{yo.nombre} → {asesino.nombre}')  # la lista va en el orden de los votantes: puede estar en cualquier lugar
    ver(s, '.j-fin-partida .j-espera', 'Cartas nuevas en')
    # La tele cuenta lo mismo.
    ver(t, '.tv-veredicto .tv-gran-titulo', 'La atraparon.', seg=9)
    ver(t, '.tv-veredicto .rev-beb .bebedores', asesino.nombre, seg=14)

    # Ya con veredicto, los votos sí pueden estar en las respuestas; antes no.
    assert sin_filtraciones(banco, s, n, yo) >= 4
    assert sin_filtraciones(banco, t, n, None) >= 4
    s.sin_errores()
    t.sin_errores()


@prueba('supabase')
def fallo_el_asesino_elige_y_la_victima_lo_sabe(banco: Banco) -> None:
    """Un fallo del grupo: beben quienes votaron por el acusado, sale un secreto anónimo y el asesino elige a su víctima desde el teléfono."""
    n = Noche(banco.db, 6)
    asesino = n.asesinos()[0]
    acusado, victima, testigo = n.inocentes()[:3]
    sa, sv, st = telefono(banco, asesino), telefono(banco, victima), telefono(banco, testigo)
    t = tele(banco, n)

    n.a_fallo(acusado)  # todos votan por el acusado (él, por otro): un fallo
    ver(sa, '.j-golpe .j-titulo', 'Fallaron. Ahora te toca a ti.', seg=9)
    ver(sa, '.j-golpe .j-etiqueta', 'Solo tú ves esto')
    ver(st, '.j-veredicto .j-espera', 'El asesino está eligiendo', seg=9)
    no_hay(st, '.j-golpe', seg=1)
    no_hay(st, '.j-ficha', seg=1)  # quien no es el asesino no tiene a quién elegir
    ver(t, '.tv-veredicto .tv-espera', 'El asesino elige', seg=9)

    revelacion_completa(st, acierto=False)
    ver(st, '.rev-cab', 'Acusaron a')
    ver(st, '.rev-acu', acusado.nombre)
    ver(st, '.j-sentencia', 'Era inocente. Fallaron.')
    ver(st, '.rev-beb .bebedores', testigo.nombre)  # votó por el acusado: bebe
    assert acusado.nombre not in st.pagina.locator('.rev-beb .bebedores').inner_text(), 'el acusado no bebe'
    ver(st, '.rev-beb .j-nota', f'Votaron por {acusado.nombre}')
    secreto = banco.db.fila("select s.*, p.name as autor from app.secrets s join app.players p on p.id = s.author_id where s.status = 'revelado'")
    ver(st, '.j-secreto blockquote p', secreto['text'])
    ver(st, '.j-secreto-sobre', f"Sobre {secreto['about_name']}")
    assert secreto['autor'] not in st.pagina.locator('.j-secreto').inner_text(), 'el secreto es anónimo'
    ver(st, '.j-secreto figcaption', 'Alguien que te quiere')

    golpear_por_ui(sa, victima.nombre)
    no_hay(sa, '.j-golpe', seg=6)
    assert contar(banco, 'kills') == 1
    assert banco.db.valor('select alive from app.roles r join app.players p on p.id = r.player_id where p.name = %s order by r.game_id desc limit 1', victima.nombre) is False

    # La víctima se entera con la pantalla "Has muerto"; una sola vez.
    ver(sv, '.j-muerte .j-titulo', 'Has muerto.', seg=9)
    expect(sv.pagina.locator('.j-muerte')).to_have_attribute('role', 'alertdialog')
    sv.tocar('.j-muerte .secundario')
    no_hay(sv, '.j-muerte', seg=3)
    ver(sv, '.j-estado.muerto', 'Sin vida')
    sv.pagina.reload()
    ver(sv, '.j-escena')
    no_hay(sv, '.j-muerte', seg=2)
    ver(sv, '.j-nota.apagada', 'Has muerto. Sigues en la fiesta, pero ya no votas.', seg=9)
    # La tele lo anuncia y el testigo recibe el aviso.
    ver(t, '.tv-muerte', f'{victima.nombre} ha muerto.', seg=9)
    ver(st, '.j-etiqueta', 'Ronda 2', seg=9)
    pestana_juego(st, 'Bitácora')
    ver(st, '.j-bitacora-lista li', f'Acusaron a {acusado.nombre}: era inocente.')
    ver(st, '.j-bitacora-lista li', f'Cayó {victima.nombre}.')

    # Los muertos no votan: ni en la interfaz ni en la API.
    n.a_votacion()
    pestana_juego(sv, 'Noche')
    ver(sv, '.j-sellado .j-titulo', 'Los muertos no votan.', seg=9)
    no_hay(sv, '.j-ficha', seg=1)
    try:
        victima.votar(asesino)
    except ErrorApi:
        pass
    else:
        raise AssertionError('un muerto pudo votar')
    for fono, quien in ((sa, asesino), (sv, victima), (st, testigo)):
        assert sin_filtraciones(banco, fono, n, quien) >= 1
        fono.sin_errores()
    t.sin_errores()


@prueba('supabase')
def tras_atrapar_al_asesino_se_reparte_de_nuevo(banco: Banco) -> None:
    """Fin de partida: todos reviven, pasa la pausa y llegan cartas nuevas sin que nadie toque nada."""
    n = Noche(banco.db, 6)
    inocente = n.inocentes()[0]
    s = telefono(banco, inocente)
    t = tele(banco, n)
    ver(s, '.j-etiqueta', 'Ronda 1')
    n.a_acierto()
    ver(s, '.j-fin-partida .j-titulo', 'La atraparon.', seg=9)
    ver(s, '.j-etiqueta', 'Fin de la partida 1')
    ver(t, '.tv-veredicto .tv-gran-titulo', 'La atraparon.', seg=9)
    ver(t, '.tv-espera', 'Cartas nuevas')
    n.adelantar(banco.db.valor('select pause_seconds from app.event') + 1)
    ver(s, '.j-ronda .j-etiqueta', 'Ronda 1', seg=9)
    ver(s, '.j-vivos', 'Con vida · 6')
    assert contar(banco, 'games') == 2
    assert banco.db.valor('select count(*) from app.roles r where r.game_id = (select id from app.games order by number desc limit 1) and r.alive') == 6
    pestana_juego(s, 'Bitácora')
    ver(s, '.j-etiqueta', 'Bitácora · Partida 2')
    ver(t, '.tv-ronda .j-etiqueta', 'Ronda 1', seg=9)
    ver(t, '.tv-contexto', 'Partida 2')
    s.sin_errores()
    t.sin_errores()


@prueba('supabase')
def el_asesino_gana_si_queda_un_inocente(banco: Banco) -> None:
    """Con tres jugadores, un fallo y una víctima dejan al asesino con un solo inocente: gana, y se dice."""
    n = Noche(banco.db, 3)
    asesino = n.asesinos()[0]
    a, b = n.inocentes()
    sa, sb = telefono(banco, asesino), telefono(banco, b)
    t = tele(banco, n)
    n.a_fallo(a)
    golpear_por_ui(sa, a.nombre)
    ver(sb, '.j-fin-partida .j-titulo', 'Ganó el asesino.', seg=9)
    ver(sb, '.j-fin-partida .j-texto.destacado', f'El asesino era {asesino.nombre}.')
    ver(sb, '.j-fin-partida .j-texto.destacado', 'Solo quedaba un inocente en pie.')
    ver(t, '.tv-veredicto .tv-gran-titulo', 'Ganó el asesino.', seg=9)
    assert banco.db.valor('select result from app.games order by number desc limit 1') == 'asesino_gana'
    n.adelantar(banco.db.valor('select pause_seconds from app.event') + 1)
    ver(sb, '.j-ronda .j-etiqueta', 'Ronda 1', seg=9)  # nueva partida, tres vivos
    sa.sin_errores()
    sb.sin_errores()


@prueba('supabase')
def desempate_por_la_interfaz(banco: Banco) -> None:
    """Un 3–3 abre un desempate entre los empatados; si sigue empatado, es un fallo y beben ellos."""
    n = Noche(banco.db, 6)
    js = n.jugadores
    x, y = js[3], js[0]
    s = telefono(banco, js[1])
    t = tele(banco, n)
    n.a_votacion()
    for votante, objetivo in [(js[0], x), (js[1], x), (js[2], x), (js[3], y), (js[4], y), (js[5], y)]:
        votante.votar(objetivo)
    ver(s, '.j-votacion .j-etiqueta', 'Desempate relámpago', seg=9)
    ver(s, '.j-titulo', f'Empate entre {y.nombre} y {x.nombre}.')
    assert s.pagina.locator('.j-ficha').count() == 2, 'en el desempate solo se elige entre los empatados'
    ver(t, '.tv-votacion .j-etiqueta', 'Desempate relámpago', seg=9)
    ver(t, '.tv-gran-titulo', 'Empate entre')
    # Nadie desempata: se acaba el tiempo y el empate se cuenta como fallo.
    n.adelantar(banco.db.valor('select tiebreak_seconds from app.event') + 1)
    ver(s, '.j-veredicto .rev-cab', 'Empate que no se rompió', seg=9)
    revelacion_completa(s, acierto=False)
    ver(s, '.j-sentencia', 'La sala no se puso de acuerdo. Fallaron.')
    ver(s, '.rev-beb .bebedores', x.nombre)
    ver(s, '.rev-beb .bebedores', y.nombre)
    ver(s, '.rev-beb .j-nota', 'Los empatados')
    s.sin_errores()
    t.sin_errores()


@prueba('supabase')
def la_pausa_congela_el_tiempo(banco: Banco) -> None:
    """En pausa, las cuentas regresivas se detienen en todas las pantallas y al reanudar siguen desde donde iban."""
    n = Noche(banco.db, 6)
    s = telefono(banco, n.inocentes()[0])
    t = tele(banco, n)
    ver(s, '.j-ronda .cuenta .numeros')
    n.adm('admin_control', p_action='pause')
    ver(s, '.j-pausa', 'Pausa. El tiempo está detenido.', seg=9)
    ver(t, '.tv-pausa', 'Pausa', seg=9)
    ver(t, '.tv-cab', 'en pausa')
    expect(s.pagina.locator('.j-ronda .cuenta')).to_have_class(re.compile(r'\bpausada\b'))
    antes = texto(s.pagina, '.j-ronda .cuenta .numeros')
    s.pagina.wait_for_timeout(2600)
    assert texto(s.pagina, '.j-ronda .cuenta .numeros') == antes, 'la cuenta siguió corriendo en pausa'
    try:
        n.jugadores[0].votar(n.jugadores[1])
    except ErrorApi:
        pass
    else:
        raise AssertionError('se pudo votar en pausa (o antes de tiempo)')
    n.adm('admin_control', p_action='resume')
    no_hay(s, '.j-pausa', seg=9)
    no_hay(t, '.tv-pausa', seg=9)
    despues = texto(s.pagina, '.j-ronda .cuenta .numeros')
    s.pagina.wait_for_timeout(2600)
    assert texto(s.pagina, '.j-ronda .cuenta .numeros') != despues, 'al reanudar la cuenta debe volver a correr'
    s.sin_errores()
    t.sin_errores()


@prueba('supabase')
def muerte_de_apertura(banco: Banco) -> None:
    """Con la opción encendida, la noche empieza con una víctima que solo el asesino elige; los demás solo ven que hay sangre."""
    n = Noche(banco.db, 6, repartir=False)
    n.config(opening_kill=True)
    n.adm('admin_deal')
    asesino = n.asesinos()[0]
    inocente, victima = n.inocentes()[:2]
    sa, si = telefono(banco, asesino), telefono(banco, inocente)
    t = tele(banco, n)
    ver(sa, '.j-golpe .j-titulo', 'La noche empieza contigo')
    ver(si, '.j-titulo', 'La noche empieza con sangre.')
    ver(si, '.j-texto', 'Alguien está eligiendo a la primera víctima')
    no_hay(si, '.j-golpe', seg=1)
    ver(t, '.tv-gran-titulo', 'con sangre')
    golpear_por_ui(sa, victima.nombre)
    ver(si, '.j-etiqueta', 'Ronda 1', seg=9)
    ver(si, '.j-vivos', 'Con vida · 5')
    pestana_juego(si, 'Bitácora')
    ver(si, '.j-bitacora-lista li', f'La noche empezó con sangre: cayó {victima.nombre}.')
    sv = telefono(banco, victima)
    ver(sv, '.j-muerte .j-titulo', 'Has muerto.')
    ver(t, '.tv-ronda .j-etiqueta', 'Ronda 1', seg=9)
    for x in (sa, si, sv, t):
        x.sin_errores()


# ================================================================================================= RED Y AVISOS
@prueba('supabase')
def sin_conexion_avisa_y_se_recupera(banco: Banco) -> None:
    """Sin red la app conserva lo último que sabía, lo dice, no pierde en silencio lo que se intenta hacer y se recupera sola."""
    n = Noche(banco.db, 5, presentes=False, repartir=False)
    j1 = n.jugadores[0]
    s = telefono(banco, j1)
    ver(s, '.j-antesala .j-titulo', 'Ya estás dentro')
    no_hay(s, '.j-conexion', seg=1)

    def abortar(ruta) -> None:
        ruta.abort('internetdisconnected')

    s.pagina.context.route(SUPABASE_FALSO + '/rest/**', abortar)
    ver(s, '.j-conexion', 'Sin conexión', seg=12)
    ver(s, '.j-antesala .j-titulo', 'Ya estás dentro')  # sigue mostrando lo último que sabía
    s.tocar('#j-estoy-aqui')
    ver(s, '#codigo-error', 'No hay conexión')
    assert banco.db.valor('select checked_in from app.players where id = %s', j1.id) is False

    s.pagina.context.unroute(SUPABASE_FALSO + '/rest/**', abortar)
    no_hay(s, '.j-conexion', seg=9)
    s.tocar('#j-estoy-aqui')
    ver(s, '.j-contador', '1 de 5 ya llegaron')
    s.sin_errores(ignorar_red=True)


@prueba('supabase')
def el_aviso_en_vivo_adelanta_la_consulta(banco: Banco) -> None:
    """Con el canal de Realtime sano, un broadcast (binario o JSON) hace que el teléfono consulte al instante; si se corta, se reconecta."""
    n = Noche(banco.db, 5, presentes=False, repartir=False)
    j1, j2, j3 = n.jugadores[:3]
    s = telefono(banco, j1, realtime=True)
    esperar(s.pagina, 'window.__realtime.estado().unidos >= 1', 10)
    assert s.pagina.evaluate('window.__realtime.estado().temas') == ['realtime:noche'], 'debe unirse al canal "noche"'
    ver(s, '.j-contador', '0 de 5 ya llegaron')
    antes = len(respuestas(s, 'get_state'))

    j2.llegar()
    s.pagina.evaluate('window.__realtime.ping(true)')
    ver(s, '.j-contador', '1 de 5 ya llegaron', seg=2.5)  # con el canal sano se consulta cada 10 s: esto solo pudo ser el aviso
    assert len(respuestas(s, 'get_state')) > antes
    j3.llegar()
    s.pagina.evaluate('window.__realtime.ping(false)')
    ver(s, '.j-contador', '2 de 5 ya llegaron', seg=2.5)

    intentos = s.pagina.evaluate('window.__realtime.estado().intentos')
    s.pagina.evaluate('window.__realtime.cortar()')
    esperar(s.pagina, f'window.__realtime.estado().intentos > {intentos}', 10)
    esperar(s.pagina, 'window.__realtime.estado().abiertos >= 1 && window.__realtime.estado().unidos >= 2', 10)
    s.sin_errores()


GUION_PUSH = r"""
const oyentes = {}, mostradas = [], abiertas = [], enfocadas = []
let cerradas = 0, ventanas = []
globalThis.self = globalThis
self.addEventListener = (tipo, fn) => { oyentes[tipo] = fn }
self.registration = { showNotification: (titulo, o) => { mostradas.push({ titulo, ...o }); return Promise.resolve() } }
self.clients = { matchAll: async () => ventanas, openWindow: async url => { abiertas.push(url) } }
require(process.argv[1])
const espera = []
const push = datos => oyentes.push({ data: datos === null ? null : { json: () => JSON.parse(datos), text: () => datos }, waitUntil: p => espera.push(p) })
const clic = url => oyentes.notificationclick({ notification: { close: () => { cerradas++ }, data: url ? { url } : {} }, waitUntil: p => espera.push(p) })
;(async () => {
  push('{"title":"Se abrió la votación","body":"Tienes 3 minutos.","tag":"votacion","url":"/"}')
  push('esto no es json')
  push(null)
  await Promise.all(espera.splice(0))
  clic('/tv')
  await Promise.all(espera.splice(0))
  ventanas = [{ focus: () => { enfocadas.push(1); return Promise.resolve() } }]
  clic()
  await Promise.all(espera.splice(0))
  console.log(JSON.stringify({ mostradas, abiertas, enfocadas, cerradas, tipos: Object.keys(oyentes) }))
})()
"""


@prueba('supabase')
def el_service_worker_muestra_los_avisos(banco: Banco) -> None:
    """El manejador de push (public/push-sw.js) muestra lo que manda el servidor, aguanta cargas raras y abre o enfoca la app al tocarlo."""
    r = subprocess.run(['node', '-e', GUION_PUSH, str(RAIZ / 'public' / 'push-sw.js')], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert sorted(d['tipos']) == ['notificationclick', 'push']
    votacion, rara, vacia = d['mostradas']
    assert (votacion['titulo'], votacion['body'], votacion['tag']) == ('Se abrió la votación', 'Tienes 3 minutos.', 'votacion')
    assert votacion['data'] == {'url': '/'} and votacion['icon'] == '/pwa-192.png' and votacion['renotify'] is True
    assert rara['titulo'] == 'Mariela · 29' and rara['body'] == 'esto no es json'
    assert vacia['titulo'] == 'Mariela · 29' and vacia['body'] == ''
    assert d['cerradas'] == 2 and d['abiertas'] == ['/tv'] and d['enfocadas'] == [1]
    # Y el service worker que genera el build lo incluye.
    sw = (RAIZ / 'dist-sb' / 'sw.js').read_text()
    assert 'push-sw.js' in sw, 'el service worker generado no importa push-sw.js'
    assert (RAIZ / 'dist-sb' / 'push-sw.js').exists()


@prueba('supabase')
def el_push_llega_al_service_worker_real(banco: Banco) -> None:
    """Un push entregado por el navegador (CDP) llega al service worker del build y se muestra como notificación."""
    s = banco.sesion('Pixel 7', permisos=['notifications'])
    s.ir()
    esperar(s.pagina, "navigator.serviceWorker.controller !== null", 20)
    cdp = s.pagina.context.new_cdp_session(s.pagina)
    registros: list[dict] = []
    cdp.on('ServiceWorker.workerRegistrationUpdated', lambda ev: registros.extend(ev['registrations']))
    cdp.send('ServiceWorker.enable')
    esperar(s.pagina, 'true', 1)
    for _ in range(50):
        if registros:
            break
        s.pagina.wait_for_timeout(100)
    assert registros, 'el navegador no reportó ningún service worker'
    origen = s.url.rstrip('/')
    cdp.send('ServiceWorker.deliverPushMessage', {
        'origin': origen, 'registrationId': registros[-1]['registrationId'],
        'data': json.dumps({'title': 'Alguien ha muerto', 'body': 'Mira la tele.', 'tag': 'muerte', 'url': '/'}),
    })
    esperar(s.pagina, "navigator.serviceWorker.getRegistration().then(r => r.getNotifications()).then(l => l.length > 0)", 10)
    notas = s.pagina.evaluate("navigator.serviceWorker.getRegistration().then(r => r.getNotifications()).then(l => l.map(n => ({ title: n.title, body: n.body, tag: n.tag })))")
    assert notas == [{'title': 'Alguien ha muerto', 'body': 'Mira la tele.', 'tag': 'muerte'}], notas


# ===================================================================================== FIN DE LA NOCHE Y RANKING
@prueba('supabase')
def el_fin_de_la_noche_muestra_los_premios(banco: Banco) -> None:
    """Al terminar la noche, teléfonos y tele muestran el podio de tragos y los premios; y se puede reabrir."""
    n = Noche(banco.db, 6)
    asesino = n.asesinos()[0]
    acusado, victima, testigo = n.inocentes()[:3]
    n.a_fallo(acusado)
    asesino.matar(victima)
    s = telefono(banco, testigo)
    t = tele(banco, n)
    n.adm('admin_control', p_action='end_night')
    ver(s, '.fin-noche .j-titulo', 'Se acabó la noche.', seg=9)
    ver(s, '.premios-cifras', '1 partida')
    ver(s, '.podio', 'trago')
    ver(s, '.premios-lista', 'Quien más bebió')
    ver(s, '.premios-lista', 'Sangre fría')  # el asesino ya puede ser nombrado: la noche terminó
    ver(s, '.premios-lista', asesino.nombre)
    ver(t, '.tv-cierre .tv-gran-titulo', 'Se acabó la noche', seg=9)
    ver(t, '.tv-cierre .premios', 'Quien más bebió')
    s.tocar('.fin-noche .j-enlace')
    ver(s, '#sello, .escena.listo')  # "Ver la invitación" devuelve la invitación
    n.adm('admin_control', p_action='reopen')
    s2 = telefono(banco, testigo)
    ver(s2, '.j-antesala, .j-ronda', seg=9)
    s.sin_errores()
    t.sin_errores()


# ======================================================================================================== ADMIN
def toast(s: Sesion, contiene: str, seg: float = 8) -> None:
    """Algún aviso de los que están en pantalla (pueden juntarse hasta tres) dice esto."""
    expect(s.pagina.locator('.avisos .aviso-toast', has_text=contiene).first).to_be_visible(timeout=seg * 1000)


@prueba('supabase')
def admin_acceso_pin_y_sesion(banco: Banco) -> None:
    """El PIN se verifica en el servidor: bloqueo tras cinco fallos, sesión que sobrevive a recargar, salir la invalida y el PIN se cambia desde el panel."""
    Noche(banco.db, 4, lobby=False, aprobar=False)
    s = banco.sesion('escritorio')
    s.pagina.set_default_timeout(TIEMPO)
    s.ir('admin', esperar_a='#pin')
    ver(s, '.j-titulo', '¿Quién manda esta noche?')
    expect(s.pagina.locator('form button[type=submit]')).to_be_disabled()  # sin PIN escrito no hay botón

    s.pagina.fill('#pin', 'incorrecto')
    s.pagina.keyboard.press('Enter')
    ver(s, '#pin-error', 'PIN incorrecto.')
    assert s.pagina.input_value('#pin') == '', 'un PIN malo no se queda escrito'
    assert s.pagina.locator('.admin').count() == 0

    for _ in range(3):
        banco.db.llamar('admin_login', p_pin='otro-malo')
    s.pagina.fill('#pin', 'quinto-malo')
    s.pagina.keyboard.press('Enter')
    ver(s, '#pin-error', 'PIN incorrecto.')
    s.pagina.fill('#pin', banco.pin)  # el bueno, pero ya está bloqueado
    s.pagina.keyboard.press('Enter')
    ver(s, '#pin-error', 'Demasiados intentos')
    assert s.pagina.locator('.admin').count() == 0, 'el bloqueo no debe dejar pasar ni al PIN correcto'
    banco.db.sql('update app.admin set failed_attempts = 0, locked_until = null')

    s.pagina.fill('#pin', banco.pin)
    s.pagina.keyboard.press('Enter')
    s.pagina.wait_for_selector('.admin')
    ver(s, '.j-estado', 'Invitación')
    sesion = s.pagina.evaluate("JSON.parse(localStorage.getItem('mariela.admin')).session")
    assert sesion and banco.pin not in sesion
    s.pagina.reload()
    s.pagina.wait_for_selector('.admin')  # la sesión sigue: no pide el PIN otra vez
    assert banco.db.llamar('admin_state', p_session=sesion)['event']['phase'] == 'invitacion'

    # Cambiar el PIN desde el panel: el viejo deja de servir.
    pestana_admin(s, 'Ajustes')
    s.pagina.fill('#pin-nuevo', 'corto')
    s.pagina.fill('#pin-otra', 'corto')
    expect(s.pagina.get_by_role('button', name='Cambiar PIN')).to_be_disabled()
    s.pagina.fill('#pin-nuevo', 'la-noche-es-mia')
    s.pagina.fill('#pin-otra', 'la-noche-es-mia')
    s.pagina.get_by_role('button', name='Cambiar PIN').click()
    s.pagina.wait_for_selector('#pin')  # recarga y pide el PIN nuevo
    s.pagina.fill('#pin', banco.pin)
    s.pagina.keyboard.press('Enter')
    ver(s, '#pin-error', 'PIN incorrecto.')
    s.pagina.fill('#pin', 'la-noche-es-mia')
    s.pagina.keyboard.press('Enter')
    s.pagina.wait_for_selector('.admin')

    # Salir cierra la sesión también en el servidor.
    sesion = s.pagina.evaluate("JSON.parse(localStorage.getItem('mariela.admin')).session")
    s.tocar('.ad-salir')
    ver(s, '#pin')
    for _ in range(30):  # la llamada de salida va sin esperar respuesta
        try:
            banco.db.llamar('admin_state', p_session=sesion)
        except ErrorApi as e:
            assert e.codigo == 'sin_permiso', e.codigo
            break
        s.pagina.wait_for_timeout(100)
    else:
        raise AssertionError('la sesión seguía viva después de salir')
    assert s.pagina.evaluate("localStorage.getItem('mariela.admin')") is None
    s.sin_errores(rechazos=True)


@prueba('supabase')
def admin_invitados_y_secretos(banco: Banco) -> None:
    """Invitados (buscar, marcar presencia, agregar con llave, llave nueva, quitar) y secretos anónimos (aprobar, rechazar, editar)."""
    n = Noche(banco.db, 5, lobby=False, aprobar=False)
    s = panel(banco, n, 'Invitados')
    filas = s.pagina.locator('.ad-invitado')
    expect(filas).to_have_count(5)
    ver(s, '.ad-seccion', '0 presentes de 5')
    s.pagina.fill('#busca', 'jugador 03')
    expect(filas).to_have_count(1)
    hay(s, '.ad-invitado', 'Jugador 03')
    s.pagina.fill('#busca', 'nadie')
    ver(s, '.ad-vacio', 'Nadie coincide.')
    s.pagina.fill('#busca', '')
    expect(filas).to_have_count(5)
    assert s.pagina.locator('.ad-chips i.aviso').count() == 0, 'los cinco respondieron desde su teléfono'

    primero = filas.first.locator('.ad-interruptor')
    expect(primero).to_have_attribute('aria-pressed', 'false')
    primero.click()
    expect(primero).to_have_attribute('aria-pressed', 'true')
    ver(s, '.ad-seccion', '1 presentes de 5')
    assert contar(banco, 'players', 'checked_in') == 1
    primero.click()
    expect(primero).to_have_attribute('aria-pressed', 'false')
    assert contar(banco, 'players', 'checked_in') == 0

    # Alguien llega sin haber respondido: se le agrega y se le da su llave.
    s.pagina.fill('#nuevo', 'Marisol')
    s.pagina.get_by_role('button', name='Agregar', exact=True).click()
    ver(s, '.hoja-capa.abierta .llave-c', seg=8)
    llave = texto(s.pagina, '.hoja-capa.abierta .llave-c')
    assert CAMPO_LLAVE.match(llave), llave
    assert contar(banco, 'players', "name = 'Marisol'") == 1
    s.pagina.keyboard.press('Escape')
    expect(s.pagina.locator('.hoja-capa.abierta')).to_have_count(0)
    hay(s, '.ad-invitado', 'Marisol')
    assert s.pagina.locator('.ad-invitado', has_text='Marisol').locator('i.aviso').count() == 1, 'a Marisol se le avisa que aún no abre la app'
    assert banco.db.llamar('recover', p_token=secrets.token_urlsafe(32), p_name='marisol', p_key=llave)['ok'] is True, 'la llave que muestra el panel debe servir'
    # Llave nueva: la anterior deja de servir.
    s.pagina.locator('.ad-mas[aria-label="Más acciones para Marisol"]').click()
    s.pagina.get_by_role('button', name='Generar llave nueva').click()
    ver(s, '.hoja-capa.abierta .llave-c', seg=8)
    nueva = texto(s.pagina, '.hoja-capa.abierta .llave-c')
    assert nueva != llave and CAMPO_LLAVE.match(nueva)
    r = banco.db.llamar('recover', p_token=secrets.token_urlsafe(32), p_name='marisol', p_key=llave)
    assert r['ok'] is False, 'la llave vieja no debe servir'
    s.pagina.keyboard.press('Escape')
    # Quitarla pide confirmación.
    s.pagina.locator('.ad-mas[aria-label="Más acciones para Marisol"]').click()
    s.pagina.get_by_role('button', name='Quitar de la noche').click()
    hoja = s.pagina.locator('.hoja-capa.abierta .hoja')
    expect(hoja).to_contain_text('¿Quitar a Marisol?')
    hoja.get_by_role('button', name='Cancelar').click()
    assert contar(banco, 'players', "name = 'Marisol'") == 1
    s.pagina.locator('.ad-mas[aria-label="Más acciones para Marisol"]').click()
    s.pagina.get_by_role('button', name='Quitar de la noche').click()
    s.pagina.locator('.hoja-capa.abierta .hoja').get_by_role('button', name='Quitar', exact=True).click()
    expect(s.pagina.locator('.ad-invitado', has_text='Marisol')).to_have_count(0)
    assert contar(banco, 'players', "name = 'Marisol'") == 0

    # Secretos: anónimos, con aprobación uno por uno o todos juntos.
    pestana_admin(s, 'Secretos')
    ver(s, '.ad-resumen', '5 por revisar')
    assert s.pagina.locator('.ad-secreto.pendiente').count() == 5
    contenido = s.pagina.locator('.ad-seccion').inner_text()
    for j in n.jugadores:
        assert f'Autor: {j.nombre}' not in contenido and 'Escrito por' not in contenido
    respuesta = banco.db.llamar('admin_state', p_session=banco.db.llamar('admin_login', p_pin=banco.pin)['session'])
    assert all('author' not in k and 'author_id' not in k for sec in respuesta['secrets'] for k in sec), 'el panel no debe saber quién escribió cada secreto'
    tarjeta = s.pagina.locator('.ad-secreto').first
    tarjeta.get_by_role('button', name='Rechazar').click()
    expect(s.pagina.locator('.ad-secreto.rechazado')).to_have_count(1)
    tarjeta = s.pagina.locator('.ad-secreto.rechazado').first
    tarjeta.get_by_role('button', name='Editar').click()
    s.pagina.locator('.ad-editar textarea').fill('Un secreto más suave y sin nombres.')
    s.pagina.locator('.ad-editar').get_by_role('button', name='Guardar').click()
    toast(s, 'Guardado.')
    ver(s, '.ad-secreto.rechazado .ad-texto', 'Un secreto más suave y sin nombres.')
    s.pagina.get_by_role('button', name='Aprobar los 4 pendientes').click()
    toast(s, 'Aprobados.')
    ver(s, '.ad-resumen', '0 por revisar')
    ver(s, '.ad-resumen', '4 en el juego')
    assert contar(banco, 'secrets', "status = 'aprobado'") == 4
    tarjeta = s.pagina.locator('.ad-secreto.rechazado').first
    tarjeta.get_by_role('button', name='Aprobar', exact=True).click()
    ver(s, '.ad-resumen', '5 en el juego')
    ver(s, '.ad-pestanas', 'Secretos')
    assert s.pagina.locator('.ad-aviso').count() == 0, 'ya no hay nada por revisar: la insignia se va'
    s.sin_errores()


@prueba('supabase')
def admin_ajustes_y_control_de_la_noche(banco: Banco) -> None:
    """Ajustes que llegan al servidor y controles de la noche: abrir la puerta, repartir, pausar, terminar, reabrir."""
    n = Noche(banco.db, 5, lobby=False)
    s = panel(banco, n)
    pestana_admin(s, 'Ajustes')
    expect(s.pagina.locator('#ad-guardar')).to_be_disabled()
    s.pagina.fill('#a-direccion', 'Calle Falsa 123, Col. Roma Norte, CDMX')
    s.pagina.get_by_role('button', name='Revelar ya').click()
    s.pagina.get_by_role('button', name='Generar uno').click()
    codigo = s.pagina.input_value('#a-codigo')
    assert re.fullmatch(r'[A-Z0-9]{3,4}', codigo), codigo
    s.pagina.fill('#a-ronda', '0.5')
    s.pagina.fill('#a-voto', '1')
    s.pagina.fill('#a-umbral', '20')
    s.pagina.locator('.ad-check', has_text='Muerte de apertura').locator('input').check()
    expect(s.pagina.locator('#ad-guardar')).to_be_enabled()
    guardar_ajustes(s)
    ev = banco.db.fila('select * from app.event')
    assert ev['address'] == 'Calle Falsa 123, Col. Roma Norte, CDMX'
    assert ev['door_code'] == codigo and ev['round_seconds'] == 30 and ev['vote_seconds'] == 60
    assert ev['killers_threshold'] == 20 and ev['opening_kill'] is True
    assert ev['address_reveal_at'] is not None and banco.db.valor('select address_reveal_at <= now() from app.event')
    # Un valor que el servidor rechaza no se queda a medias.
    s.pagina.fill('#a-ronda', '0')
    s.tocar('#ad-guardar')
    toast(s, 'no es válido')
    assert banco.db.valor('select round_seconds from app.event') == 30
    s.pagina.fill('#a-ronda', '0.5')
    s.pagina.get_by_role('button', name='Sin código').click()
    s.pagina.locator('.ad-check', has_text='Muerte de apertura').locator('input').uncheck()
    guardar_ajustes(s)
    assert banco.db.valor('select door_code from app.event') is None and banco.db.valor('select opening_kill from app.event') is False

    # Noche: la puerta, las condiciones para repartir, y el reparto.
    pestana_admin(s, 'Noche')
    ver(s, '.ad-grande', '0 de 5 presentes')
    ver(s, '.ad-lista-check', 'Dirección revelada')
    s.pagina.get_by_role('button', name='Abrir la puerta').click()
    toast(s, 'La puerta está abierta.')
    ver(s, '.j-estado', 'Puerta abierta')
    expect(s.pagina.locator('#ad-repartir')).to_be_disabled()
    ver(s, '.ad-nota', 'al menos 3 personas presentes')
    for j in n.jugadores[:4]:
        j.llegar()
    ver(s, '.ad-grande', '4 de 5 presentes', seg=9)
    expect(s.pagina.locator('#ad-repartir')).to_be_enabled()
    s.tocar('#ad-repartir')
    toast(s, 'Cartas repartidas.')
    ver(s, '.j-estado', 'Jugando')
    ver(s, '.ad-estado .j-etiqueta', 'Partida 1 · Ronda 1')
    ver(s, '.ad-grande', 'Discusión')
    ver(s, '.ad-estado .j-nota', '4 con vida')
    assert banco.db.valor('select count(*) from app.roles') == 4

    # Pausar y seguir; adelantar; el enlace de la tele con su llave.
    s.pagina.get_by_role('button', name='Pausar', exact=True).click()
    toast(s, 'Juego en pausa.')
    assert banco.db.valor('select paused_at is not null from app.event') is True
    ver(s, '.ad-estado .j-nota', 'en pausa')
    s.pagina.get_by_role('button', name='Reanudar').click()
    toast(s, 'El juego sigue.')
    assert banco.db.valor('select paused_at is null from app.event') is True
    s.pagina.get_by_role('button', name='Abrir la votación ya').click()
    ver(s, '.ad-grande', 'Votación', seg=9)
    llave_tv = banco.db.valor('select tv_key from app.event')
    ver(s, '.ad-enlace code', f'/tv#k={llave_tv}')

    # Repartir de nuevo y terminar la noche piden confirmación.
    s.pagina.get_by_role('button', name='Repartir de nuevo').click()
    hoja = s.pagina.locator('.hoja-capa.abierta .hoja')
    expect(hoja).to_contain_text('¿Repartir de nuevo?')
    hoja.get_by_role('button', name='Cancelar').click()
    assert contar(banco, 'games') == 1
    s.pagina.get_by_role('button', name='Repartir de nuevo').click()
    s.pagina.locator('.hoja-capa.abierta .hoja').get_by_role('button', name='Repartir de nuevo').click()
    toast(s, 'Cartas nuevas.')
    assert contar(banco, 'games') == 2
    s.pagina.get_by_role('button', name='Terminar la noche').click()
    s.pagina.locator('.hoja-capa.abierta .hoja').get_by_role('button', name='Terminar la noche').click()
    toast(s, 'La noche terminó.')
    ver(s, '.j-estado', 'Terminó')
    assert banco.db.valor('select phase from app.event') == 'fin'
    s.pagina.get_by_role('button', name='Reabrir la noche').click()
    toast(s, 'La noche sigue abierta.')
    assert banco.db.valor('select phase from app.event') != 'fin'
    s.sin_errores(rechazos=True)


@prueba('supabase')
def admin_modo_ensayo(banco: Banco) -> None:
    """El modo ensayo: se enciende en Ajustes, trae bots y reloj adelantable, y al apagarlo todo vuelve a la hora real."""
    n = Noche(banco.db, 3, lobby=False)
    s = panel(banco, n, 'Ajustes')
    no_hay(s, '.ad-banda', seg=1)
    assert s.pagina.locator('.ad-pestanas button', has_text='Ensayo').count() == 0
    s.pagina.locator('.ad-check', has_text='Modo ensayo').locator('input').check()
    guardar_ajustes(s)
    ver(s, '.ad-banda', 'Modo ensayo')
    pestana_admin(s, 'Ensayo')
    s.pagina.fill('#e-bots', '5')
    s.pagina.get_by_role('button', name='Agregar bots').click()
    toast(s, 'Bots agregados.')
    hay(s, '.ad-nota', 'Ahora hay 5 bots.')
    assert contar(banco, 'players', 'is_bot') == 5
    s.pagina.get_by_role('button', name='+5 min').click()
    hay(s, '.ad-seccion', 'Desfase actual: 5 min')
    assert banco.db.valor("select extract(epoch from clock_offset)::int from app.event") == 300
    pestana_admin(s, 'Noche')
    hay(s, '.ad-lista-check li.falta', 'El modo ensayo sigue encendido')  # no se puede olvidar apagarlo antes de la fiesta
    s.pagina.get_by_role('button', name='Abrir la puerta').click()
    toast(s, 'La puerta está abierta.')
    for j in n.jugadores:
        j.llegar()
    ver(s, '.ad-grande', '8 de 8 presentes', seg=9)  # los bots llegan solos
    s.tocar('#ad-repartir')
    toast(s, 'Cartas repartidas.')
    pestana_admin(s, 'Ensayo')
    s.pagina.get_by_role('button', name='Mostrar roles y votos').click()
    ver(s, '.ad-dios li.asesino')
    assert s.pagina.locator('.ad-dios li').count() == 8
    # Reiniciar borra partidas y bots.
    s.pagina.get_by_role('button', name='Reiniciar el ensayo').click()
    s.pagina.locator('.hoja-capa.abierta .hoja').get_by_role('button', name='Reiniciar', exact=True).click()
    toast(s, 'Ensayo reiniciado.')
    assert contar(banco, 'players', 'is_bot') == 0 and contar(banco, 'games') == 0
    # Apagarlo pide confirmación y devuelve el reloj a la hora real.
    pestana_admin(s, 'Ajustes')
    s.pagina.locator('.ad-check', has_text='Modo ensayo').locator('input').click()  # apagarlo pide confirmar antes de cambiar
    hoja = s.pagina.locator('.hoja-capa.abierta .hoja')
    expect(hoja).to_contain_text('¿Apagar el ensayo?')
    hoja.get_by_role('button', name='Apagar el ensayo').click()
    guardar_ajustes(s)
    no_hay(s, '.ad-banda', seg=9)
    assert banco.db.valor('select rehearsal from app.event') is False
    assert banco.db.valor("select extract(epoch from clock_offset)::int from app.event") == 0
    s.sin_errores()


# ============================================================================================ UNA NOCHE ENTERA
DETECTAR_PANTALLA = """
() => {
  const q = s => document.querySelector(s)
  if (q('.j-muerte')) return 'muerte'
  if (q('.fin-noche')) return 'fin_noche'
  if (q('.j-golpe')) return q('#j-elegir-victima') ? 'golpe' : 'otro'
  if (q('.j-votacion')) return q('#j-votar') ? 'votar' : 'espera_voto'
  if (q('.j-fin-partida')) return 'fin_partida'
  if (q('.j-veredicto')) return 'veredicto'
  if (q('.j-ronda')) return 'ronda'
  if (q('.j-antesala')) return 'antesala'
  return 'otro'
}
"""


def jugar_un_paso(banco: Banco, n: Noche, s: Sesion, pantalla: str) -> None:
    """Lo que haría una persona con el teléfono en la mano ante la pantalla que tiene enfrente."""
    if pantalla == 'muerte':
        s.tocar('.j-muerte .secundario')
    elif pantalla == 'votar':
        nombre = s.pagina.locator('.j-ficha').first.get_attribute('aria-label').removeprefix('Votar por ')
        votar_por_ui(s, nombre, sellado=False)
    elif pantalla == 'golpe':
        nombre = s.pagina.locator('.j-ficha').first.get_attribute('aria-label').removeprefix('Elegir a ')
        golpear_por_ui(s, nombre)
    elif pantalla == 'ronda' and ronda_actual(banco)['state'] == 'discusion':
        n.adm('admin_control', p_action='force')  # la discusión ya duró lo suficiente
        s.pagina.wait_for_timeout(600)
    elif pantalla == 'fin_partida':
        n.adelantar(banco.db.valor('select pause_seconds from app.event') + 1)
    else:
        s.pagina.wait_for_timeout(250)


@prueba('supabase')
def noche_completa_con_bots(banco: Banco) -> None:
    """Una persona juega solo con su teléfono, rodeada de bots, dos partidas seguidas: nada se atora, todo termina y el ranking cuadra."""
    n = Noche(banco.db, 0, lobby=False, aprobar=False)
    yo = Jugador(n, 'Renata')
    yo.responder('Mariela', 'Se sabe de memoria todos los diálogos de Gossip Girl.')
    n.jugadores.append(yo)
    n.config(rehearsal=True, bots_delay_seconds=1, round_seconds=60, vote_seconds=30, tiebreak_seconds=15, kill_seconds=20, pause_seconds=5)
    n.adm('admin_rehearsal', p_action='bots', p_value=7)
    n.adm('admin_approve_all')
    n.adm('admin_phase', p_phase='lobby')
    yo.llegar()
    n.adm('admin_deal')
    s = telefono(banco, yo)
    t = tele(banco, n)

    vistas: dict[str, int] = {}
    partidas_vistas: set[int] = set()
    limite = time.monotonic() + 300
    while time.monotonic() < limite and len(partidas_vistas) < 2:
        pantalla = s.pagina.evaluate(DETECTAR_PANTALLA)
        vistas[pantalla] = vistas.get(pantalla, 0) + 1
        if pantalla == 'fin_partida':
            partidas_vistas.add(banco.db.valor('select max(number) from app.games'))
            if len(partidas_vistas) >= 2:
                break
        try:
            jugar_un_paso(banco, n, s, pantalla)
        except Exception as e:  # noqa: BLE001
            raise AssertionError(
                f'falló en la pantalla "{pantalla}": {str(e)[:400]}\navisos en pantalla: {s.pagina.locator(".avisos").inner_text()!r}'
                f'\nronda: {ronda_actual(banco)}\nvistas: {vistas}') from e
    else:
        if len(partidas_vistas) < 2:
            raise AssertionError(f'la noche se atoró. Pantallas vistas: {vistas}. Ronda: {ronda_actual(banco)}')

    fin_de_partida = len(partidas_vistas)
    assert fin_de_partida >= 2, vistas
    assert vistas.get('votar', 0) + vistas.get('espera_voto', 0) > 0
    resultados = [f['result'] for f in banco.db.filas('select result from app.games where ended_at is not null order by number')]
    assert resultados and all(r in ('atrapado', 'asesino_gana') for r in resultados), resultados
    # Ninguna ronda quedó abierta a medias, y nadie votó dos veces ni a sí mismo.
    abiertas = banco.db.valor(
        """select count(*) from app.rounds r join app.games g on g.id = r.game_id
            where g.ended_at is not null and r.state <> 'cerrada'
              and r.number < (select max(number) from app.rounds where game_id = g.id)""")
    assert abiertas == 0, 'una ronda quedó abierta a medias'
    print(f'      {len(partidas_vistas)} partidas · {banco.db.valor("select count(*) from app.rounds")} rondas · {banco.db.valor("select count(*) from app.votes")} votos · pantallas: {vistas}')
    assert banco.db.valor('select count(*) from (select round_id, stage, voter_id from app.votes group by 1, 2, 3 having count(*) > 1) x') == 0
    assert banco.db.valor('select count(*) from app.votes where voter_id = target_id') == 0

    n.adm('admin_control', p_action='end_night')
    ver(s, '.fin-noche .j-titulo', 'Se acabó la noche.', seg=9)
    ver(s, '.premios-cifras', '2 partidas')
    ver(t, '.tv-cierre .tv-gran-titulo', 'Se acabó la noche', seg=9)
    ranking = banco.db.llamar('get_state', p_token=yo.token)['ranking']
    assert ranking['games'] == 2 and len(ranking['players']) == 8
    assert sum(p['shots'] for p in ranking['players']) == banco.db.valor('select count(*) from app.shots')
    assert sin_filtraciones(banco, s, n, yo) >= 5
    assert sin_filtraciones(banco, t, n, None) >= 3
    s.sin_errores()
    t.sin_errores()


# =================================================================================================== MODO DEMO
def sembrar_demo(banco: Banco, s: Sesion, nombre: str = 'Tú', bots: int = 7) -> str:
    """Deja la noche repartida dentro del servidor de la página (con el ensayo encendido) y devuelve el token de `nombre`."""
    admin = banco.llamar('admin_login', p_pin=banco.pin)['session']
    banco.llamar('admin_config', p_session=admin, p_changes={
        'rehearsal': True, 'bots_delay_seconds': 2, 'round_seconds': 60, 'vote_seconds': 30, 'tiebreak_seconds': 15, 'kill_seconds': 20, 'pause_seconds': 5,
    })
    token = secrets.token_urlsafe(32)
    banco.llamar('rsvp', p_token=token, p_name=nombre, p_about='Mariela', p_text='Se sabe de memoria todas las temporadas de Gossip Girl.')
    banco.llamar('admin_rehearsal', p_session=admin, p_action='bots', p_value=bots)
    banco.llamar('admin_approve_all', p_session=admin)
    banco.llamar('admin_phase', p_session=admin, p_phase='lobby')
    banco.llamar('check_in', p_token=token, p_code=None)
    banco.llamar('admin_deal', p_session=admin, p_force=False)
    return token


@prueba('demo')
def demo_teléfono_tele_y_admin_comparten_el_servidor(banco: Banco) -> None:
    """Sin Supabase todo corre en el navegador: el mismo servidor sirve al teléfono, a la tele y al admin, y sus datos sobreviven a navegar."""
    s = banco.anfitrion()
    s.pagina.set_default_timeout(TIEMPO)
    token = sembrar_demo(banco, s)
    admin = banco.llamar('admin_login', p_pin=banco.pin)['session']
    llave_tv = banco.llamar('admin_state', p_session=admin)['event']['tv_key']

    # El teléfono: la carta solo se ve mientras se sostiene.
    s.pagina.evaluate("t => localStorage.setItem('mariela.token', t)", token)
    s.ir('', esperar_a='.juego')
    ver(s, '.j-etiqueta', 'Ronda 1', seg=20)
    ver(s, '.pastilla-demo, .juego')  # el aviso de demo no estorba
    pestana_juego(s, 'Mi carta')
    assert cara_montada(s) == 0
    mantener(s)
    ver(s, '#mi-carta-nota', re.compile('Eres (el asesino|inocente)\\.'))
    s.pagina.mouse.up()
    no_hay(s, '#mi-carta .cm-frente svg', seg=3)

    # La tele, en la misma pestaña: ve la misma partida, sin roles.
    s.ir(f'tv#k={llave_tv}', esperar_a='.tv-ronda')
    ver(s, '.tv-ronda .j-etiqueta', 'Ronda 1')
    ver(s, '.tv-vivos', 'Con vida · 8')
    assert 'inocente' not in s.pagina.inner_text('body').lower()

    # El admin: entra con el PIN de demo y ve la partida.
    s.ir('admin', esperar_a='#pin')
    ver(s, '.admin-nota, .j-nota', '000000')
    s.pagina.fill('#pin', banco.pin)
    s.pagina.keyboard.press('Enter')
    s.pagina.wait_for_selector('.admin')
    ver(s, '.ad-estado .j-etiqueta', 'Partida 1 · Ronda 1')
    s.pagina.get_by_role('button', name='Abrir la votación ya').click()
    ver(s, '.ad-grande', 'Votación', seg=9)

    # De vuelta al teléfono: ya se vota, y los bots votan solos.
    s.ir('', esperar_a='.juego')
    ver(s, '.j-votacion .j-etiqueta', 'Votación', seg=20)
    nombre = s.pagina.locator('.j-ficha').first.get_attribute('aria-label').removeprefix('Votar por ')
    votar_por_ui(s, nombre, sellado=False)  # con bots, la ronda puede cerrarse antes de que se pinte el sello
    ver(s, '.j-veredicto, .j-fin-partida, .j-ronda', seg=30)
    s.sin_errores()


@prueba('demo')
def demo_solo_una_pestana_a_la_vez(banco: Banco) -> None:
    """El Postgres del navegador tiene un solo dueño: una segunda pestaña lo dice claro en vez de romperse."""
    s = banco.anfitrion()
    otra = s.pagina.context.new_page()
    otra.goto(s.url)
    otra.wait_for_selector('[role=alert]', timeout=20000)
    assert 'otra pestaña' in otra.inner_text('[role=alert]')
    otra.close()
    s.pagina.reload()
    s.pagina.wait_for_selector('.escena.listo', timeout=20000)  # al cerrar la otra, la primera vuelve a funcionar
    s.sin_errores()


@prueba('demo')
def simulador_de_la_noche(banco: Banco) -> None:
    """/demo: dos teléfonos, la tele y los controles sobre un mismo servidor, con bots; una persona sola prueba la noche entera."""
    s = banco.sesion('escritorio')
    s.pagina.set_default_timeout(20_000)
    s.pagina.set_viewport_size({'width': 1500, 'height': 950})
    s.ir('demo', esperar_a='#sim-nombre')
    ver(s, '.j-titulo', 'Prueba la noche entera, sin nadie más.')
    s.pagina.fill('#sim-nombre', 'Mariela P.')
    s.pagina.select_option('#sim-bots', '8')
    s.pagina.get_by_role('button', name='Preparar la noche').click()
    s.pagina.wait_for_selector('.sim', timeout=60000)
    ver(s, '.sim-titulo', 'Puerta abierta')
    a = s.pagina.frame_locator('iframe[title="Teléfono A"]')
    b = s.pagina.frame_locator('iframe[title="Teléfono B"]')
    tv = s.pagina.frame_locator('iframe[title="La tele"]')
    expect(a.locator('.j-antesala .j-titulo')).to_contain_text('Ya estás dentro, Mariela P.', timeout=30000)
    expect(b.locator('.j-antesala')).to_be_visible(timeout=30000)
    expect(tv.locator('.tv-recibidor')).to_contain_text('La puerta está abierta', timeout=30000)
    expect(tv.locator('.tv-llegados')).to_contain_text('9 de 9')

    s.tocar('#sim-repartir')
    expect(a.locator('.j-ronda .j-etiqueta')).to_contain_text('Ronda 1', timeout=30000)
    expect(b.locator('.j-ronda .j-etiqueta')).to_contain_text('Ronda 1', timeout=30000)
    expect(tv.locator('.tv-ronda .j-etiqueta')).to_contain_text('Ronda 1', timeout=30000)
    ver(s, '.sim-titulo', 'Partida 1 · ronda 1')

    # Mi carta, en el teléfono A, se ve solo mientras se sostiene.
    a.locator('.j-pestanas button', has_text='Mi carta').click()
    caja = a.locator('#mi-carta').bounding_box()
    marco = s.pagina.locator('iframe[title="Teléfono A"]').bounding_box()
    s.pagina.mouse.move(marco['x'] + caja['x'] + caja['width'] / 2, marco['y'] + caja['y'] + caja['height'] / 2)
    s.pagina.mouse.down()
    expect(a.locator('#mi-carta-nota')).to_contain_text(re.compile('Eres (el asesino|inocente)\\.'))
    s.pagina.mouse.up()
    expect(a.locator('#mi-carta .cm-frente svg')).to_have_count(0)

    # Adelantar el juego: se abre la votación en los tres, y el teléfono A vota.
    s.pagina.get_by_role('button', name='Adelantar ▸').click()
    a.locator('.j-pestanas button', has_text='Noche').click()
    expect(a.locator('.j-votacion > .j-etiqueta')).to_contain_text('Votación', timeout=30000)
    expect(tv.locator('.tv-votacion')).to_be_visible(timeout=30000)
    a.locator('.j-ficha').first.click()
    a.locator('#j-votar').click()
    a.locator('#j-confirmar-voto').click()
    expect(a.locator('.j-sellado .j-titulo')).to_contain_text('Voto sellado.')
    # Los bots votan y matan solos; "Adelantar" salta las esperas (el desempate, la elección de la víctima) hasta la siguiente ronda
    # (o una partida nueva, si atraparon al asesino).
    for _ in range(12):
        titulo = texto(s.pagina, '.sim-titulo')
        if re.search(r'ronda 2|Partida 2|terminada', titulo):
            break
        adelantar = s.pagina.get_by_role('button', name='Adelantar ▸')
        if adelantar.is_enabled():
            adelantar.click()
        s.pagina.wait_for_timeout(2500)
    else:
        raise AssertionError(f'la noche no avanzó: {texto(s.pagina, ".sim-titulo")}')
    # La tele siguió a la partida: ya no está en la votación de la ronda 1. El título del simulador va hasta 3 s atrás del servidor, así
    # que un "Adelantar" de más puede haber abierto la votación de la ronda 2: no importa en qué momento de la ronda 2 (o de otra
    # partida) la agarre, y a veces ya enseña el final de la partida.
    siguiente = re.compile(r'Partida [2-9]|Ronda ([2-9]|\d\d)')
    expect(tv.locator('.tv-fin-partida').or_(tv.locator('.tv-contexto', has_text=siguiente)).first).to_be_visible(timeout=30000)
    s.sin_errores()


@prueba('supabase')
def un_servidor_sin_el_juego_instalado_se_avisa(banco: Banco) -> None:
    """Si Supabase todavía no tiene el juego (falta pegar setup.sql) o rechaza la clave, la página lo dice en vez de fallar callada."""
    casos = [
        (404, {'code': 'PGRST202', 'message': 'Could not find the function public.get_state in the schema cache', 'details': None, 'hint': None}, 'setup.sql'),
        (401, {'message': 'Invalid API key', 'hint': 'Double check your Supabase `anon` or `service_role` API key.'}, 'VITE_SUPABASE_ANON_KEY'),
    ]
    for estado, cuerpo, pista in casos:
        s = banco.sesion('Pixel 7')
        s.pagina.set_default_timeout(TIEMPO)

        def responder(estado: int, cuerpo: dict):
            return lambda ruta: ruta.fulfill(status=estado, content_type='application/json', body=json.dumps(cuerpo))

        s.pagina.context.route(SUPABASE_FALSO + '/rest/**', responder(estado, cuerpo))
        s.ir()
        ver(s, '.aviso-config', 'Falta configurar el servidor.')
        ver(s, '.aviso-config', pista)
        # La invitación sigue entera, y al responder el error dice lo mismo (con lo escrito intacto).
        s.tocar('#sello')
        s.pagina.wait_for_selector('.escena.abierta', timeout=8000)
        s.pagina.locator('#form').scroll_into_view_if_needed()
        s.pagina.fill('#nombre', 'Ana')
        s.pagina.fill('#sobre-quien', 'Mariela')
        s.pagina.fill('#secreto', 'Le tiene miedo a los pavos reales.')
        s.tocar('#form button[type=submit]')
        ver(s, '#e-general', pista, seg=12)
        assert s.pagina.input_value('#secreto') == 'Le tiene miedo a los pavos reales.'
        s.sin_errores(rechazos=True)


@prueba('supabase')
def la_tele_no_deja_que_se_apague_la_pantalla(banco: Banco) -> None:
    """La tele pide el candado de pantalla encendida (y lo vuelve a pedir si el sistema lo suelta); doble clic → pantalla completa; el cursor se esconde."""
    n = Noche(banco.db, 4, presentes=False, repartir=False)
    llave = n.adm('admin_state')['event']['tv_key']
    s = banco.sesion('tele')
    s.pagina.set_default_timeout(TIEMPO)
    s.pagina.context.add_init_script("""
      window.__candados = { pedidos: 0, activos: 0, soltar: () => {} }
      const escuchas = new Set()
      Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: {
        request: async tipo => {
          window.__candados.pedidos++
          window.__candados.activos++
          let vivo = true
          const centinela = {
            type: tipo,
            release: async () => { if (vivo) { vivo = false; window.__candados.activos-- } },
            addEventListener: (nombre, f) => { if (nombre === 'release') escuchas.add(f) },
          }
          window.__candados.soltar = () => { if (vivo) { vivo = false; window.__candados.activos--; escuchas.forEach(f => f()) } }
          return centinela
        },
      } })
      window.__pantallaCompleta = 0
      Element.prototype.requestFullscreen = function () { window.__pantallaCompleta++; return Promise.resolve() }
    """)
    s.ir(f'tv#k={llave}', esperar_a='.tv')
    esperar(s.pagina, 'window.__candados.pedidos === 1 && window.__candados.activos === 1', 5)

    # El sistema lo suelta (pestaña oculta, batería baja): al volver a la pantalla se pide otra vez.
    s.pagina.evaluate('window.__candados.soltar()')
    assert s.pagina.evaluate('window.__candados.activos') == 0
    s.pagina.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    esperar(s.pagina, 'window.__candados.pedidos === 2 && window.__candados.activos === 1', 5)

    # Doble clic: pantalla completa.
    s.pagina.dblclick('.tv-marca')
    esperar(s.pagina, 'window.__pantallaCompleta === 1', 5)

    # El cursor se esconde a los 3 s sin moverlo y reaparece al moverlo.
    esperar(s.pagina, "document.documentElement.hasAttribute('data-cursor-quieto')", 6)
    assert s.pagina.evaluate("getComputedStyle(document.querySelector('.tv')).cursor") == 'none'
    s.pagina.mouse.move(200, 200)
    s.pagina.mouse.move(260, 240)
    assert s.pagina.evaluate("!document.documentElement.hasAttribute('data-cursor-quieto')")

    s.sin_errores()


if __name__ == '__main__':
    correr(__doc__ or '')
