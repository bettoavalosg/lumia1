"""Lo que comparten los scripts: compilar la app, servir dist/ en local y abrir Chromium."""

from __future__ import annotations

import contextlib
import functools
import http.server
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / 'dist'
PUBLICO = RAIZ / 'public'


def compilar(env_extra: dict[str, str] | None = None) -> None:
    """Corre `npm run build` (typecheck + Vite). Solo muestra la salida si falla."""
    npm = shutil.which('npm')
    if not npm:
        sys.exit('No encontré npm. Instala Node 20 o más reciente y corre `npm install`.')
    print('· npm run build', flush=True)
    resultado = subprocess.run(
        [npm, 'run', 'build'],
        cwd=RAIZ,
        env={**os.environ, **(env_extra or {})},
        capture_output=True,
        text=True,
    )
    if resultado.returncode:
        print(resultado.stdout, resultado.stderr, sep='\n')
        sys.exit('La compilación falló.')


class _Manejador(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.js': 'text/javascript',
        '.webmanifest': 'application/manifest+json',
        '.woff2': 'font/woff2',
    }

    def end_headers(self) -> None:
        # Como en Vercel, nada se queda en la caché HTTP: de guardar se encarga el service worker.
        self.send_header('Cache-Control', 'no-cache')
        # Deja que otra página local (el prototipo) use las fuentes autoalojadas.
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def log_message(self, *args: object) -> None:
        pass


@contextlib.contextmanager
def servir(directorio: Path = DIST, indice: str = 'index.html') -> Iterator[str]:
    """Sirve `directorio` en un puerto libre de 127.0.0.1 (contexto seguro: el service worker funciona)."""
    if not (directorio / indice).exists():
        sys.exit(f'Falta {directorio / indice}. Compila primero con `npm run build`.')
    manejador = functools.partial(_Manejador, directory=str(directorio))
    servidor = http.server.ThreadingHTTPServer(('127.0.0.1', 0), manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f'http://127.0.0.1:{servidor.server_address[1]}'
    finally:
        servidor.shutdown()
        servidor.server_close()


# Espera a que termine toda animación finita (las infinitas, como la luz de vela, se ignoran).
ESPERAR_ANIMACIONES = """
async () => {
  await document.fonts.ready
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
  const finitas = document.getAnimations().filter(a => a.effect?.getComputedTiming().endTime !== Infinity)
  await Promise.all(finitas.map(a => a.finished.catch(() => {})))
}
"""


def lanzar_chromium(playwright):  # noqa: ANN001, ANN201 (tipos de Playwright)
    """Chromium de Playwright, o el binario de CHROMIUM_PATH si lo defines."""
    ruta = os.environ.get('CHROMIUM_PATH')
    try:
        return playwright.chromium.launch(executable_path=ruta) if ruta else playwright.chromium.launch()
    except Exception as error:  # noqa: BLE001
        sys.exit(f'No pude abrir Chromium ({error}).\nCorre `python -m playwright install chromium` o define CHROMIUM_PATH.')
