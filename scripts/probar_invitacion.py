"""Pruebas de la invitación contra la app compilada, en Chromium con perfiles de celular.

    python scripts/probar_invitacion.py                   # compila y prueba en los dos entornos
    python scripts/probar_invitacion.py --modo supabase   # solo el build de producción contra la API (servidor local)
    python scripts/probar_invitacion.py --sin-build       # con los dist/ que ya tengas
    python scripts/probar_invitacion.py -k rsvp           # solo las pruebas cuyo nombre contiene "rsvp"

Cubre la carga sin errores (con la CSP activa y sin pedir nada fuera del sitio), los metadatos y la vista previa
para WhatsApp, el manifest y los íconos, el service worker y la recarga sin red, el sobre y la ruptura del sello,
el revelado de toda la suite (también tras un salto de scroll), la cuenta regresiva, la carta que no se deja
voltear, el RSVP de verdad (guarda al invitado, sella el secreto, entrega la llave y se recupera desde otro
dispositivo), la dirección que solo aparece a su hora, el teclado con foco visible, prefers-reduced-motion y 320 px
de ancho sin scroll horizontal.
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from banco import (
    MOVIMIENTO,
    SUPABASE_FALSO,
    TEXTOS_OCULTOS,
    Banco,
    correr,
    esperar,
    prueba,
    texto,
)

MESA = '#07050a'
CDMX = timezone(timedelta(hours=-6))  # Sin horario de verano desde 2022
INICIO = datetime(2026, 10, 24, 18, 0, tzinfo=CDMX)

NEGATIVAS = ['Todavía no.', 'Dije que todavía no.', 'Se voltea el 24 a las 6:00 pm. Ni un minuto antes.', 'Qué ganas de saber, ¿no?']
ICS = '\r\n'.join([
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//XOXO//Mariela 29//ES',
    'BEGIN:VEVENT',
    'UID:mariela-29-20261024@xoxo',
    'DTSTAMP:20260928T000000Z',
    'DTSTART:20261025T000000Z',
    'DTEND:20261025T060000Z',
    'SUMMARY:Mariela cumple 29',
    'DESCRIPTION:All black. La dirección se revela unos días antes. XOXO',
    'END:VEVENT',
    'END:VCALENDAR',
])


def contar(banco: Banco, tabla: str, donde: str = 'true') -> int:
    """Cuántas filas hay en una tabla privada del servidor, mirando la base directamente."""
    if banco.db is not None:
        return banco.db.valor(f'select count(*) from app.{tabla} where {donde}')
    pagina = banco.sesiones[0].pagina
    return pagina.evaluate("([q]) => window.__marielaDemo.sql(q, []).then(r => Number(r[0].n))", [f'select count(*) as n from app.{tabla} where {donde}'])


def admin(banco: Banco) -> str:
    return banco.llamar('admin_login', p_pin=banco.pin)['session']


# ---------------------------------------------------------------- carga y metadatos


@prueba()
def carga_limpia(banco: Banco) -> None:
    """Carga sin errores, con la CSP de producción y todo servido desde el propio sitio."""
    s = banco.sesion('Pixel 7')
    s.ir()
    csp = s.pagina.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content')
    assert csp and "script-src 'self'" in csp, 'falta la CSP en el HTML de producción'
    assert "'unsafe-eval'" not in csp and "'unsafe-inline'" not in csp.split('script-src')[1].split(';')[0], 'la CSP de scripts es más laxa de lo debido'
    fuentes = s.pagina.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => `${f.family} ${f.style}`)")
    for esperada in ['Bodoni Moda italic', 'Bodoni Moda normal', 'Jost normal']:
        assert esperada in fuentes, f'no cargó {esperada}: {fuentes}'
    banco.esperar_backend(s.pagina)
    s.pagina.wait_for_timeout(1500)
    s.sin_errores()


@prueba()
def la_invitacion_aparece_antes_que_el_servidor(banco: Banco) -> None:
    """El sobre se pinta sin esperar a que el servidor responda (ni siquiera si está caído)."""
    s = banco.sesion('Pixel 7')
    if banco.modo == 'supabase':
        # Nada contesta: la invitación igual tiene que verse y no debe soltar errores raros.
        s.pagina.context.unroute(SUPABASE_FALSO + '/rest/**')
        s.pagina.context.route(SUPABASE_FALSO + '/rest/**', lambda ruta: ruta.abort())
    t0 = time.perf_counter()
    s.ir()
    assert time.perf_counter() - t0 < 4, 'la invitación tardó demasiado en verse'
    assert texto(s.pagina, '.sobre-hint') == 'Toca el sello'
    s.tocar('#sello')
    s.pagina.wait_for_selector('.escena.abierta', timeout=6000)
    s.recorrer()
    assert s.pagina.locator('#form').count() == 1, 'sin servidor la invitación debe seguir completa'


@prueba()
def metadatos_y_vista_previa(banco: Banco) -> None:
    """Título, descripción y og:image absoluta de 1200×630 y menos de 300 KB (límite de WhatsApp)."""
    s = banco.sesion('Pixel 7')
    s.ir()
    meta = s.pagina.evaluate("""() => Object.fromEntries([...document.querySelectorAll('meta[property], meta[name]')]
      .map(m => [m.getAttribute('property') || m.getAttribute('name'), m.content]))""")
    assert s.pagina.title() == 'Mariela cumple 29'
    assert s.pagina.locator('html').get_attribute('lang') == 'es'
    assert meta['og:title'] == 'Hay una fiesta en la Ciudad de México…'
    assert meta['og:description'] == meta['description'] == '…y esta noche alguien no va a salir viva. XOXO'
    assert meta['theme-color'] == MESA
    assert meta['twitter:card'] == 'summary_large_image'
    imagen = meta['og:image']
    assert imagen.startswith('https://') and imagen.endswith('/og.jpg') and meta['og:url'] + 'og.jpg' == imagen, f'og:image y og:url no coinciden: {imagen}'
    info = s.pagina.evaluate("""async () => {
      const r = await fetch('/og.jpg')
      const blob = await r.blob()
      const img = await createImageBitmap(blob)
      return { tipo: r.headers.get('content-type'), bytes: blob.size, ancho: img.width, alto: img.height }
    }""")
    assert info['tipo'] == 'image/jpeg', info
    assert (info['ancho'], info['alto']) == (1200, 630), info
    assert info['bytes'] < 300 * 1024, f"og.jpg pesa {info['bytes'] / 1024:.0f} KB"


@prueba()
def manifest_e_iconos(banco: Banco) -> None:
    """El manifest describe una PWA instalable y cada ícono mide lo que dice."""
    s = banco.sesion('Pixel 7')
    s.ir()
    info = s.pagina.evaluate("""async () => {
      const enlace = document.querySelector('link[rel=manifest]').href
      const manifest = await (await fetch(enlace)).json()
      const medir = async src => {
        const img = await createImageBitmap(await (await fetch(src)).blob())
        return `${img.width}x${img.height}`
      }
      const iconos = await Promise.all(manifest.icons.map(async i => ({ ...i, real: await medir(i.src) })))
      const apple = await medir(document.querySelector('link[rel=apple-touch-icon]').href)
      const favicon = await medir(document.querySelector('link[rel=icon]').href)
      return { manifest, iconos, apple, favicon }
    }""")
    m = info['manifest']
    assert m['name'] == 'Mariela cumple 29' and m['short_name'] == 'Mariela 29', m
    assert m['display'] == 'standalone' and m['start_url'] == '/' and m['lang'] == 'es-MX', m
    assert m['theme_color'] == m['background_color'] == MESA, m
    for icono in info['iconos']:
        assert icono['real'] == icono['sizes'], f"{icono['src']} mide {icono['real']}, el manifest dice {icono['sizes']}"
    tamanos = {(i['sizes'], i.get('purpose', 'any')) for i in info['iconos']}
    assert {('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable')} <= tamanos, tamanos
    assert info['apple'] == '180x180', info['apple']
    assert info['favicon'] == '32x32', info['favicon']


@prueba('supabase')
def funciona_sin_red(banco: Banco) -> None:
    """Con el service worker listo, la invitación recarga y se abre sin conexión (el RSVP avisa que no hay red)."""
    s = banco.sesion('Pixel 7')
    s.ir()
    # Desde la primera visita: el service worker instala el precache y toma el control.
    esperar(s.pagina, 'navigator.serviceWorker.controller !== null', 15)
    # Playwright resuelve las rutas desviadas por su cuenta, sin pasar por el modo sin conexión del navegador: la API se corta aparte.
    s.pagina.context.unroute(SUPABASE_FALSO + '/rest/**')
    s.pagina.context.route(SUPABASE_FALSO + '/**', lambda ruta: ruta.abort('internetdisconnected'))
    s.pagina.context.set_offline(True)
    try:
        inicio = time.perf_counter()
        s.pagina.reload()
        s.pagina.wait_for_selector('.escena.listo')
        s.tocar('#sello')
        s.pagina.wait_for_selector('.escena.abierta', timeout=6000)
        assert s.pagina.evaluate("document.fonts.check('italic 400 16px \"Bodoni Moda\"')"), 'sin red no cargó Bodoni Moda'
        s.recorrer()
        s.pagina.fill('#nombre', 'Ana')
        s.pagina.fill('#sobre-quien', 'Luis')
        s.pagina.fill('#secreto', 'Sin red no se puede sellar.')
        s.tocar('#form button[type=submit]')
        s.pagina.wait_for_selector('#e-general:not(:empty)', timeout=25000)
        assert 'conexión' in texto(s.pagina, '#e-general'), texto(s.pagina, '#e-general')
        assert s.pagina.locator('#form').is_visible(), 'al fallar el envío el formulario tiene que volver'
        assert s.pagina.input_value('#secreto') == 'Sin red no se puede sellar.', 'se perdió lo que escribió'
        print(f'      sin red: abrió y avisó en {time.perf_counter() - inicio:.1f} s')
    finally:
        s.pagina.context.set_offline(False)
    s.sin_errores(ignorar_red=True)


# ---------------------------------------------------------------- el sobre


@prueba()
def sobre_cerrado(banco: Banco) -> None:
    """La notificación anónima, el sello y nada más: sin scroll y con la suite inerte."""
    s = banco.sesion('iPhone 15')
    s.ir()
    p = s.pagina
    assert texto(p, '.push-meta b') == 'Remitente desconocido'
    assert texto(p, '.push-meta span') == 'ahora'
    assert texto(p, '.push-texto > span:last-child') == 'Tengo algo para ti. Rompe el sello.'
    assert texto(p, '.sobre-hint') == 'Toca el sello'
    assert p.locator('#sello').get_attribute('aria-label') == 'Romper el sello y abrir la invitación'
    assert p.evaluate("document.documentElement.style.overflow") == 'hidden'
    assert p.evaluate("document.getElementById('suite').inert && document.getElementById('portada').inert")
    p.mouse.wheel(0, 800)
    p.wait_for_timeout(300)
    assert p.evaluate('scrollY') == 0, 'con el sobre cerrado la página no debe moverse'
    # Tocar la notificación señala el sello.
    s.tocar('#push')
    assert p.evaluate("document.getElementById('sello').getAnimations().length") > 0, 'la notificación no señaló el sello'


@prueba()
def romper_el_sello(banco: Banco) -> None:
    """Al romper el sello sale la portada, el foco va al título y se libera el scroll."""
    s = banco.sesion('Pixel 7')
    duracion = s.abrir()
    p = s.pagina
    assert 2.4 < duracion < 4.5, f'la apertura tardó {duracion:.1f} s (esperado ~2.8 s)'
    enfocado = p.evaluate('document.activeElement.textContent.trim()')
    assert enfocado == 'Hay una fiesta en la Ciudad de México…', f'el foco quedó en: {enfocado!r}'
    assert p.evaluate("document.documentElement.style.overflow") == ''
    assert p.evaluate("!document.getElementById('suite').inert && !document.getElementById('portada').inert")
    encima = p.evaluate("""() => {
      const r = document.getElementById('portada').getBoundingClientRect()
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest('#portada') !== null
    }""")
    assert encima, 'algo tapa la portada'
    assert texto(p, '#remate') == '…y esta noche alguien no va a salir viva.'


@prueba()
def quien_ya_abrio_el_sobre_no_lo_rompe_otra_vez(banco: Banco) -> None:
    """La segunda visita en el mismo teléfono entra directo a la portada."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    s.pagina.reload()
    s.pagina.wait_for_selector('.escena.abierta')
    assert s.pagina.locator('#sello').count() == 1 and not s.pagina.locator('#sello').is_visible()
    assert s.pagina.evaluate("document.documentElement.style.overflow") == ''
    assert texto(s.pagina, '#portada h1') == 'Hay una fiesta en la Ciudad de México…'
    s.recorrer()
    assert not s.pagina.evaluate(TEXTOS_OCULTOS)


