# Mariela cumple 29

La invitación de cumpleaños y el juego del "asesino" en vivo para unas 20 personas, en una sola PWA: React + Vite + TypeScript, Tailwind v4, Supabase (Postgres, Realtime), Web Push y Vercel.

- `docs/spec.md`: el flujo, el modelo de datos y las pantallas. Es la fuente de verdad.
- `docs/decisiones.md`: por qué el servidor es SQL y no funciones, cómo se resolvieron las reglas que la spec dejaba abiertas y otras decisiones de diseño.
- `prototipo/`: el diseño aprobado de la invitación (`invitacion-mariela-v3.html`). La app se compara contra él píxel por píxel.

| Ruta | Qué es |
| --- | --- |
| `/` | La invitación (sobre, sello, RSVP). Cuando el admin abre la puerta, se convierte en el juego de cada invitado: antesala, carta, ronda, votación, veredicto, bitácora. |
| `/tv` | La pantalla para proyectar: cuenta regresiva grande, votación, veredictos, secretos y muertes. |
| `/admin` | El panel del admin (PIN): puerta, reparto, pausa, invitados, secretos, ajustes y modo ensayo. |
| `/demo` | Un simulador: dos teléfonos, la tele y los controles sobre un mismo servidor de mentiras, con bots. Sirve para probar la noche completa sin nadie más. |

## Probarla ahora mismo (sin Supabase)

```sh
npm install
npm run dev          # http://localhost:5173
```

Sin configurar nada la app corre en **modo demo**: el Postgres vive dentro del navegador (PGlite, con las mismas migraciones que usará Supabase). Abre <http://localhost:5173/demo>, pulsa "Preparar la noche" y tendrás dos teléfonos, la tele y los controles del admin; los demás invitados son bots y el reloj se puede adelantar. El PIN de admin en modo demo es `000000`.

El modo demo es para probar y ensayar. **No sirve para la fiesta**: cada navegador tiene su propio servidor, así que las respuestas de tus invitados no llegarían a ti. Para la noche real, conecta Supabase (siguiente sección; son unos 15 minutos).

## Ponerla en marcha para la fiesta

### 1. Supabase (el servidor)

1. Crea un proyecto en <https://supabase.com> (el plan gratuito alcanza de sobra).
2. **SQL Editor → New query**, pega **todo** `supabase/setup.sql` y pulsa Run. Crea el esquema privado `app` (todas las tablas, cerradas con RLS y sin políticas), las funciones del motor y la API, y programa el reloj con `pg_cron` si está disponible.
3. En otra consulta, define tu PIN de admin (mínimo 6 caracteres; lo puedes cambiar después desde el panel):

   ```sql
   select app.set_admin_pin('tu-pin-secreto');
   ```
4. **Database → Extensions**: activa `pg_cron` (el reloj del servidor, cada 5 s) y `pg_net` (lo usan los avisos push). Si ya los activaste antes de pegar `setup.sql`, no hay nada más que hacer; si los activaste después, vuelve a correr `setup.sql` (es seguro repetirlo).
5. **Project Settings → API**: copia la *Project URL* y la *anon* (o *publishable*) key. **Nunca** uses ni pegues la `service_role` key en el front.

Si `pg_cron` no está disponible el juego sigue funcionando: los teléfonos y la tele empujan el reloj cada vez que consultan su estado. Y si Realtime no llega (canales privados, red de oficina), la app consulta cada 3 s en vez de esperar el aviso.

### 2. Vercel (el sitio)

1. Importa el repo en Vercel. Detecta Vite solo: el build es `npm run build` y la salida es `dist`. `vercel.json` ya trae el fallback de SPA (para `/admin`, `/tv` y `/demo`) y las cabeceras de seguridad.
2. En **Settings → Environment Variables** agrega:

   | Variable | Valor |
   | --- | --- |
   | `VITE_SUPABASE_URL` | la Project URL |
   | `VITE_SUPABASE_ANON_KEY` | la anon / publishable key (pública por diseño: la seguridad está en la base) |
   | `VITE_SITE_URL` | opcional: el dominio final, para la vista previa de WhatsApp (si no, se toma de Vercel) |
   | `VITE_VAPID_PUBLIC_KEY` | opcional: para los avisos push (paso 3) |

