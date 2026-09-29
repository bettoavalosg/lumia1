"""Compara la app con el prototipo aprobado (prototipo/invitacion-mariela-v3.html): mismo texto, mismo aspecto.

    python scripts/comparar_prototipo.py                  # compila y compara
    python scripts/comparar_prototipo.py --sin-build
    python scripts/comparar_prototipo.py --guardar CARPETA  # guarda capturas y mapas de diferencias

Texto: cada palabra de la página, más las que solo salen al interactuar (las negativas de la
carta, los errores del formulario y la confirmación), tiene que coincidir.
Aspecto: con movimiento reducido y el reloj detenido, captura el sobre, la portada y la página
completa en los dos y mide qué fracción de píxeles cambia a la vista.
El prototipo pide sus fuentes a Google; aquí recibe las mismas que la app sirve, para comparar
tipografía contra tipografía.
"""

from __future__ import annotations

import argparse
import base64
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Browser, Page, Route, sync_playwright

from comun import ESPERAR_ANIMACIONES, RAIZ, compilar, lanzar_chromium, servir
from probar_invitacion import RECORRER

PROTOTIPO = RAIZ / 'prototipo' / 'invitacion-mariela-v3.html'
HORA = datetime(2026, 10, 1, 12, 0, tzinfo=timezone(timedelta(hours=-6)))
# Un píxel "cambia a la vista" si algún canal difiere en más de 16 de 255.
UMBRAL = 0.005

DIFERENCIA = """
async ({ a, b, mapa }) => {
  const cargar = async src => createImageBitmap(await (await fetch(src)).blob())
  const [ia, ib] = await Promise.all([cargar(a), cargar(b)])
  const ancho = Math.min(ia.width, ib.width)
  const alto = Math.min(ia.height, ib.height)
  const lienzo = new OffscreenCanvas(ancho, alto)
  const ctx = lienzo.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(ia, 0, 0)
  const da = ctx.getImageData(0, 0, ancho, alto).data
  ctx.clearRect(0, 0, ancho, alto)
  ctx.drawImage(ib, 0, 0)
  const salida = ctx.getImageData(0, 0, ancho, alto)
  const db = salida.data
  let distintos = 0
  for (let i = 0; i < da.length; i += 4) {
    const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2]))
    if (d > 16) {
      distintos++
      db.set([255, 48, 48, 255], i)
    } else {
      const gris = (db[i] + db[i + 1] + db[i + 2]) / 9
      db.set([gris, gris, gris, 255], i)
    }
  }
  let png = null
  if (mapa) {
    ctx.putImageData(salida, 0, 0)
    const blob = await lienzo.convertToBlob({ type: 'image/png' })
    png = await new Promise(r => { const f = new FileReader(); f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(blob) })
  }
  return { fraccion: distintos / (ancho * alto), tamanos: [[ia.width, ia.height], [ib.width, ib.height]], png }
}
"""


# Texto de un elemento, nodo por nodo. textContent pegaría palabras de bloques vecinos: el
# prototipo tiene saltos de línea entre etiquetas y JSX no, aunque en pantalla se vean igual.
TEXTO = """
selector => {
  const recorrido = document.createTreeWalker(document.querySelector(selector), NodeFilter.SHOW_TEXT)
  const partes = []
  while (recorrido.nextNode()) partes.push(recorrido.currentNode.textContent)
  return partes.join(' ').split(/\\s+/).filter(Boolean).join(' ')
}
"""


def palabras(texto: str) -> Counter[str]:
    return Counter(texto.split())