@prueba()
def revelado_completo(banco: Banco) -> None:
    """Bajando por la página, cada texto de la suite termina visible."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    s.recorrer()
    ocultos = s.pagina.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)
    banco.esperar_backend(s.pagina)
    s.sin_errores()


@prueba()
def revelado_tras_salto(banco: Banco) -> None:
    """Si el scroll salta hasta el final, las piezas que nunca entraron a la vista también se revelan."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    s.pagina.evaluate('scrollTo(0, document.documentElement.scrollHeight)')
    s.pagina.wait_for_timeout(2800)
    ocultos = s.pagina.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)


# ---------------------------------------------------------------- la carta y el reloj


@prueba()
def cuenta_regresiva(banco: Banco) -> None:
    """El reloj cuenta hacia el sábado 24 a las 6:00 pm de la Ciudad de México."""
    s = banco.sesion('Pixel 7', hora=INICIO - timedelta(days=1, hours=1, minutes=1, seconds=1))
    s.ir()
    p = s.pagina
    assert texto(p, '#reloj') == 'Se voltea en 1 día, 1 hora, 1 minuto y 1 segundo.', texto(p, '#reloj')
    p.clock.set_fixed_time(INICIO - timedelta(seconds=2))
    esperar(p, "document.getElementById('reloj').textContent.includes('2 segundos')")
    assert texto(p, '#reloj') == 'Se voltea en 0 horas, 0 minutos y 2 segundos.', texto(p, '#reloj')
    p.clock.set_fixed_time(INICIO + timedelta(seconds=1))
    esperar(p, "document.getElementById('reloj').textContent.startsWith('Ya')")
    assert texto(p, '#reloj') == 'Ya se puede voltear. Corre.'