3. Vuelve a desplegar. Abre el sitio, responde la invitación con un nombre de prueba y entra a `/admin` con tu PIN: ahí debe aparecer.

WhatsApp guarda la vista previa de cada URL. Si cambias `og.jpg` después de compartir el link, comparte `https://tu-dominio/?v=2` para que la vuelva a pedir.

### 3. Avisos push (opcional)

Los avisos llegan aunque el teléfono esté bloqueado: "La puerta está abierta", "Ya sabes dónde es" (cuando se revela la dirección), "Tu carta ya está lista", "Se abrió la votación", "Fallaron", "Elige a tu víctima", "Has muerto", el fin de la partida y el de la noche. Solo los reciben quienes los activaron desde la app. En iPhone **solo funcionan con la PWA instalada en la pantalla de inicio** (iOS 16.4 o más reciente): son un extra, no el canal principal.

```sh
python scripts/generar_vapid.py       # imprime el par de llaves VAPID
```

1. La llave pública va a Vercel como `VITE_VAPID_PUBLIC_KEY` (y redespliegas).
2. Con el [CLI de Supabase](https://supabase.com/docs/guides/cli) (`supabase link --project-ref <ref>`):

   ```sh
   supabase secrets set VAPID_PUBLIC_KEY=… VAPID_PRIVATE_KEY=… VAPID_SUBJECT=mailto:tu@correo.com PUSH_SECRET=<algo-largo-al-azar>
   supabase functions deploy enviar-push --no-verify-jwt
   ```
3. En el SQL Editor, conecta Postgres con la función:

   ```sql
   select app.configure_push('https://<ref>.supabase.co/functions/v1/enviar-push', '<el mismo PUSH_SECRET>');
   ```

La función no se expone al público: sin el secreto compartido responde 403, y solo habla con la base por dos funciones que únicamente acepta la `service_role`.

## Mandar la invitación

La invitación es un enlace: `https://tu-dominio.com`. Mandarla por SMS es mandar ese enlace en un mensaje. En iMessage suele salir con la vista previa del sobre sellado; en un SMS normal es solo el texto del enlace.

**Para unos 20 amigos, lo más confiable es mandarlo tú desde tu teléfono**: el mensaje sale de un número que conocen, sin filtros de spam y sin cuentas que pagar. Algo como:

> Mariela cumple 29: hay fiesta en la CDMX y alguien no va a salir viva. XOXO
> Ana, tu invitación: https://tu-dominio.com

**Si prefieres que salgan solos**, `scripts/enviar_sms.py` los manda por Twilio, uno por uno y con el nombre de cada quien. Corre en tu computadora y solo usa la biblioteca estándar de Python: los teléfonos no pasan por la app ni por Supabase, y las llaves de Twilio no están en el front.

1. Crea una cuenta en Twilio y consigue un número que mande SMS (o un *Messaging Service*). Una cuenta de prueba solo manda a números que hayas verificado en su consola. Revisa que México esté activado en *Messaging → Settings → Geo permissions*.
2. Arma `contactos.csv` con una fila por invitado. Está en el `.gitignore` (como `contactos*.csv`, `invitados*.csv` y `*.envios.csv`): son datos personales, no los subas.

   ```csv
   nombre,telefono
   Ana Torres,55 1234 5678
   Luis,+52 1 33 9876 5432
   ```

   El nombre sale tal cual en el mensaje. Los teléfonos de México se escriben como sea (espacios, guiones, 044, +52 1…); los de otro país, con su `+`.
3. Pon las credenciales en tu terminal (están en la consola de Twilio):

   ```sh
   export TWILIO_ACCOUNT_SID=AC…  TWILIO_AUTH_TOKEN=…  TWILIO_FROM=+1…     # o TWILIO_MESSAGING_SERVICE_SID=MG… en vez de TWILIO_FROM
   ```
4. **Ensayo**: no manda nada; enseña a quién, cómo le llega, cuántos SMS son y qué filas tienen un teléfono malo.

   ```sh
   python scripts/enviar_sms.py contactos.csv --url https://tu-dominio.com
   ```
5. Mándate uno a ti primero y, si llegó bien, a todos:

   ```sh
   python scripts/enviar_sms.py contactos.csv --url https://tu-dominio.com --enviar --solo "tu nombre"
   python scripts/enviar_sms.py contactos.csv --url https://tu-dominio.com --enviar
   ```

Si lo corres otra vez, a quien ya se le mandó se le salta (queda en `contactos.envios.csv`); con `--reenviar` se manda de nuevo. Un envío sin respuesta queda como *incierto* y no se reintenta solo, para no mandar el mismo mensaje dos veces: mira en Twilio si salió. Cada corrida tiene un tope de 40 mensajes (`--max`) que frena un CSV equivocado. El texto se cambia con `--mensaje "…{nombre}…{url}…"` o con `--mensaje-archivo`. La dirección no va en el mensaje: se revela desde la app a la hora que fijes.

Lo que conviene saber:

- Con acentos o símbolos el SMS pasa a UCS-2 (70 caracteres por SMS en vez de 160), así que el mensaje de arriba son 2 SMS por persona. El ensayo te dice el total.
- Según la guía de Twilio, en México un nombre de remitente propio hay que registrarlo y pide un mínimo de unos 1,000 SMS al mes; para unas decenas de invitados se manda desde un número. A veces los operadores retrasan o filtran los mensajes de números extranjeros: prueba con 2 o 3 personas antes, no el último día.
- Twilio solo confirma que recibió el mensaje; si llegó, lo ves en su consola (*Monitor → Logs → Messaging*).

## Antes de la fiesta: ensayar

Hay tres formas, de menos a más real:

1. **`/demo`**: la noche entera en tu navegador, con bots y reloj adelantable. No toca ningún servidor.
2. **Modo ensayo en tu proyecto** (`/admin` → Ajustes → *Modo ensayo*): aparece la pestaña *Ensayo* con bots, un reloj que se adelanta y una vista de depuración (roles y votos: es un spoiler). Al apagarlo se van los bots y el reloj vuelve a la hora real; *Reiniciar el ensayo* borra partidas y votos y devuelve los secretos revelados al montón.
3. **`scripts/ensayo.py`**: 20 invitados simulados que juegan por la misma API pública que usan los teléfonos (ver más abajo).

```sh
python scripts/ensayo.py --url https://<ref>.supabase.co --clave <anon key> --pin <tu PIN>
python scripts/ensayo.py --local        # lo mismo, contra un Postgres temporal en tu computadora
```

Reparte, vota (todos a la vez), empata, mata, atrapa, reparte de nuevo y cierra la noche, y en cada paso comprueba que nadie vea el rol de otro, que los votos sigan ocultos hasta el veredicto, que un voto o una muerte no se puedan repetir aunque lleguen juntos, que las cuentas de tragos cuadren y que las tablas y el admin sigan cerrados. Todo lo que crea se llama "Ensayo NN" y se borra al terminar. Se niega a correr si ya hay una partida o invitados de verdad.

**Prueba en celulares reales** (los scripts emulan un iPhone y un Android sobre Chromium, pero no reemplazan a Safari de iOS ni a Chrome de Android):

1. Pega el link en un chat de WhatsApp: tiene que salir el sobre negro con el sello.
2. Rompe el sello, recorre la invitación, responde con un secreto, agrega el evento al calendario.
3. Instala la app en la pantalla de inicio, actívale los avisos y ponla en modo avión: abre desde el ícono.
4. Con la puerta abierta desde `/admin`: "Estoy aquí", ver la carta (hay que mantenerla presionada), votar, recibir el veredicto.
5. Abre `/tv` en la pantalla que vas a proyectar y mírala desde donde se van a sentar.
6. Activa "Reducir movimiento" (iOS: Accesibilidad → Movimiento) y ábrela otra vez.

## La noche (guía del admin)

**Días antes**: en `/admin` → *Ajustes*, escribe la dirección y la hora en que se revela (el servidor no la manda a ningún teléfono antes; ver "Seguridad"). En *Secretos* aprueba, rechaza o edita los que vayan llegando: son anónimos (no ves quién escribió cada uno) y solo los aprobados entran al juego. Quien tenga un secreto rechazado ve un aviso y escribe otro.

**Ese día**:

1. *Noche → La tele*: copia el enlace (lleva una llave que solo tú tienes) y ábrelo en la computadora conectada a la tele. Doble clic para pantalla completa; la pantalla no se apaga sola y el cursor se esconde. También puedes ponerle un *código de la puerta* en Ajustes: sale en la tele y hay que escribirlo para marcar "Estoy aquí".
2. *Noche → Abrir la puerta*. Los invitados abren la app (el link con el que respondieron, o su llave en "¿Ya respondiste desde otro teléfono?") y marcan "Estoy aquí". Quien llegue sin haber respondido: *Invitados → Agregar a alguien* y le das su llave. Quien pierda su teléfono: *··· → Generar llave nueva*.
3. Con al menos 3 presentes, *Repartir cartas*. Cada quien ve la suya **solo mientras la mantiene presionada**.
4. El juego corre solo: ronda de 20 min → votación de 3 min → veredicto. Desde el panel puedes *Pausar*, *Abrir la votación ya* / *Elegir la víctima al azar ya* (forzar el momento) y *Repartir de nuevo*. Los tiempos se cambian en Ajustes.
5. *Terminar la noche*: la tele y los teléfonos muestran el podio de tragos y los premios. Se puede reabrir.

**Reglas tal como están implementadas**

- 1 asesino; 2 si hay más de 16 presentes (`killers_threshold`).
- **Votación**: solo votan los vivos, un voto cada uno, sin cambiarlo. Gana la mayoría relativa. Empate → desempate relámpago (60 s) entre los empatados; si persiste, cuenta como fallo. Nadie vota → fallo.
- **Acierto**: bebe el asesino, se revela quién era, todos reviven y se reparten cartas nuevas.
- **Fallo**: beben quienes votaron por el acusado, sale a la luz un secreto anónimo y el asesino elige una víctima en la app (90 s; si no elige, el azar). La víctima ve "Has muerto", la tele lo anuncia y el mismo asesino sigue.
- Si solo quedan el asesino y un inocente, gana el asesino y se reparte de nuevo.
- *Muerte de apertura* (apagada por defecto): al repartir, el asesino elige a una primera víctima para que la primera votación no sea a ciegas.
- Los tiempos de cada momento, el umbral de dos asesinos, la muerte de apertura y el código de la puerta se ajustan desde el panel.

**Si algo sale mal**

| Pasa | Qué hacer |
| --- | --- |
| Olvidaste el PIN | En el SQL Editor: `select app.set_admin_pin('uno-nuevo');` |
| Un teléfono dice "Sin conexión" | Es su red; la app conserva lo último que sabía y se recupera sola. Nada se pierde. |
| Alguien no ve su carta | Debe haber marcado "Estoy aquí" *antes* del reparto; si llegó tarde, entra en la siguiente partida. |
| Se te fue la luz / cerraste el panel | El juego sigue solo (el reloj vive en el servidor). Vuelve a entrar con tu PIN. |
| Quieres empezar de cero tras ensayar | *Ajustes → Modo ensayo*, y en *Ensayo* → *Reiniciar el ensayo*; luego apaga el modo. |

## Después de la fiesta

Los nombres y los secretos de tus amigos no tienen por qué quedarse en una base de datos. Cuando termine la noche, en el SQL Editor:

```sql
select app.borrar_datos_de_la_fiesta();
```

Borra a los invitados (con sus tokens y llaves), sus secretos y todas las partidas; vacía la dirección y el código de la puerta, apaga el modo ensayo y deja la app en la invitación. Conserva tu PIN y los tiempos que ajustaste. La opción radical es borrar el proyecto de Supabase (Settings → General → Delete project).

## Seguridad

- **Las tablas no se pueden tocar desde el navegador.** Todo vive en un esquema privado (`app`) que la API no expone; tiene RLS activado y cero políticas, y a `anon`/`authenticated` se les quitaron los permisos. Lo único alcanzable son funciones `security definer` en `public` que validan el token del dispositivo o la sesión de admin.
- **Cada quien solo lee su propio rol.** El estado que recibe un teléfono nunca trae el rol de otros; los asesinos se revelan hasta que termina la partida. El estado de un inocente ni siquiera contiene la palabra "asesino".
- **Los votos están ocultos hasta el veredicto**: durante la votación solo se sabe *cuántos* han votado, nunca quién votó por quién. **Los secretos** no salen del servidor hasta que se revelan, y solo entran al montón los aprobados; el panel de admin no sabe quién escribió cada uno.
- **La dirección** no se manda a ningún teléfono antes de la hora que fijes.
- **Solo el asesino vivo mata**, solo dentro de su ventana y solo a un vivo que no sea él; el candado del servidor hace que dos votos o dos golpes simultáneos no se dupliquen.
- **Identidad sin login**: cada dispositivo genera un token al azar y el servidor guarda solo su hash. La *llave* (XXXX-XXXX) recupera el lugar en otro teléfono, con bloqueo tras 5 intentos. El PIN de admin se verifica en el servidor (bcrypt), con bloqueo creciente y sesiones de 12 horas.
- **La tele** entra con una llave en el fragmento de la URL (`#k=…`), que no llega a los registros de ningún servidor.
- **Todo el estado del juego se decide en el servidor**: los relojes son `ends_at` en la base; los teléfonos solo pintan la cuenta regresiva.
- La `service_role` key no está en el front ni en ningún archivo del repo.

Las invariantes se comprueban con pruebas, no con fe (ver "Pruebas").

## Pruebas

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python -m playwright install chromium        # o define CHROMIUM_PATH=/ruta/a/chrome
npm install
```

| Comando | Qué comprueba |
| --- | --- |
| `python scripts/probar_motor.py` | **73 pruebas del servidor** contra un Postgres real (temporal): seguridad, reparto, votación, empates, veredictos, muertes, ranking, admin, ensayo, push (incluidos los avisos de la puerta y la dirección, una sola vez), concurrencia, que `setup.sql` se pueda volver a pegar y que la limpieza final borre a todos. Se validaron también con mutaciones (se rompe una regla a propósito y la prueba tiene que fallar). |
| `python scripts/probar_juego.py` | **27 pruebas de interfaz** de la noche: antesala y puerta con código, la carta que solo existe mientras se sostiene, votar y el veredicto por partes, fallo/muerte/"Has muerto", desempate, pausa, sin conexión, aviso de Realtime, el service worker de push, la tele que no deja apagar la pantalla, el aviso de un servidor sin configurar, premios, el panel de admin entero y una noche completa jugada contra bots. Además revisa **cada respuesta que recibe cada teléfono y la tele** para que no lleve nada que no debe. |
| `python scripts/probar_invitacion.py` | 23 pruebas de la invitación: sello, carta, RSVP real, llave, calendario, dirección, sin red, teclado, movimiento reducido, 320 px. |
| `python scripts/probar_pantallas.py` | Ninguna pantalla se desborda ni deja controles imposibles de tocar: teléfono de 320 px, tableta, escritorio y la tele (con 17 nombres de 40 caracteres, lo más apretado posible, y con una fiesta normal de 20; y que la tele achicada no parpadee). |
| `python scripts/probar_accesibilidad.py` | Las mismas pantallas con axe-core (WCAG 2.2 AA). |
| `python scripts/comparar_prototipo.py` | La invitación contra el prototipo aprobado: mismo texto, mismo aspecto. |
| `python scripts/ensayo.py --local` | El ensayo general con 20 invitados simulados (también contra tu proyecto real; ver arriba). |
| `python scripts/probar_sms.py` | 15 pruebas del envío por SMS contra un Twilio de mentiras (no manda nada ni pide cuenta): teléfonos, conteo de SMS, el ensayo, el formato exacto de lo que recibe Twilio, no repetir envíos, errores, interrupciones y que los números no lleguen al repo. También validadas con mutaciones. |

`python scripts/probar_todo.py` corre todas seguidas (compila una sola vez) y al final resume cuáles pasaron; con `--solo` o `--saltar` eliges pasos.

Las pruebas de interfaz corren en dos entornos: `supabase` (el build de producción, con su CSP y su service worker, hablando con la API real sobre un Postgres local) y `demo` (Postgres dentro del navegador). Con `--modo` eliges uno, con `-k texto` filtras por nombre y con `--sin-build` reutilizas la compilación anterior.

Otras herramientas: `python scripts/servidor_local.py` levanta la API en tu computadora (imprime la línea para `npm run dev` contra ella), `python scripts/generar_setup_sql.py` regenera `supabase/setup.sql` tras tocar una migración (`--revisar` comprueba que esté al día), `python scripts/generar_assets.py` renderiza la `og:image` y los íconos desde la app y `python scripts/descargar_fuentes.py` baja Bodoni Moda y Jost para autoalojarlas.

### Lo que no pude probar desde aquí

- **Safari de iOS y Chrome de Android reales**, ni lectores de pantalla: los teléfonos son emulaciones de Chromium.
- **Supabase de verdad**: Realtime (`realtime.send` desde la base) y los envíos de Web Push a los servicios de Apple y Google. El cliente de Realtime se probó contra un servidor de mentiras que habla el mismo protocolo (tramas binarias y JSON), y el service worker recibió pushes entregados por el navegador; pero el primer ensayo en tu proyecto, con `scripts/ensayo.py` y tus propios teléfonos, es el que cierra el círculo. Si Realtime o el push fallaran, el juego no se cae: consulta cada 3 s.
- **Twilio de verdad**: `scripts/enviar_sms.py` se probó contra un servidor local que contesta con el mismo formato que la API de mensajes de Twilio (ruta, autenticación, campos, errores y respuestas cortadas), pero no mandó ningún SMS. La primera vez, mándate uno a ti con `--solo`.

## Estructura

```
src/invitacion/   el sobre, el sello, la suite de tarjetas, la carta de tarot y el RSVP
src/juego/        la noche de cada invitado: antesala, carta, ronda, votación, veredicto, muerte, fin
src/tv/           la pantalla de la tele (se ajusta sola para que nada se corte)
src/admin/        el panel: noche, invitados, secretos, ajustes, ensayo
src/demo/         el simulador de /demo
src/servidor/     cómo habla la app con el servidor: Supabase, demo (PGlite) y el estado que se refresca
src/compartido/   piezas que usan varias pantallas (cuenta regresiva, hojas, avisos, premios)
src/lib/          fecha del evento, cuenta regresiva, .ics y utilidades de movimiento
src/styles/       tokens OKLCH (@theme de Tailwind) y los estilos de cada parte
supabase/         migraciones (fuente), setup.sql (todo en un pegado), Edge Function de push
public/           fuentes autoalojadas, íconos, og.jpg y el service worker de push
scripts/          automatizaciones y pruebas en Python
```

El servidor es SQL: `supabase/migrations/` (esquema, motor de estados, JSON de estado, API, admin, push y cron). No hay lógica del juego en el navegador: solo pinta lo que dice el servidor.
