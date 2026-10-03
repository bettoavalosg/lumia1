"""El arnés de las pruebas de interfaz: compila la app, la sirve y la maneja en Chromium con perfiles de celular.

Hay dos entornos, y las mismas pruebas corren en los dos:

  supabase  El build de producción (con CSP y service worker), hablando con la API de Supabase por `fetch`.
            Aquí "Supabase" es scripts/servidor_local.py: la misma API (PostgREST) sobre un Postgres real y
            las mismas migraciones. Playwright desvía las llamadas a https://ejemplo.supabase.co hacia él.
  demo      El build sin configurar: el Postgres corre dentro del navegador (PGlite).

Los teléfonos emulan pantalla, densidad y tacto de un iPhone o un Android sobre Chromium: no sustituyen probar en
Safari de iOS y Chrome de Android de verdad.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, sync_playwright

from comun import RAIZ, compilar, lanzar_chromium, servir
from motor_pg import BaseDeDatos, ErrorApi
from servidor_local import CLAVE_ANON, servir_api

SITIO_PRUEBA = 'https://mariela-29.prueba'
SUPABASE_FALSO = 'https://ejemplo.supabase.co'
MESA = '#07050a'
PIN_DEMO = '000000'
PIN_LOCAL = '123456'

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
// Lo que el servidor le respondió a esta pestaña, función por función: para comprobar que no llega nada que no debería.
window.__rpc = []
const traer = window.fetch
window.fetch = async function (entrada, opciones) {
  const respuesta = await traer.call(this, entrada, opciones)
  try {
    const m = /\\/rpc\\/([a-z_]+)/.exec(typeof entrada === 'string' ? entrada : entrada.url)
    if (m) {
      respuesta.clone().text().then(cuerpo => {
        window.__rpc.push({ fn: m[1], estado: respuesta.status, cuerpo })
        if (window.__rpc.length > 400) window.__rpc.shift()
      }).catch(() => {})
    }
  } catch {}
  return respuesta
}
const animar = Element.prototype.animate
Element.prototype.animate = function (fotogramas, opciones) {
  anotar(Array.isArray(fotogramas) ? fotogramas.flatMap(Object.keys) : Object.keys(fotogramas ?? {}), this, '')
  return animar.call(this, fotogramas, opciones)
}
})()
"""

