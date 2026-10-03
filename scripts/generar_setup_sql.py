"""Junta las migraciones en un solo archivo (supabase/setup.sql) para pegarlo en el SQL Editor de Supabase.

    python scripts/generar_setup_sql.py          # escribe supabase/setup.sql
    python scripts/generar_setup_sql.py --revisar  # falla si setup.sql no está al día con las migraciones

Es idempotente: se puede volver a correr sobre una base que ya lo tiene (create if not exists / create or replace).
"""

from __future__ import annotations

import argparse
import sys

from motor_pg import MIGRACIONES, RAIZ

SALIDA = RAIZ / 'supabase' / 'setup.sql'
ENCABEZADO = """-- Mariela · 29 — TODO el servidor en un solo pegado.
-- Generado por scripts/generar_setup_sql.py a partir de supabase/migrations/. No lo edites a mano.
--
-- Cómo usarlo: Supabase → SQL Editor → New query → pega este archivo → Run.
-- Luego define tu PIN de admin (una sola vez):   select app.set_admin_pin('tu-pin-de-al-menos-6');
"""


def generar() -> str:
    partes = [ENCABEZADO]
    for migracion in MIGRACIONES:
        partes.append(f'-- ================================================================================\n-- {migracion.name}\n-- ================================================================================\n')
        partes.append(migracion.read_text().rstrip() + '\n')
    partes.append("-- ================================================================================\n-- Listo. Ahora:  select app.set_admin_pin('tu-pin-de-al-menos-6');\n-- ================================================================================\n")
    return '\n'.join(partes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--revisar', action='store_true', help='no escribe: solo comprueba que setup.sql esté al día')
    args = parser.parse_args()
    contenido = generar()
    if args.revisar:
        if not SALIDA.exists() or SALIDA.read_text() != contenido:
            sys.exit('supabase/setup.sql no está al día. Corre: python scripts/generar_setup_sql.py')
        print('supabase/setup.sql está al día.')
        return
    SALIDA.write_text(contenido)
    print(f'{SALIDA.relative_to(RAIZ)}: {len(contenido.splitlines())} líneas, {len(contenido) / 1024:.0f} KB')


if __name__ == '__main__':
    main()