@prueba()
def la_carta_no_se_voltea(banco: Banco) -> None:
    """Cada intento recibe una negativa distinta, la carta se resiste y regresa, y su frente no existe."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    # La carta flota sin parar: Playwright nunca la vería "estable", así que se toca forzando.
    p.evaluate("document.getElementById('carta-juego').scrollIntoView({ block: 'center' })")
    p.wait_for_timeout(1200)
    for intento in range(5):
        s.tocar('#carta-juego', forzar=True)
        esperado = NEGATIVAS[min(intento, len(NEGATIVAS) - 1)]
        assert texto(p, '#aviso') == esperado, f'intento {intento + 1}: {texto(p, "#aviso")!r}'
        if intento == 0:
            p.wait_for_timeout(200)
            giro = p.evaluate("getComputedStyle(document.querySelector('.carta-giro')).transform")
            assert giro != 'none', 'la carta no se movió al intentar voltearla'
        p.wait_for_timeout(800)
    assert p.evaluate("getComputedStyle(document.querySelector('.carta-giro')).transform") == 'none', 'la carta no regresó'
    assert texto(p, '#carta-juego .sr-only') == 'Intentar voltear tu carta'
    grabado = texto(p, '#carta-juego').lower()
    assert 'inocente' not in grabado and 'asesino' not in grabado, grabado
    assert p.locator('#carta-juego').get_attribute('aria-describedby') == 'reloj'
    p.wait_for_timeout(3300)
    assert texto(p, '#aviso') == '', 'el aviso no se borró'


# ---------------------------------------------------------------- RSVP


@prueba()
def rsvp_errores(banco: Banco) -> None:
    """Sin datos, cada campo dice qué falta; el secreto tiene que ser de otra persona."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    p.locator('#form button[type=submit]').scroll_into_view_if_needed()
    s.tocar('#form button[type=submit]')
    assert texto(p, '#e-nombre') == 'Escribe tu nombre.'
    assert texto(p, '#e-quien') == 'Escribe de quién es el secreto.'
    assert texto(p, '#e-secreto') == 'Escribe el secreto.'
    for campo in ['#nombre', '#sobre-quien', '#secreto']:
        assert p.locator(campo).get_attribute('aria-invalid') == 'true', campo
    assert p.evaluate('document.activeElement.id') == 'nombre'

    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', '  ÁNA ')
    s.tocar('#form button[type=submit]')
    assert texto(p, '#e-nombre') == ''
    assert p.locator('#nombre').get_attribute('aria-invalid') is None
    assert texto(p, '#e-quien') == 'Tiene que ser de otro invitado.'
    assert p.evaluate('document.activeElement.id') == 'sobre-quien'

    p.fill('#sobre-quien', 'Mariela')
    s.tocar('#form button[type=submit]')
    assert p.evaluate('document.activeElement.id') == 'secreto'
    p.fill('#secreto', 'hola')
    assert texto(p, '#contador') == '4 / 280'
    assert p.locator('#secreto').get_attribute('maxlength') == '280'
    assert contar(banco, 'players') == 0, 'un formulario con errores no debe guardar nada'


