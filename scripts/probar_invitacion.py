"""Pruebas de la invitación contra la app compilada, en Chromium con perfiles de celular.

    python scripts/probar_invitacion.py              # compila y prueba
    python scripts/probar_invitacion.py --sin-build  # prueba el dist/ actual
    python scripts/probar_invitacion.py -k rsvp      # solo las pruebas cuyo nombre contiene "rsvp"

Cubre la carga sin errores (con la CSP activa y sin pedir nada fuera del sitio), los metadatos y
la vista previa para WhatsApp, el manifest y los íconos, el service worker y la recarga sin red,
el sobre y la ruptura del sello, el revelado de toda la suite (también tras un salto de scroll),
la cuenta regresiva, la carta que no se deja voltear, el RSVP (errores, sellado y .ics), el
teclado con foco visible, prefers-reduced-motion y 320 px de ancho sin scroll horizontal.

Los perfiles de iPhone y Android emulan pantalla, densidad y tacto sobre Chromium: no sustituyen
probar en Safari de iOS y Chrome de Android de verdad.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from comun import compilar, lanzar_chromium, servir

SITIO_PRUEBA = 'https://mariela-29.prueba'
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

# Se instala antes que la app: junta las violaciones de la CSP y cada propiedad que se anima
# (transiciones y animaciones CSS, y Element.animate), con el elemento que la animó.
VIGIA = """
(() => {
window.__csp = []
document.addEventListener('securitypolicyviolation', e => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
window.__animado = new Set()
const nombre = (el, pseudo = '') => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + [...el.classList].map(c => '.' + c).join('') + pseudo
const anotar = (propiedades, el, pseudo) => propiedades
  .filter(p => !['offset', 'computedOffset', 'easing', 'composite'].includes(p))
  .map(p => p.replace(/[A-Z]/g, m => '-' + m.toLowerCase()))
  .forEach(p => window.__animado.add(`${p} · ${nombre(el, pseudo)}`))
addEventListener('transitionrun', e => anotar([e.propertyName], e.target, e.pseudoElement), true)
addEventListener('animationstart', e => {
  const a = e.target.getAnimations({ subtree: true }).find(a => a.animationName === e.animationName)
  anotar(a ? a.effect.getKeyframes().flatMap(Object.keys) : [e.animationName], e.target, e.pseudoElement)
}, true)
const animar = Element.prototype.animate
Element.prototype.animate = function (fotogramas, opciones) {
  anotar(Array.isArray(fotogramas) ? fotogramas.flatMap(Object.keys) : Object.keys(fotogramas ?? {}), this, '')
  return animar.call(this, fotogramas, opciones)
}
})()
"""

# Lo que cuenta como movimiento para prefers-reduced-motion: desplazar, girar, escalar, barrer o desenfocar.
MOVIMIENTO = {
    'transform', 'translate', 'rotate', 'scale', 'clip-path', 'filter', 'stroke-dashoffset',
    'background-position', 'background-position-x', 'background-position-y', 'top', 'left', 'right', 'bottom',
}

RECORRER = """
async () => {
  const pausa = ms => new Promise(r => setTimeout(r, ms))
  const fondo = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 2
  for (let paso = 0; paso < 80 && !fondo(); paso++) {
    scrollBy(0, innerHeight * 0.6)
    await pausa(220)
  }
  if (!fondo()) throw new Error(`no llegué al final de la página (scrollY ${scrollY})`)
}
"""

# Cada elemento con texto dentro de #carta, con su opacidad efectiva (producto de sus ancestros).
TEXTOS_OCULTOS = """
() => {
  const malos = []
  const vistos = new Set()
  const recorrido = document.createTreeWalker(document.getElementById('carta'), NodeFilter.SHOW_TEXT)
  while (recorrido.nextNode()) {
    const nodo = recorrido.currentNode
    const el = nodo.parentElement
    if (!nodo.textContent.trim() || vistos.has(el)) continue
    vistos.add(el)
    // Ocultos a propósito: estados que aún no ocurren, texto para lectores de pantalla, el sobre ya
    // abierto y el rótulo "Sellando tu secreto", que se apaga al terminar de sellar.
    if (el.closest('[hidden], .sr-only, svg, .push, .sobre-hint, .sellado-t')) continue
    let opacidad = 1
    let oculto = false
    for (let n = el; n; n = n.parentElement) {
      const estilo = getComputedStyle(n)
      opacidad *= parseFloat(estilo.opacity)
      if (estilo.visibility === 'hidden' || estilo.display === 'none') oculto = true
    }
    if (oculto || opacidad < 0.99) malos.push(`"${nodo.textContent.trim().slice(0, 48)}" (opacidad ${opacidad.toFixed(2)})`)
  }
  if (getComputedStyle(document.querySelector('.firma')).clipPath.includes('110%')) malos.push('la firma XOXO sigue recortada')
  return malos
}
"""


@dataclass
class Sesion:
    pagina: Page
    url: str
    tactil: bool
    errores: list[str] = field(default_factory=list)
    peticiones: list[str] = field(default_factory=list)

    def ir(self) -> None:
        self.pagina.goto(self.url)
        self.pagina.wait_for_selector('.escena.listo')

    def tocar(self, selector: str, forzar: bool = False) -> None:
        objetivo = self.pagina.locator(selector)
        objetivo.tap(force=forzar) if self.tactil else objetivo.click(force=forzar)

    def abrir(self) -> float:
        """Rompe el sello y espera a que la portada quede sobre la mesa. Devuelve cuánto tardó."""
        self.ir()
        inicio = time.perf_counter()
        self.tocar('#sello')
        self.pagina.wait_for_selector('.escena.abierta', timeout=6000)
        return time.perf_counter() - inicio

    def recorrer(self) -> None:
        self.pagina.evaluate(RECORRER)
        # La firma termina de escribirse 2.5 s después de llegar.
        self.pagina.wait_for_timeout(2800)

    def sin_errores(self) -> None:
        violaciones = self.pagina.evaluate('window.__csp')
        assert not violaciones, f'violaciones de CSP: {violaciones}'
        assert not self.errores, 'errores:\n' + '\n'.join(self.errores)
        externas = [u for u in self.peticiones if not u.startswith(self.url) and not u.startswith(('data:', 'blob:'))]
        assert not externas, f'pidió cosas fuera del sitio: {externas}'


@dataclass
class Banco:
    playwright: Playwright
    navegador: Browser
    url: str
    contextos: list[BrowserContext] = field(default_factory=list)

    def sesion(self, perfil: str = 'Pixel 7', movimiento: str = 'no-preference', hora: datetime | None = None) -> Sesion:
        if perfil == 'escritorio':
            opciones = {'viewport': {'width': 1280, 'height': 800}, 'device_scale_factor': 1}
        else:
            opciones = {k: v for k, v in self.playwright.devices[perfil].items() if k != 'default_browser_type'}
        contexto = self.navegador.new_context(
            **opciones,
            reduced_motion=movimiento,
            locale='es-MX',
            timezone_id='America/Mexico_City',
            accept_downloads=True,
        )
        self.contextos.append(contexto)
        contexto.add_init_script(VIGIA)
        pagina = contexto.new_page()
        if hora:
            pagina.clock.set_fixed_time(hora)
        s = Sesion(pagina, self.url, tactil=bool(opciones.get('has_touch')))
        pagina.on('console', lambda m: m.type == 'error' and s.errores.append(f'consola: {m.text}'))
        pagina.on('pageerror', lambda e: s.errores.append(f'excepción: {e}'))
        pagina.on('requestfailed', lambda r: s.errores.append(f'falló {r.url}: {r.failure}'))
        pagina.on('response', lambda r: r.status >= 400 and s.errores.append(f'{r.status} {r.url}'))
        pagina.on('request', lambda r: s.peticiones.append(r.url))
        return s

    def cerrar(self) -> None:
        for contexto in self.contextos:
            contexto.close()
        self.contextos.clear()


PRUEBAS: list[Callable[[Banco], None]] = []


def prueba(fn: Callable[[Banco], None]) -> Callable[[Banco], None]:
    PRUEBAS.append(fn)
    return fn


def texto(pagina: Page, selector: str) -> str:
    return ' '.join(pagina.locator(selector).text_content().split())


def esperar(pagina: Page, expresion: str, segundos: float = 5) -> None:
    """Como wait_for_function, que evalúa con eval dentro de la página y la CSP lo bloquea."""
    limite = time.monotonic() + segundos
    while not pagina.evaluate(expresion):
        if time.monotonic() > limite:
            raise AssertionError(f'no se cumplió en {segundos} s: {expresion}')
        pagina.wait_for_timeout(100)


# ---------------------------------------------------------------- carga y metadatos


@prueba
def carga_limpia(banco: Banco) -> None:
    """Carga sin errores, con la CSP de producción y todo servido desde el propio sitio."""
    s = banco.sesion('Pixel 7')
    s.ir()
    csp = s.pagina.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content')
    assert csp and "script-src 'self'" in csp, 'falta la CSP en el HTML de producción'
    fuentes = s.pagina.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => `${f.family} ${f.style}`)")
    for esperada in ['Bodoni Moda italic', 'Bodoni Moda normal', 'Jost normal']:
        assert esperada in fuentes, f'no cargó {esperada}: {fuentes}'
    s.sin_errores()


@prueba
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
    if imagen.startswith('http'):
        assert imagen.endswith('/og.jpg') and meta['og:url'] + 'og.jpg' == imagen, f'og:image y og:url no coinciden: {imagen}'
    else:
        print('      aviso: og:image es relativa (compila con VITE_SITE_URL para que WhatsApp la encuentre)')
    info = s.pagina.evaluate("""async () => {
      const r = await fetch('/og.jpg')
      const blob = await r.blob()
      const img = await createImageBitmap(blob)
      return { tipo: r.headers.get('content-type'), bytes: blob.size, ancho: img.width, alto: img.height }
    }""")
    assert info['tipo'] == 'image/jpeg', info
    assert (info['ancho'], info['alto']) == (1200, 630), info
    assert info['bytes'] < 300 * 1024, f"og.jpg pesa {info['bytes'] / 1024:.0f} KB"
    s.sin_errores()


@prueba
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
    s.sin_errores()


@prueba
def funciona_sin_red(banco: Banco) -> None:
    """Con el service worker listo, la invitación recarga y se abre sin conexión."""
    s = banco.sesion('Pixel 7')
    s.ir()
    # Desde la primera visita: el service worker instala el precache y toma el control.
    esperar(s.pagina, 'navigator.serviceWorker.controller !== null', 15)
    s.pagina.context.set_offline(True)
    try:
        inicio = time.perf_counter()
        s.pagina.reload()
        s.pagina.wait_for_selector('.escena.listo')
        s.tocar('#sello')
        s.pagina.wait_for_selector('.escena.abierta', timeout=6000)
        assert s.pagina.evaluate("document.fonts.check('italic 400 16px \"Bodoni Moda\"')"), 'sin red no cargó Bodoni Moda'
        print(f'      sin red: abrió en {time.perf_counter() - inicio:.1f} s')
    finally:
        s.pagina.context.set_offline(False)
    s.sin_errores()


# ---------------------------------------------------------------- el sobre


@prueba
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
    s.sin_errores()


@prueba
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
    # Nada del sobre queda encima de la portada.
    encima = p.evaluate("""() => {
      const r = document.getElementById('portada').getBoundingClientRect()
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest('#portada') !== null
    }""")
    assert encima, 'algo tapa la portada'
    assert texto(p, '#remate') == '…y esta noche alguien no va a salir viva.'
    s.sin_errores()


@prueba
def revelado_completo(banco: Banco) -> None:
    """Bajando por la página, cada texto de la suite termina visible."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    s.recorrer()
    ocultos = s.pagina.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)
    s.sin_errores()


