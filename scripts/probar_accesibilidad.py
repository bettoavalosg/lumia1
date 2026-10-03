"""Accesibilidad de cada pantalla con axe-core (WCAG 2.2 AA y buenas prácticas): teléfono, admin y tele.

    python scripts/probar_accesibilidad.py                # compila y prueba contra el servidor local
    python scripts/probar_accesibilidad.py --sin-build    # reutiliza dist-sb/

Corre las mismas pruebas de pantallas que probar_pantallas.py (mismos estados: votación, veredicto, muerte, premios…) con axe-core
metido en cada página, y falla si encuentra violaciones. Necesita `npm install` (axe-core es una dependencia de desarrollo).
axe no sustituye probar con un lector de pantalla (VoiceOver, TalkBack): revisa lo que una máquina puede ver.
"""

from __future__ import annotations

import os

os.environ['AXE'] = '1'  # antes de importar: el arnés lo lee al crear cada sesión

from banco import correr  # noqa: E402
import probar_pantallas  # noqa: E402,F401  (al importarlo registra sus pruebas)

if __name__ == '__main__':
    correr(__doc__ or '', epilogo_modos=('supabase',), modulos=('probar_pantallas',))
