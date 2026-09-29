"""Descarga Bodoni Moda y Jost (woff2) para auto-hospedarlas en public/fonts y genera src/styles/fuentes.css.

Las mismas familias y ejes que usa el prototipo en Google Fonts, servidas desde nuestro dominio:
la PWA las precachea y funciona sin conexión. Licencia: SIL Open Font License (se copia junto a los archivos).

Uso: python scripts/descargar_fuentes.py
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "public" / "fonts"
CSS_SALIDA = RAIZ / "src" / "styles" / "fuentes.css"

CSS_GOOGLE = (
    "https://fonts.googleapis.com/css2"
    "?family=Bodoni+Moda:ital,opsz,wght@0,6..96,400..600;1,6..96,400..600"
    "&family=Jost:wght@400..500&display=swap"
)
LICENCIAS = {
    "bodoni-moda": "https://raw.githubusercontent.com/google/fonts/main/ofl/bodonimoda/OFL.txt",
    "jost": "https://raw.githubusercontent.com/google/fonts/main/ofl/jost/OFL.txt",
}
SUBCONJUNTOS = {"latin": "", "latin-ext": "-ext"}
# Un navegador moderno recibe woff2 con los ejes variables completos.
AGENTE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def bajar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main() -> None:
    css = bajar(CSS_GOOGLE).decode("utf-8")
    bloques = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S)
    DESTINO.mkdir(parents=True, exist_ok=True)
    reglas = ["/* Generado por scripts/descargar_fuentes.py. No editar a mano. */"]
    for subconjunto, cuerpo in bloques:
        if subconjunto not in SUBCONJUNTOS:
            continue
        prop = lambda nombre: re.search(rf"{nombre}:\s*([^;]+);", cuerpo).group(1).strip()
        familia = prop("font-family").strip("'\"")
        estilo = prop("font-style")
        url = re.search(r"url\((https://[^)]+\.woff2)\)", cuerpo).group(1)
        base = familia.lower().replace(" ", "-") + ("-italica" if estilo == "italic" else "")
        archivo = f"{base}{SUBCONJUNTOS[subconjunto]}.woff2"
        (DESTINO / archivo).write_bytes(bajar(url))
        print(f"{archivo:34} {len((DESTINO / archivo).read_bytes()) / 1024:6.1f} KB  {familia} {estilo} {subconjunto}")
        reglas.append(
            "@font-face {\n"
            f"  font-family: \"{familia}\";\n"
            f"  font-style: {estilo};\n"
            f"  font-weight: {prop('font-weight')};\n"
            "  font-display: swap;\n"
            f"  src: url(\"/fonts/{archivo}\") format(\"woff2\");\n"
            f"  unicode-range: {prop('unicode-range')};\n"
            "}"
        )
    CSS_SALIDA.write_text("\n".join(reglas) + "\n", encoding="utf-8")
    for nombre, url in LICENCIAS.items():
        (DESTINO / f"OFL-{nombre}.txt").write_bytes(bajar(url))
    print(f"{len(reglas) - 1} caras escritas en {CSS_SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