@prueba()
def rsvp_guarda_al_invitado_y_sella_el_secreto(banco: Banco) -> None:
    """El secreto se tacha y se sella mientras viaja; el servidor guarda al invitado con su secreto pendiente y entrega su llave."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    secreto = 'Una vez se quedó dormida en el cine y roncó.'
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', secreto)
    s.tocar('#form button[type=submit]')
    assert p.locator('#form').is_hidden()
    assert p.locator('#sellado-txt span').count() == len(secreto.split())
    p.wait_for_selector('#sellado.tachar.estampado.hecho', timeout=25000)
    p.wait_for_selector('#aceptado:not([hidden])')
    assert texto(p, '#aceptado h3') == 'Aceptaste, Ana.'
    assert texto(p, '#aceptado > p') == 'Tu secreto quedó sellado. Nadie va a saber que fuiste tú.'
    assert p.evaluate('document.activeElement.id') == 'aceptado'

    # El servidor guardó todo, con el secreto pendiente y sin el token en claro.
    assert contar(banco, 'players', "name = 'Ana'") == 1
    assert contar(banco, 'secrets', f"status = 'pendiente' and about_name = 'Mariela' and text = '{secreto}'") == 1
    token = p.evaluate("localStorage.getItem('mariela.token')")
    assert token and len(token) >= 40
    assert contar(banco, 'players', f"token_hash = sha256(convert_to('{token}', 'UTF8'))") == 1, 'el servidor guarda el hash del token'

    # Le entrega su llave para recuperar el lugar en otro teléfono.
    llave = texto(p, '.llave-c')
    assert re.fullmatch(r'[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}', llave), llave
    assert p.evaluate("localStorage.getItem('mariela.llave')") == llave
    assert 'Tu secreto está en revisión' in texto(p, '.secreto-estado')

    # Volver a abrir la invitación en el mismo teléfono no repite la ceremonia: ya está aceptada.
    p.reload()
    p.wait_for_selector('#aceptado:not([hidden])', timeout=20000)
    assert texto(p, '#aceptado h3') == 'Aceptaste, Ana.'
    assert p.locator('#form').is_hidden() and p.locator('#sellado').is_hidden()
    assert texto(p, '.llave-c') == llave


@prueba()
def rsvp_calendario(banco: Banco) -> None:
    """El .ics que se descarga es el del prototipo, línea por línea."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'Le tiene miedo a los pavos reales.')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    with p.expect_download() as descarga:
        s.tocar('#calendario')
    archivo = descarga.value
    assert archivo.suggested_filename == 'mariela-29.ics'
    contenido = Path(archivo.path()).read_bytes().decode('utf-8')
    assert contenido == ICS, f'el .ics no coincide:\n{contenido!r}'


