# Mariela cumple 29

Invitación de cumpleaños y juego de "asesino" en vivo para unas 20 personas. Es una PWA hecha con React, Vite y TypeScript, Tailwind v4 y, a partir de la Fase 2, Supabase.

- `docs/spec.md`: flujo, modelo de datos y pantallas. Es la fuente de verdad.
- `prototipo/`: diseños aprobados. El que se portó es `invitacion-mariela-v3.html`.

| Fase | Qué | Estado |
| --- | --- | --- |
| 1 | Invitación: sobre, sello, carta, RSVP de demostración, .ics y PWA | En revisión |
| 2 | Datos y RSVP real (Supabase, RLS) | Pendiente |
| 3 | Admin con PIN | Pendiente |
| 4 | Motor del juego (Edge Functions, pg_cron) | Pendiente |
| 5 | Pantallas del juego y /tv | Pendiente |
| 6 | Push y ensayo con 20 jugadores simulados | Pendiente |

## Requisitos

- Node 22 o más reciente (Vite 8 pide al menos 20.19).
- Python 3.10 o más reciente para los scripts.

## Desarrollo

```sh
npm install
npm run dev       # http://localhost:5173
npm run build     # typecheck y build de producción en dist/
npm run preview   # sirve dist/
```

## Scripts (Python)

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python -m playwright install chromium

python scripts/probar_invitacion.py    # el flujo completo contra la app compilada
python scripts/comparar_prototipo.py   # texto y píxeles contra el prototipo aprobado
python scripts/generar_assets.py       # og:image e íconos, renderizados desde la app
python scripts/descargar_fuentes.py    # vuelve a bajar Bodoni Moda y Jost para autoalojarlas
```

Todos compilan antes de empezar; con `--sin-build` usan el `dist/` que ya tengas. Si prefieres usar un Chromium propio, indícalo con `CHROMIUM_PATH=/ruta/a/chrome`.

## Deploy en Vercel

1. Importa el repo en Vercel. Detecta Vite solo: el build es `npm run build` y la salida es `dist`.
2. La `og:image` necesita URL absoluta. En Vercel se arma con `VERCEL_PROJECT_PRODUCTION_URL`, que apunta al dominio de producción más corto. Si quieres forzar otro dominio, define `VITE_SITE_URL=https://tu-dominio` en Settings → Environment Variables.
3. `vercel.json` agrega el fallback de SPA (para `/admin` y `/tv`) y las cabeceras de seguridad y de caché.

WhatsApp guarda la vista previa de cada URL. Si cambias `og.jpg` después de compartir el link, comparte `https://tu-dominio/?v=2` para que la vuelva a pedir.

## Probar en celulares reales

Los scripts emulan un iPhone y un Android sobre Chromium, pero eso no reemplaza a Safari de iOS ni a Chrome de Android. Con el link de preview de Vercel, revisa en los dos:

1. Pega el link en un chat de WhatsApp: tiene que salir el sobre negro con el sello.
2. Abre el link, toca el sello y recorre toda la invitación hasta el XOXO.
3. Intenta voltear la carta, deja el formulario vacío y luego llénalo, y agrega el evento al calendario.
4. Agrégala a la pantalla de inicio, ponte en modo avión y ábrela desde el ícono.
5. Activa "Reducir movimiento" (iOS: Accesibilidad → Movimiento; Android: Accesibilidad → Quitar animaciones) y ábrela otra vez.

## Estructura

```
src/invitacion/   el sobre, el sello, la suite de tarjetas, la carta de tarot y el RSVP
src/lib/          fecha del evento, cuenta regresiva, .ics y utilidades de movimiento
src/styles/       tokens OKLCH (@theme de Tailwind), fuentes y estilos de la invitación
public/           fuentes autoalojadas, íconos y og.jpg
scripts/          automatizaciones en Python
```