@prueba
def revelado_tras_salto(banco: Banco) -> None:
    """Si el scroll salta hasta el final, las piezas que nunca entraron a la vista también se revelan."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    s.pagina.evaluate('scrollTo(0, document.documentElement.scrollHeight)')
    s.pagina.wait_for_timeout(2800)
    ocultos = s.pagina.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)
    s.sin_errores()


# ---------------------------------------------------------------- la carta y el reloj


@prueba
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
    s.sin_errores()


@prueba
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
    # La carta solo tiene dorso: el rol no está en el cliente.
    assert texto(p, '#carta-juego .sr-only') == 'Intentar voltear tu carta'
    grabado = texto(p, '#carta-juego').lower()
    assert 'inocente' not in grabado and 'asesino' not in grabado, grabado
    assert p.locator('#carta-juego').get_attribute('aria-describedby') == 'reloj'
    p.wait_for_timeout(3300)
    assert texto(p, '#aviso') == '', 'el aviso no se borró'
    s.sin_errores()


# ---------------------------------------------------------------- RSVP


@prueba
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
    s.sin_errores()


@prueba
def rsvp_sellado_y_calendario(banco: Banco) -> None:
    """El secreto se tacha y se sella, llega la confirmación y el .ics es el del prototipo. En Fase 1 no se envía nada."""
    s = banco.sesion('Pixel 7')
    s.abrir()
    p = s.pagina
    secreto = 'Una vez se quedó dormida en el cine y roncó.'
    p.locator('#form').scroll_into_view_if_needed()
    p.fill('#nombre', 'Ana')
    p.fill('#sobre-quien', 'Mariela')
    p.fill('#secreto', secreto)
    antes = len(s.peticiones)
    s.tocar('#form button[type=submit]')
    assert p.locator('#form').is_hidden()
    assert p.locator('#sellado-txt span').count() == len(secreto.split())
    p.wait_for_selector('#sellado.tachar.estampado.hecho', timeout=4000)
    p.wait_for_selector('#aceptado:not([hidden])')
    assert texto(p, '#aceptado h3') == 'Aceptaste, Ana.'
    assert p.evaluate('document.activeElement.id') == 'aceptado'
    assert s.peticiones[antes:] == [], f'el RSVP hizo peticiones: {s.peticiones[antes:]}'

    with p.expect_download() as descarga:
        s.tocar('#calendario')
    archivo = descarga.value
    assert archivo.suggested_filename == 'mariela-29.ics'
    contenido = Path(archivo.path()).read_bytes().decode('utf-8')
    assert contenido == ICS, f'el .ics no coincide:\n{contenido!r}'
    s.sin_errores()


# ---------------------------------------------------------------- accesibilidad y pantallas chicas


@prueba
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
    s.sin_errores()


@prueba
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
    p.wait_for_selector('#aceptado:not([hidden])', timeout=3000)
    p.wait_for_timeout(800)
    animado = p.evaluate('[...window.__animado]')
    movimiento = sorted(a for a in animado if a.split(' · ')[0] in MOVIMIENTO)
    assert not movimiento, 'con movimiento reducido se animó:\n' + '\n'.join(movimiento)
    ocultos = p.evaluate(TEXTOS_OCULTOS)
    assert not ocultos, 'siguen ocultos:\n' + '\n'.join(ocultos)
    s.sin_errores()


@prueba
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
    p.wait_for_selector('#aceptado:not([hidden])', timeout=4000)
    assert desborde() <= 0, f'el sellado se desborda {desborde()} px'
    ancho = p.evaluate("Math.max(...[...document.querySelectorAll('#sellado-txt span, #aceptado h3')].map(e => e.getBoundingClientRect().right))")
    assert ancho <= p.evaluate('innerWidth'), f'el texto sellado llega a {ancho:.0f} px'
    s.sin_errores()


# ---------------------------------------------------------------- corrida


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-build', action='store_true', help='no compilar; probar el dist/ actual')
    parser.add_argument('-k', dest='filtro', default='', help='solo las pruebas cuyo nombre contiene este texto')
    args = parser.parse_args()

    if not args.sin_build:
        compilar({'VITE_SITE_URL': SITIO_PRUEBA})
    elegidas = [fn for fn in PRUEBAS if args.filtro in fn.__name__]
    fallas = 0
    with servir() as url, sync_playwright() as p:
        navegador = lanzar_chromium(p)
        banco = Banco(p, navegador, url + '/')
        print(f'· {len(elegidas)} pruebas · Chromium {navegador.version} · {url}')
        for fn in elegidas:
            inicio = time.perf_counter()
            try:
                fn(banco)
            except Exception as error:  # noqa: BLE001
                fallas += 1
                print(f'  ✗ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
                detalle = str(error) if isinstance(error, AssertionError) and str(error) else traceback.format_exc(limit=3)
                print('      ' + detalle.strip().replace('\n', '\n      '))
            else:
                print(f'  ✓ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
            finally:
                banco.cerrar()
        navegador.close()
    print(f'{len(elegidas) - fallas} de {len(elegidas)} pasaron.')
    sys.exit(1 if fallas else 0)


if __name__ == '__main__':
    main()