@prueba()
def rsvp_rechazado_por_el_servidor_deshace_el_sello(banco: Banco) -> None:
    """Un nombre repetido no entra: el sello se deshace y el error queda en el campo del nombre, con lo escrito intacto."""
    s = banco.anfitrion()
    banco.llamar('rsvp', p_token=secrets.token_urlsafe(32), p_name='Ana', p_about='Luis', p_text='algo')
    s.abrir()
    p = s.pagina
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'ANA')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'Otro secreto cualquiera.')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#e-nombre:not(:empty)', timeout=25000)
    assert 'ya respondió' in texto(p, '#e-nombre'), texto(p, '#e-nombre')
    assert p.locator('#form').is_visible() and p.locator('#sellado').is_hidden()
    assert p.evaluate('document.activeElement.id') == 'nombre'
    assert p.input_value('#secreto') == 'Otro secreto cualquiera.'
    assert p.evaluate("localStorage.getItem('mariela.token')") is None, 'un RSVP rechazado no deja un token huérfano'
    assert contar(banco, 'players') == 1


@prueba()
def recuperar_el_lugar_con_la_llave(banco: Banco) -> None:
    """Desde otro teléfono (o la app instalada), nombre y llave devuelven el lugar; el dispositivo anterior lo pierde."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'Ana María')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'Nunca ha visto Titanic completa.')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    llave = texto(p, '.llave-c')
    token_viejo = p.evaluate("localStorage.getItem('mariela.token')")
    assert token_viejo

    # El otro teléfono: el mismo navegador, pero sin el token (así el servidor puede vivir dentro de la página, en `demo`).
    p.evaluate("localStorage.removeItem('mariela.token')")
    s.ir()
    p.wait_for_selector('.escena.abierta', timeout=15000)  # el sobre ya se rompió en este navegador: la portada aparece abierta
    p.locator('.recuperar .enlace').scroll_into_view_if_needed()
    p.locator('.recuperar .enlace').click()
    p.fill('#rec-nombre', 'ana maria')
    p.fill('#rec-llave', 'AAAA-AAAA')
    p.get_by_role('button', name='Entrar').click()
    p.wait_for_selector('.recuperar-campos .error:not(:empty)', timeout=15000)
    assert 'no coinciden' in texto(p, '.recuperar-campos .error')
    p.fill('#rec-llave', llave.lower())
    p.get_by_role('button', name='Entrar').click()
    p.wait_for_selector('#aceptado:not([hidden])', timeout=15000)
    assert texto(p, '#aceptado h3') == 'Aceptaste, Ana María.'
    token_nuevo = p.evaluate("localStorage.getItem('mariela.token')")
    assert token_nuevo and token_nuevo != token_viejo

    # El teléfono anterior ya no es el dueño de ese lugar.
    p.evaluate("t => localStorage.setItem('mariela.token', t)", token_viejo)
    s.ir()
    p.wait_for_selector('.escena.abierta', timeout=15000)
    p.locator('#form').scroll_into_view_if_needed()
    p.wait_for_timeout(1500)
    assert p.locator('#form').is_visible(), 'el token viejo sigue funcionando'


@prueba()
def enlace_de_llave_entra_solo(banco: Banco) -> None:
    """El enlace que da el admin (?nombre=…&llave=…) recupera el lugar sin tocar nada."""
    s = banco.anfitrion()
    r = banco.llamar('rsvp', p_token=secrets.token_urlsafe(32), p_name='Sofía Reyes', p_about='Luis', p_text='algo gracioso')
    s.ir(f"?nombre=Sof%C3%ADa%20Reyes&llave={r['recovery_key']}")
    s.pagina.wait_for_selector('.escena.listo')
    s.tocar('#sello')
    s.pagina.wait_for_selector('.escena.abierta', timeout=8000)
    s.pagina.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    assert texto(s.pagina, '#aceptado h3') == 'Aceptaste, Sofía Reyes.'
    assert 'llave=' not in s.pagina.url, 'la llave no debe quedar en la URL'


@prueba()
def la_direccion_solo_aparece_a_su_hora(banco: Banco) -> None:
    """La dirección no está en ningún lado del cliente hasta que el servidor la revela."""
    direccion = 'Calle Falsa 123, Col. Roma Norte, CDMX'
    s = banco.anfitrion()
    sesion_admin = admin(banco)
    if banco.modo == 'demo':
        banco.llamar('admin_config', p_session=sesion_admin, p_changes={'rehearsal': True})
    banco.llamar('admin_config', p_session=sesion_admin, p_changes={'address': direccion, 'address_reveal_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()})
    s.abrir()
    s.recorrer()
    p = s.pagina
    assert direccion not in p.content() and direccion not in p.inner_text('body'), 'la dirección llegó al cliente antes de tiempo'
    assert 'Se revela unos días antes.' in texto(p, '.datos')
    # El admin la revela: en la siguiente consulta aparece, con su enlace a Maps.
    banco.llamar('admin_config', p_session=sesion_admin, p_changes={'address_reveal_at': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    p.reload()
    p.wait_for_selector('.escena.abierta', timeout=15000)
    p.wait_for_selector('.datos dd:has-text("Calle Falsa 123")', timeout=20000)
    assert 'Ya no es un secreto' in texto(p, '.datos')
    assert 'google.com/maps' in p.locator('.datos a').get_attribute('href')


@prueba()
def secreto_rechazado_se_reemplaza(banco: Banco) -> None:
    """Si el admin rechaza el secreto, su autor ve el aviso y escribe otro."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'Uno demasiado pesado.')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    sesion_admin = admin(banco)
    banco.llamar('admin_state', p_session=sesion_admin)
    lista = banco.llamar('admin_state', p_session=sesion_admin)['secrets']
    banco.llamar('admin_secret', p_session=sesion_admin, p_id=lista[0]['id'], p_status='rechazado')
    p.reload()
    p.wait_for_selector('.reemplazo', timeout=20000)
    assert 'no pasó la revisión' in texto(p, '.reemplazo-t')
    p.fill('#rem-quien', 'Mariela')
    p.fill('#rem-secreto', 'Uno más suave.')
    p.get_by_role('button', name='Enviar otro').click()
    p.wait_for_selector('.reemplazo', state='detached', timeout=15000)
    assert 'en revisión' in texto(p, '.secreto-estado')
    assert contar(banco, 'secrets', "status = 'pendiente' and text = 'Uno más suave.'") == 1


