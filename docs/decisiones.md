# Decisiones de diseño

Lo que se resolvió por el camino, y por qué. `docs/spec.md` manda; esto explica cómo se cumplió y dónde se eligió.

## El servidor es SQL, no funciones

La spec pedía Edge Functions para el reparto, el cierre de votación y el veredicto. Se hicieron como funciones de PL/pgSQL (`supabase/migrations/*_motor.sql`) porque así:

- Cada jugada es **una transacción bajo un candado** (`app.lock()`): dos votos, dos golpes o el reloj y un voto simultáneos no pueden duplicar un veredicto. Con Edge Functions habría que reconstruir esa atomicidad por fuera de la base.
- No hay arranques en frío: el voto número veinte no espera a que despierte un contenedor.
- Se prueba contra un Postgres real, sin emular nada (`scripts/probar_motor.py`, con concurrencia real).

La única Edge Function es `enviar-push`, porque Web Push necesita HTTP saliente con VAPID.

## La base solo se toca por funciones

Todo vive en el esquema `app`, que la API no expone. Las tablas tienen RLS activado y ninguna política, y a `anon`/`authenticated`/`service_role` se les quitaron los permisos. El cliente solo llama funciones de `public` (`security definer`, `search_path = pg_temp`) que validan el token del dispositivo o la sesión de admin y devuelven **JSON ya recortado para quien pregunta** (`*_estado.sql`): el rol propio, nunca el ajeno; los votos, solo cuando hay veredicto; los secretos, solo cuando se revelan; la dirección, solo pasada su hora.

Es más estricto que RLS por fila: no hay forma de pedir "todas las filas de `roles`", ni siquiera por error.

## Identidad sin login

Cada dispositivo genera un token de 256 bits; el servidor guarda su `sha256`. Perder el teléfono no pierde el lugar: la **llave** (XXXX-XXXX) que se muestra al responder, o la que genera el admin, recupera el lugar y rota el token (el dispositivo anterior queda fuera). Cinco fallos bloquean la recuperación diez minutos. El PIN de admin es bcrypt (`pgcrypto`), con bloqueo creciente y sesiones de 12 horas.

## El tiempo lo manda el servidor

Cada ronda guarda su `ends_at`. Los teléfonos solo pintan la cuenta regresiva a partir de la hora del servidor (con la diferencia de reloj medida en cada respuesta). Quien avanza el juego:

1. `pg_cron`, cada 5 s (en vez de los 30 s de la spec: el veredicto llega a tiempo);
2. y, si `pg_cron` no está, cualquier consulta de estado (`advance_if_due()` es barata: solo toma el candado si hay algo vencido).

La pausa desplaza los plazos al reanudar. En modo ensayo, `app.now()` suma un `clock_offset`, así una noche entera corre en minutos sin cambiar una línea del motor.

## Realtime solo avisa

El canal `noche` transmite "algo cambió" sin datos. Quien lo oye vuelve a pedir su estado (ya filtrado por el servidor), de modo que Realtime no puede filtrar nada aunque alguien se suscriba a mano. Si el canal se cae, la app consulta cada 3 s.

## Un mismo cliente para tres servidores

`Backend` (`src/servidor/backend.ts`) tiene tres implementaciones: Supabase (`fetch` + Realtime), **demo** (el Postgres corre dentro del navegador con PGlite y las mismas migraciones, con su propio reloj que hace de `pg_cron`) y un puente para los iframes del simulador. Por eso `/demo` y el ensayo prueban el motor de verdad, no una maqueta, y por eso las pruebas de interfaz corren en los dos entornos.

## Reglas que la spec dejaba abiertas

| Caso | Se resolvió así |
| --- | --- |
| Nadie vota | Fallo ("el silencio también es un voto"); nadie bebe; sale un secreto. |
| Empate que persiste tras el desempate | Fallo; beben los empatados. |
| Acierto | Bebe el asesino; no sale ningún secreto; se reparte de nuevo tras una pausa (configurable). |
| Dos asesinos (más de 16 presentes) | Cada uno conoce a su cómplice; cualquiera de los dos puede matar (solo una víctima por fallo). |
| Llega alguien con la partida empezada | Marca llegada, ve la partida y entra en la siguiente; no recibe carta ni vota. |
| Se acaban los secretos aprobados | El fallo sigue, con un aviso de que no quedan secretos. |
| El asesino no elige víctima | Elige el azar, y así queda en la bitácora. |
| Muerte de apertura | Detrás de un interruptor, apagado por defecto. |
| Quién puede ver quién era el asesino | Todos, al terminar la partida. Los premios de la noche ("Sangre fría") nombran a quien más mató. |
| Datos después de la fiesta | `select app.borrar_datos_de_la_fiesta();` los borra. |

## La interfaz

- **La carta no existe en el DOM mientras no se sostiene**: se monta al mantenerla presionada (170 ms, para que un roce no delate nada) y se desmonta al soltar, al perder el foco o al cambiar de app. Un espía no puede verla en una captura, en el inspector ni en el HTML.
- **La tele se ajusta sola**: todo está en `rem`; si una escena trae de más (veinte nombres largos), se reduce la raíz lo justo (nunca por debajo de 12 px) para que quepa entera. Además pide que la pantalla no se apague y pasa a pantalla completa con doble clic.
- **Las hojas de confirmación se montan sobre la raíz de la app**, no donde se declaran. Una capa `position: fixed` se ancla al ancestro más cercano con `transform`, `translate` o `filter`, y las pantallas entran animadas (`translate`): la hoja cerrada asomaba sobre la barra de pestañas. Ahora `Hoja` usa un portal hacia `.juego`, cerrada es `visibility: hidden`, y `probar_pantallas.py` lo comprueba en cada pantalla (también con la pantalla forzada a tener un `translate`).
- **CSS a mano** sobre los tokens OKLCH de la invitación, en vez de un kit de componentes: la estética (cartulina negra, peltre, un solo rojo) es el producto.
- **Accesibilidad como prueba, no como intención**: axe-core (WCAG 2.2 AA) corre sobre cada pantalla del teléfono, el admin y la tele; los controles miden al menos 44 px; hay un `h1` por vista, el foco se maneja en las hojas de confirmación y `prefers-reduced-motion` desactiva las animaciones.
