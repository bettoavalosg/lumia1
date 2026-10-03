"""Corre TODAS las pruebas, una tras otra, y al final dice cuáles pasaron. Compila una sola vez.

    python scripts/probar_todo.py                       # todo (unos 15 minutos)
    python scripts/probar_todo.py --saltar ensayo,accesibilidad
    python scripts/probar_todo.py --solo motor,juego

Pasos: motor, invitacion, juego, pantallas, accesibilidad, prototipo, ensayo, setup.
Cada uno es un script de esta carpeta que también se puede correr por su cuenta (con --help ves sus opciones).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from banco import compilar_entorno

AQUI = Path(__file__).resolve().parent
PASOS: dict[str, list[str]] = {
    'motor': ['probar_motor.py'],
    'invitacion': ['probar_invitacion.py', '--sin-build'],
    'juego': ['probar_juego.py', '--sin-build'],
    'pantallas': ['probar_pantallas.py', '--sin-build'],
    'accesibilidad': ['probar_accesibilidad.py', '--sin-build'],
    'prototipo': ['comparar_prototipo.py', '--sin-build'],
    'ensayo': ['ensayo.py', '--local'],
    'setup': ['generar_setup_sql.py', '--revisar'],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--saltar', default='', help='pasos que no se corren, separados por comas')
    ap.add_argument('--solo', default='', help='solo estos pasos, separados por comas')
    args = ap.parse_args()
    saltar = {x for x in args.saltar.split(',') if x}
    solo = [x for x in args.solo.split(',') if x]
    desconocidos = (saltar | set(solo)) - set(PASOS)
    if desconocidos:
        ap.error(f'pasos desconocidos: {", ".join(sorted(desconocidos))}. Los hay: {", ".join(PASOS)}')
    pasos = [p for p in (solo or PASOS) if p not in saltar]

    if any(p in pasos for p in ('invitacion', 'juego', 'pantallas', 'accesibilidad', 'prototipo')):
        compilar_entorno('supabase')
    if any(p in pasos for p in ('invitacion', 'juego')):
        compilar_entorno('demo')

    resultados: list[tuple[str, bool, float]] = []
    for nombre in pasos:
        print(f'\n{"=" * 100}\n▶ {nombre}\n{"=" * 100}', flush=True)
        inicio = time.monotonic()
        codigo = subprocess.run([sys.executable, '-u', str(AQUI / PASOS[nombre][0]), *PASOS[nombre][1:]], cwd=AQUI.parent).returncode
        resultados.append((nombre, codigo == 0, time.monotonic() - inicio))

    print(f'\n{"=" * 100}\nResumen\n{"=" * 100}')
    for nombre, ok, segundos in resultados:
        print(f'  {"✓" if ok else "✗"} {nombre:<14} {segundos:>6.0f} s')
    fallaron = [n for n, ok, _ in resultados if not ok]
    if fallaron:
        sys.exit(f'\nFallaron: {", ".join(fallaron)}')
    print('\nTodo en orden.')


if __name__ == '__main__':
    main()