def recorrer(pagina: Page, url: str) -> dict:
    """El mismo recorrido en la app y en el prototipo: capturas primero, interacción después."""
    capturas: dict[str, bytes] = {}
    pagina.clock.set_fixed_time(HORA)
    pagina.goto(url)
    pagina.wait_for_selector('.escena.listo')
    pagina.evaluate(ESPERAR_ANIMACIONES)
    capturas['sobre'] = pagina.screenshot()

    pagina.locator('#sello').tap()
    pagina.wait_for_selector('.escena.abierta', timeout=6000)
    pagina.evaluate(ESPERAR_ANIMACIONES)
    capturas['portada'] = pagina.screenshot()

    pagina.evaluate(RECORRER)
    pagina.wait_for_timeout(1500)
    pagina.evaluate(ESPERAR_ANIMACIONES)
    capturas['pagina'] = pagina.screenshot(full_page=True)
    estatico = pagina.evaluate(TEXTO, '#carta')

    dinamico: list[str] = []
    for _ in range(4):
        pagina.locator('#carta-juego').tap()
        dinamico.append(pagina.evaluate(TEXTO, '#aviso'))
    enviar = pagina.locator('#form button[type=submit]')
    enviar.tap()
    dinamico += [pagina.evaluate(TEXTO, f'#e-{c}') for c in ('nombre', 'quien', 'secreto')]
    pagina.fill('#nombre', 'Ana')
    pagina.fill('#sobre-quien', 'ana')
    enviar.tap()
    dinamico.append(pagina.evaluate(TEXTO, '#e-quien'))
    pagina.fill('#sobre-quien', 'Mariela')
    pagina.fill('#secreto', 'Se sabe de memoria todas las temporadas de Gossip Girl.')
    enviar.tap()
    pagina.wait_for_selector('#aceptado:not([hidden])', timeout=4000)
    dinamico += [pagina.evaluate(TEXTO, '#sellado-txt'), pagina.evaluate(TEXTO, '#aceptado')]
    return {'estatico': estatico, 'dinamico': dinamico, 'capturas': capturas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-build', action='store_true', help='no compilar; usar el dist/ actual')
    parser.add_argument('--guardar', type=Path, help='carpeta donde guardar capturas y mapas de diferencias')
    args = parser.parse_args()

    if not args.sin_build:
        compilar()
    fallas: list[str] = []
    fuentes_app = (RAIZ / 'src' / 'styles' / 'fuentes.css').read_text()
    with servir() as url_app, servir(PROTOTIPO.parent, PROTOTIPO.name) as url_proto, sync_playwright() as p:
        fuentes = fuentes_app.replace('url("/fonts/', f'url("{url_app}/fonts/')

        def enrutar(ruta: Route) -> None:
            destino = ruta.request.url
            if destino.startswith('https://fonts.googleapis.com/'):
                ruta.fulfill(status=200, content_type='text/css', body=fuentes)
            elif destino.startswith('http://127.0.0.1'):
                ruta.continue_()
            else:
                ruta.abort()

        navegador: Browser = lanzar_chromium(p)
        resultados = {}
        for nombre, url in [('app', url_app + '/'), ('prototipo', f'{url_proto}/{PROTOTIPO.name}')]:
            contexto = navegador.new_context(
                viewport={'width': 412, 'height': 915}, device_scale_factor=1, is_mobile=True, has_touch=True,
                reduced_motion='reduce', locale='es-MX', timezone_id='America/Mexico_City', service_workers='block',
            )
            contexto.route('**/*', enrutar)
            resultados[nombre] = recorrer(contexto.new_page(), url)
            contexto.close()
        app, proto = resultados['app'], resultados['prototipo']

        print('· Texto')
        a, b = palabras(app['estatico']), palabras(proto['estatico'])
        if a == b:
            print(f'  ✓ las {sum(a.values())} palabras de la página coinciden')
        else:
            fallas.append('texto de la página')
            print(f'  ✗ solo en la app: {dict(a - b)}\n    solo en el prototipo: {dict(b - a)}')
        if app['dinamico'] == proto['dinamico']:
            print(f'  ✓ los {len(app["dinamico"])} textos de interacción coinciden (negativas, errores, confirmación)')
        else:
            fallas.append('textos de interacción')
            for x, y in zip(app['dinamico'], proto['dinamico']):
                if x != y:
                    print(f'  ✗ app: {x!r}\n    prototipo: {y!r}')

        print('· Aspecto (movimiento reducido, 412 px de ancho)')
        comparador = navegador.new_page()
        if args.guardar:
            args.guardar.mkdir(parents=True, exist_ok=True)
        for estado in ['sobre', 'portada', 'pagina']:
            datos = {k: 'data:image/png;base64,' + base64.b64encode(v['capturas'][estado]).decode() for k, v in resultados.items()}
            r = comparador.evaluate(DIFERENCIA, {'a': datos['app'], 'b': datos['prototipo'], 'mapa': bool(args.guardar)})
            (aw, ah), (bw, bh) = r['tamanos']
            alto = '' if ah == bh else f'  (alto: app {ah} px, prototipo {bh} px)'
            ok = r['fraccion'] < UMBRAL and ah == bh
            if not ok:
                fallas.append(f'aspecto: {estado}')
            print(f"  {'✓' if ok else '✗'} {estado:<8} {r['fraccion'] * 100:.2f} % de píxeles distintos{alto}")
            if args.guardar:
                for k, v in resultados.items():
                    (args.guardar / f'{estado}-{k}.png').write_bytes(v['capturas'][estado])
                (args.guardar / f'{estado}-diferencia.png').write_bytes(base64.b64decode(r['png']))
        navegador.close()

    if fallas:
        sys.exit(f'Difiere del prototipo en: {", ".join(fallas)}')
    print('Igual al prototipo.')


if __name__ == '__main__':
    main()