# ---------------------------------------------------------------- accesibilidad y pantallas chicas


@prueba()
def teclado_y_foco_visible(banco: Banco) -> None:
    """Todo se usa con teclado, en orden, con el foco siempre visible."""
    s = banco.sesion('escritorio')
    s.ir()
    p = s.pagina

    def foco() -> dict:
        return p.evaluate("""() => {
          const el = document.activeElement
          const estilo = getComputedStyle(el)
          return { id: el.id || el.className, visible: el.matches(':focus-visible') && estilo.outlineStyle !== 'none' && parseFloat(estilo.outlineWidth) >= 2 }
        }""")

    p.keyboard.press('Tab')
    assert foco() == {'id': 'sello', 'visible': True}, foco()
    # Con el sobre cerrado, el tabulador no se mete a la suite.
    p.keyboard.press('Tab')
    assert not p.evaluate("!!document.activeElement.closest('#suite, #portada')"), foco()
    p.keyboard.press('Shift+Tab')
    assert foco()['id'] == 'sello', foco()
    p.keyboard.press('Enter')
    p.wait_for_selector('.escena.abierta', timeout=6000)
    assert p.evaluate("document.activeElement.tagName") == 'H1'
    for esperado in ['carta-juego', 'nombre', 'sobre-quien', 'secreto', 'primario escalon']:
        p.keyboard.press('Tab')
        actual = foco()
        assert actual == {'id': esperado, 'visible': True}, f'esperaba {esperado}, llegó {actual}'