# Un servidor de Realtime de mentiras, dentro de la página: habla el protocolo de Phoenix que usa Supabase (versión 2.0.0,
# arreglos JSON y la trama binaria de los broadcast) lo justo para que el cliente real se una al canal `noche`.
# Con `window.__realtimeActivo` apagado (lo normal) el enchufe falla como si no hubiera red, y la app cae a consultar.
# Playwright tiene `route_web_socket`, pero su manejador corre dentro del bucle de eventos y no puede llamar a la API síncrona.
REALTIME_FALSO = """
(() => {
const Nativo = window.WebSocket
const es = url => /\\/realtime\\/v1\\/websocket/.test(String(url))
const vivos = new Set()
const cuenta = { intentos: 0, unidos: 0, latidos: 0 }
const codificar = new TextEncoder()
class Falso extends EventTarget {
  constructor(url) {
    super()
    Object.assign(this, { url: String(url), protocol: '', extensions: '', bufferedAmount: 0, binaryType: 'blob', readyState: 0 })
    this.onopen = this.onmessage = this.onclose = this.onerror = null
    cuenta.intentos++
    setTimeout(() => {
      if (this.readyState !== 0) return
      if (!window.__realtimeActivo) {
        this.readyState = 3
        this.avisar('error', new Event('error'))
        this.avisar('close', new CloseEvent('close', { code: 1006, reason: 'sin red', wasClean: false }))
        return
      }
      this.readyState = 1
      vivos.add(this)
      this.avisar('open', new Event('open'))
    }, 20)
  }
  avisar(tipo, evento) {
    const f = this['on' + tipo]
    if (typeof f === 'function') f.call(this, evento)
    this.dispatchEvent(evento)
  }
  recibir(arreglo) {
    setTimeout(() => this.readyState === 1 && this.avisar('message', new MessageEvent('message', { data: JSON.stringify(arreglo) })), 5)
  }
  send(datos) {
    if (this.readyState !== 1) throw new DOMException('El enchufe no está abierto', 'InvalidStateError')
    if (typeof datos !== 'string') return
    const [unirse, ref, tema, evento] = JSON.parse(datos)
    if (evento === 'phx_join') { cuenta.unidos++; (this.temas ??= []).push(tema); this.recibir([unirse, ref, tema, 'phx_reply', { status: 'ok', response: {} }]) }
    else if (evento === 'heartbeat') { cuenta.latidos++; this.recibir([null, ref, 'phoenix', 'phx_reply', { status: 'ok', response: {} }]) }
    else if (evento === 'phx_leave') this.recibir([unirse, ref, tema, 'phx_reply', { status: 'ok', response: {} }])
  }
  close(codigo = 1000, motivo = '') {
    if (this.readyState === 3) return
    this.readyState = 3
    vivos.delete(this)
    setTimeout(() => this.avisar('close', new CloseEvent('close', { code: codigo, reason: motivo, wasClean: codigo === 1000 })), 0)
  }
  // Un broadcast del servidor: en binario (como llegan de verdad con la versión 2.0.0 del protocolo) o en JSON.
  broadcast(tema, evento, carga, binario) {
    if (this.readyState !== 1) return
    if (!binario) return this.recibir([null, null, tema, 'broadcast', { type: 'broadcast', event: evento, payload: carga }])
    const t = codificar.encode(tema), e = codificar.encode(evento), c = codificar.encode(JSON.stringify(carga))
    const trama = new Uint8Array(5 + t.length + e.length + c.length)
    trama.set([4, t.length, e.length, 0, 1], 0)
    trama.set(t, 5)
    trama.set(e, 5 + t.length)
    trama.set(c, 5 + t.length + e.length)
    setTimeout(() => this.readyState === 1 && this.avisar('message', new MessageEvent('message', { data: this.binaryType === 'arraybuffer' ? trama.buffer : new Blob([trama]) })), 5)
  }
}
for (const [nombre, valor] of Object.entries({ CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 })) Falso[nombre] = Falso.prototype[nombre] = valor
window.WebSocket = new Proxy(Nativo, { construct: (objetivo, args, nuevo) => (es(args[0]) ? new Falso(...args) : Reflect.construct(objetivo, args, nuevo)) })
window.__realtime = {
  estado: () => ({ ...cuenta, abiertos: vivos.size, temas: [...vivos].flatMap(v => v.temas ?? []) }),
  ping: (binario = true) => vivos.forEach(v => v.broadcast('realtime:noche', 'cambio', {}, binario)),
  cortar: () => [...vivos].forEach(v => v.close(1006, 'corte')),
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
    // Ocultos a propósito: estados que aún no ocurren, texto para lectores de pantalla, el sobre ya abierto, el
    // rótulo "Sellando tu secreto" (se apaga al terminar) y los números del reloj (ruedan cada segundo).
    if (el.closest('[hidden], .sr-only, svg, .push, .sobre-hint, .sellado-t, .reloj')) continue
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


def texto(pagina: Page, selector: str) -> str:
    return ' '.join((pagina.locator(selector).first.text_content() or '').split())


def esperar(pagina: Page, expresion: str, segundos: float = 5) -> None:
    """Como wait_for_function, que evalúa con eval dentro de la página y la CSP lo bloquea."""
    limite = time.monotonic() + segundos
    while not pagina.evaluate(expresion):
        if time.monotonic() > limite:
            raise AssertionError(f'no se cumplió en {segundos} s: {expresion}')
        pagina.wait_for_timeout(100)


def espera_error(codigo: str, fn: Callable[[], object]) -> ErrorApi:
    try:
        fn()
    except ErrorApi as e:
        assert e.codigo == codigo, f'esperaba {codigo!r} y llegó {e.codigo!r}: {e.mensaje}'
        return e
    raise AssertionError('debió fallar y no falló')


@dataclass
class Sesion:
    """Una pestaña de un teléfono (o de escritorio) con lo necesario para vigilarla."""

    banco: Banco
    pagina: Page
    url: str
    tactil: bool
    errores: list[str] = field(default_factory=list)
    peticiones: list[str] = field(default_factory=list)

    def ir(self, ruta: str = '', esperar_a: str = '.escena.listo') -> None:
        self.pagina.goto(self.url.rstrip('/') + '/' + ruta.lstrip('/'))
        if esperar_a:
            self.pagina.wait_for_selector(esperar_a)

    def tocar(self, selector: str, forzar: bool = False) -> None:
        objetivo = self.pagina.locator(selector).first
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

    def sin_errores(self, ignorar_red: bool = False, rechazos: bool = False) -> None:
        """Ni excepciones, ni errores de consola, ni CSP violada, ni peticiones fuera del sitio. `rechazos` deja pasar las respuestas 4xx que la
        prueba provocó a propósito (un código de puerta malo, una llave falsa, un servidor sin instalar…): el navegador las anota como error."""
        violaciones = self.pagina.evaluate('window.__csp')
        assert not violaciones, f'violaciones de CSP: {violaciones}'
        errores = [
            e for e in self.errores
            if not (ignorar_red and 'ERR_INTERNET_DISCONNECTED' in e) and not (rechazos and (re.match(r'4\d\d ', e) or re.search(r'status of 4\d\d', e)))
        ]
        assert not errores, 'errores:\n' + '\n'.join(errores)
        propios = (self.url, SUPABASE_FALSO, 'data:', 'blob:')
        externas = [u for u in self.peticiones if not u.startswith(propios)]
        assert not externas, f'pidió cosas fuera del sitio: {externas}'


@dataclass
class Banco:
    playwright: Playwright
    navegador: Browser
    url: str
    modo: str
    db: BaseDeDatos | None = None
    api: str | None = None
    contextos: list[BrowserContext] = field(default_factory=list)
    sesiones: list[Sesion] = field(default_factory=list)

    # -- la noche, sin importar dónde corra el servidor -----------------------------------------------------
    def llamar(self, fn: str, **args):
        """Llama a una función de la API. En `supabase` va directo al Postgres del servidor local; en `demo`, al PGlite de la primera pestaña."""
        if self.db is not None:
            return self.db.llamar(fn, **args)
        pagina = self.sesiones[0].pagina
        try:
            return pagina.evaluate("([fn, args]) => window.__marielaDemo.rpc(fn, args)", [fn, args])
        except Exception as e:  # noqa: BLE001
            m = re.search(r'ErrorJuego: (.*)\n', str(e))
            raise ErrorApi('error', m.group(1) if m else str(e)) from None

    def anfitrion(self, perfil: str = 'Pixel 7') -> Sesion:
        """La primera pestaña, ya con el servidor a la mano. En `demo` el Postgres vive dentro de ella, así que hay que abrirla antes de sembrar nada y seguir usándola."""
        s = self.sesion(perfil)
        s.ir()
        self.esperar_backend(s.pagina)
        return s

    @property
    def pin(self) -> str:
        return PIN_LOCAL if self.db is not None else PIN_DEMO

    def esperar_backend(self, pagina: Page, segundos: float = 90) -> None:
        if self.modo == 'demo':
            esperar(pagina, 'window.__marielaDemo !== undefined', segundos)

    # -- sesiones --------------------------------------------------------------------------------------------
    def sesion(
        self,
        perfil: str = 'Pixel 7',
        movimiento: str = 'no-preference',
        hora: datetime | None = None,
        permisos: list[str] | None = None,
        realtime: bool = False,
    ) -> Sesion:
        if perfil == 'escritorio':
            opciones = {'viewport': {'width': 1280, 'height': 800}, 'device_scale_factor': 1}
        elif perfil == 'tele':
            opciones = {'viewport': {'width': 1920, 'height': 1080}, 'device_scale_factor': 1}
        else:
            opciones = {k: v for k, v in self.playwright.devices[perfil].items() if k != 'default_browser_type'}
        contexto = self.navegador.new_context(
            **opciones,
            reduced_motion=movimiento,
            locale='es-MX',
            timezone_id='America/Mexico_City',
            accept_downloads=True,
            permissions=permisos or [],
        )
        self.contextos.append(contexto)
        contexto.add_init_script(VIGIA)
        if os.environ.get('AXE'):  # accesibilidad: axe-core disponible en cada página (ver probar_accesibilidad.py)
            contexto.add_init_script(path=str(RAIZ / 'node_modules' / 'axe-core' / 'axe.min.js'))
        if self.modo == 'supabase':
            self._desviar(contexto, realtime)
        pagina = contexto.new_page()
        if hora:
            pagina.clock.set_fixed_time(hora)
        s = Sesion(self, pagina, self.url, tactil=bool(opciones.get('has_touch')))
        pagina.on('console', lambda m: m.type == 'error' and s.errores.append(f'consola: {m.text}'))
        pagina.on('pageerror', lambda e: s.errores.append(f'excepción: {e}'))
        pagina.on('requestfailed', lambda r: s.errores.append(f'falló {r.url}: {r.failure}'))
        pagina.on('response', lambda r: r.status >= 400 and s.errores.append(f'{r.status} {r.url}'))
        pagina.on('request', lambda r: s.peticiones.append(r.url))
        self.sesiones.append(s)
        return s

    def _desviar(self, contexto: BrowserContext, realtime: bool) -> None:
        """Las llamadas a "Supabase" van al servidor local. Realtime está caído (la app consulta cada 3 s) salvo que la sesión pida un canal vivo."""
        api = self.api or ''

        def rest(ruta: Route) -> None:
            destino = api + ruta.request.url[len(SUPABASE_FALSO):]
            respuesta = ruta.fetch(url=destino)
            ruta.fulfill(response=respuesta)

        contexto.route(SUPABASE_FALSO + '/rest/**', rest)
        if realtime:
            contexto.add_init_script('window.__realtimeActivo = true')
        contexto.add_init_script(REALTIME_FALSO)

    def cerrar(self) -> None:
        for contexto in self.contextos:
            try:
                contexto.unroute_all(behavior='ignoreErrors')  # una consulta a medias no debe tumbar el cierre
                contexto.close()
            except Exception:  # noqa: BLE001
                pass
        self.contextos.clear()
        self.sesiones.clear()

    def preparar(self) -> None:
        """Deja el servidor como recién migrado antes de cada prueba (en `demo` cada sesión nueva ya arranca limpia)."""
        if self.db is not None:
            self.db.reiniciar()


Prueba = Callable[[Banco], None]
PRUEBAS: list[tuple[Prueba, tuple[str, ...]]] = []


def prueba(*modos: str) -> Callable[[Prueba], Prueba]:
    """Registra una prueba. Sin argumentos corre en todos los entornos; `@prueba('supabase')` la limita a uno."""

    def registrar(fn: Prueba) -> Prueba:
        PRUEBAS.append((fn, modos or ('supabase', 'demo')))
        return fn

    return registrar


def compilar_entorno(modo: str) -> None:
    """Compila la app para un entorno de pruebas: `supabase` → dist-sb/ (configurada contra un "Supabase" falso), `demo` → dist/ (sin configurar)."""
    if modo == 'supabase':
        compilar(
            {'VITE_SITE_URL': SITIO_PRUEBA, 'VITE_SUPABASE_URL': SUPABASE_FALSO, 'VITE_SUPABASE_ANON_KEY': CLAVE_ANON, 'VITE_VAPID_PUBLIC_KEY': ''},
            salida='dist-sb',
        )
    else:
        compilar({'VITE_SITE_URL': SITIO_PRUEBA, 'VITE_SUPABASE_URL': '', 'VITE_SUPABASE_ANON_KEY': ''}, salida='dist')


@contextlib.contextmanager
def entorno(modo: str, playwright: Playwright, construir: bool) -> Iterator[Banco]:
    if modo == 'supabase':
        if construir:
            compilar_entorno(modo)
        with BaseDeDatos(pin=PIN_LOCAL) as db, servir_api(db) as api, servir(RAIZ / 'dist-sb') as url:
            navegador = lanzar_chromium(playwright)
            try:
                yield Banco(playwright, navegador, url + '/', modo, db, api)
            finally:
                navegador.close()
    else:
        if construir:
            compilar_entorno(modo)
        with servir(RAIZ / 'dist') as url:
            navegador = lanzar_chromium(playwright)
            try:
                yield Banco(playwright, navegador, url + '/', modo)
            finally:
                navegador.close()


def correr(descripcion: str, epilogo_modos: tuple[str, ...] = ('supabase', 'demo'), modulos: tuple[str, ...] = ('__main__',)) -> None:
    """La línea de comandos común a los scripts de prueba de interfaz."""
    parser = argparse.ArgumentParser(description=descripcion, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-build', action='store_true', help='no compilar; usar dist/ y dist-sb/ como están')
    parser.add_argument('--modo', choices=['supabase', 'demo', 'ambos'], default='ambos', help='en qué entorno correr (por defecto, los dos)')
    parser.add_argument('-k', dest='filtro', default='', help='solo las pruebas cuyo nombre coincide con esta expresión (por ejemplo: -k "carta|voto")')
    parser.add_argument('-x', dest='parar', action='store_true', help='detenerse en la primera falla')
    args = parser.parse_args()

    modos = [m for m in ('supabase', 'demo') if args.modo in (m, 'ambos') and m in epilogo_modos]
    fallas = corridas = 0
    with sync_playwright() as p:
        for modo in modos:
            elegidas = [fn for fn, ms in PRUEBAS if modo in ms and fn.__module__ in modulos and re.search(args.filtro, fn.__name__)]  # (las de otros archivos que se importen solo prestan utilidades)
            if not elegidas:
                continue
            with entorno(modo, p, not args.sin_build) as banco:
                print(f'· [{modo}] {len(elegidas)} pruebas · Chromium {banco.navegador.version} · {banco.url}')
                for fn in elegidas:
                    corridas += 1
                    inicio = time.perf_counter()
                    try:
                        banco.preparar()
                        fn(banco)
                    except Exception as error:  # noqa: BLE001
                        fallas += 1
                        print(f'  ✗ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
                        detalle = str(error) if isinstance(error, AssertionError) and str(error) else traceback.format_exc(limit=-4)
                        print('      ' + detalle.strip().replace('\n', '\n      '))
                        if args.parar:
                            break
                    else:
                        print(f'  ✓ {fn.__name__}  ({time.perf_counter() - inicio:.1f} s)')
                    finally:
                        banco.cerrar()
            if args.parar and fallas:
                break
    print(f'{corridas - fallas} de {corridas} pasaron.')
    sys.exit(1 if fallas else 0)
