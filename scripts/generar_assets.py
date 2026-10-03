"""Genera la vista previa para WhatsApp (og:image) y los íconos de la PWA desde la app compilada.

    python scripts/generar_assets.py              # compila, renderiza y vuelve a compilar
    python scripts/generar_assets.py --sin-build  # renderiza sobre el dist/ que ya existe

Todo sale de la app real: el mismo sobre y el mismo sello de cera (sprite SVG, tokens OKLCH
y Bodoni Moda autoalojada). Si cambia el diseño, basta con volver a correr este script.
Escribe en public/: og.jpg, pwa-192.png, pwa-512.png, pwa-maskable-512.png,
apple-touch-icon.png y favicon-32.png.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright

from comun import ESPERAR_ANIMACIONES, PUBLICO, compilar, lanzar_chromium, servir

# La primera impresión en WhatsApp: el sobre cerrado con el sello, sin notificación ni instrucciones.
CSS_OG = """
.push, .sobre-hint, .pastilla-demo { display: none !important; }
.escena { --w: min(84vw, 25rem, 50svh); --ey: 50%; height: 100svh; }
body::after, .bruma, .destello { animation: none !important; }
"""

# Para los íconos solo queda el sello, sobre un lienzo propio.
CSS_ICONO = """
#raiz, .pastilla-demo { visibility: hidden !important; }
body::before, body::after { display: none !important; }
html, body { background: transparent !important; }
#lienzo-icono { position: fixed; inset: 0; z-index: 99; display: grid; place-items: center; }
"""

# Luz de vela sobre la mesa, como detrás del sobre.
FONDO = 'radial-gradient(circle at 50% 42%, oklch(0.2 0.016 310), var(--color-mesa) 72%)'


@dataclass(frozen=True)
class Icono:
    archivo: str
    lado: int
    sello: float  # diámetro del sello como fracción del lado
    fondo: bool = True
    sombra: bool = True


ICONOS = [
    Icono('pwa-192.png', 192, 0.76),
    Icono('pwa-512.png', 512, 0.76),
    # Android puede recortar el ícono hasta un círculo del 80 %: el sello queda holgado dentro.
    Icono('pwa-maskable-512.png', 512, 0.64),
    # iOS no admite transparencia y redondea las esquinas por su cuenta.
    Icono('apple-touch-icon.png', 180, 0.72),
    # Pestaña del navegador: sin fondo ni sombra, el sello lo más grande posible.
    Icono('favicon-32.png', 32, 1.0, fondo=False, sombra=False),
]

LIENZO = """
({ diametro, fondo, sombra }) => {
  document.getElementById('lienzo-icono')?.remove()
  const lienzo = document.createElement('div')
  lienzo.id = 'lienzo-icono'
  lienzo.style.background = fondo
  const sello = document.querySelector('#sello .sello-entero').cloneNode(true)
  sello.querySelectorAll('.destello, .grieta, .grieta-luz').forEach(n => n.remove())
  sello.removeAttribute('class')
  const d = diametro
  sello.style.cssText = `width: ${d}px; height: ${d}px; overflow: visible;` + (sombra
    ? `filter: drop-shadow(0 ${d * 0.045}px ${d * 0.07}px oklch(0 0 0 / .6)) drop-shadow(0 ${d * 0.012}px ${d * 0.02}px oklch(0 0 0 / .45));`
    : '')
  lienzo.append(sello)
  document.body.append(lienzo)
}
"""


def abrir_sobre(pagina: Page, url: str) -> None:
    pagina.goto(url)
    pagina.wait_for_selector('.escena.listo')


def generar_og(navegador, url: str) -> None:  # noqa: ANN001
    pagina = navegador.new_page(viewport={'width': 1200, 'height': 630}, device_scale_factor=1)
    abrir_sobre(pagina, url)
    pagina.add_style_tag(content=CSS_OG)
    pagina.evaluate(ESPERAR_ANIMACIONES)
    destino = PUBLICO / 'og.jpg'
    pagina.screenshot(path=destino, type='jpeg', quality=90)
    pagina.close()
    print(f'  og.jpg                1200×630  {destino.stat().st_size / 1024:.0f} KB')


def generar_iconos(navegador, url: str) -> None:  # noqa: ANN001
    pagina = navegador.new_page(viewport={'width': 512, 'height': 512}, device_scale_factor=1)
    abrir_sobre(pagina, url)
    pagina.evaluate(ESPERAR_ANIMACIONES)
    pagina.add_style_tag(content=CSS_ICONO)
    for icono in ICONOS:
        pagina.set_viewport_size({'width': icono.lado, 'height': icono.lado})
        pagina.evaluate(
            LIENZO,
            {'diametro': icono.lado * icono.sello, 'fondo': FONDO if icono.fondo else 'transparent', 'sombra': icono.sombra},
        )
        destino = PUBLICO / icono.archivo
        pagina.screenshot(path=destino, omit_background=not icono.fondo)
        print(f'  {icono.archivo:<21} {icono.lado}×{icono.lado}  {destino.stat().st_size / 1024:.0f} KB')
    pagina.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-build', action='store_true', help='no compilar; usar el dist/ actual')
    args = parser.parse_args()

    if not args.sin_build:
        compilar()
    with servir() as url, sync_playwright() as p:
        navegador = lanzar_chromium(p)
        print('· Renderizando desde la app')
        generar_og(navegador, url)
        generar_iconos(navegador, url)
        navegador.close()
    if not args.sin_build:
        # Otra vez, para que dist/ y el precache del service worker lleven los archivos nuevos.
        compilar()
    print('Listo.')


if __name__ == '__main__':
    main()