@prueba()
def movimiento_reducido(banco: Banco) -> None:
    """Con prefers-reduced-motion, en todo el recorrido: solo fundidos, nada se desplaza y no hay atmósfera animada."""
    s = banco.sesion('Pixel 7', movimiento='reduce')
    s.ir()
    p = s.pagina
    p.wait_for_timeout(1600)
    infinitas = p.evaluate("document.getAnimations().filter(a => a.effect.getComputedTiming().endTime === Infinity).length")
    assert infinitas == 0, f'{infinitas} animaciones infinitas con movimiento reducido'
    inicio = time.perf_counter()
    s.tocar('#sello')
    p.wait_for_selector('.escena.abierta', timeout=3000)
    assert time.perf_counter() - inicio < 1.5, 'la apertura con movimiento reducido debe ser corta'
    s.recorrer()
    s.tocar('#carta-juego')
    s.tocar('#form button[type=submit]')
    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'Se sabe todas las coreografías de Gossip Girl.')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    p.wait_for_timeout(800)
    animado = p.evaluate('[...window.__animado]')
    movimiento = sorted(a for a in animado if a.split(' · ')[0] in MOVIMIENTO)
    assert not movimiento, 'con movimiento reducido se animó:\n' + '\n'.join(movimiento)
    ocultos = p.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)


@prueba()
def pantalla_de_320(banco: Banco) -> None:
    """A 320 px de ancho nada se sale de la pantalla, ni con un secreto de una sola palabra larguísima."""
    s = banco.sesion('iPhone SE')
    p = s.pagina

    def desborde() -> int:
        return p.evaluate('document.documentElement.scrollWidth - innerWidth')

    s.ir()
    assert desborde() <= 0, f'el sobre se desborda {desborde()} px'
    s.tocar('#sello')
    p.wait_for_selector('.escena.abierta', timeout=6000)
    s.recorrer()
    assert desborde() <= 0, f'la suite se desborda {desborde()} px'
    p.fill('#nombre', 'María Fernanda de los Ángeles')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', 'jajajajajajajajajajajajajajajajajajajajajajajajajaja')
    s.tocar('#form button[type=submit]')
    p.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
    assert desborde() <= 0, f'el sellado se desborda {desborde()} px'
    ancho = p.evaluate("Math.max(...[...document.querySelectorAll('#sellado-txt span, #aceptado h3, .llave-c')].map(e => e.getBoundingClientRect().right))")
    assert ancho <= p.evaluate('innerWidth'), f'el texto sellado llega a {ancho:.0f} px'


if __name__ == '__main__':
    correr(__doc__)
