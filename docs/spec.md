# Mariela · 29 — Invitación + juego "Asesino" (PWA)

## 1. Invitación (copy)

> **Hay una fiesta en la Ciudad de México… y esta noche alguien no va a salir viva.**
>
> Mariela cumple 29 y sus amigos están convocados. Veinte invitados, un departamento, y entre ustedes se esconde un asesino. Nadie sabe quién. Ni siquiera yo… por ahora.
>
> **Sábado 24 de octubre · 6:00 pm**
> **Dirección:** se revela unos días antes. Es un secreto que todavía no voy a contar.
> **Dress code:** all black. Literal. Negro de pies a cabeza. Si llegas con color, todos lo van a notar.
>
> Para confirmar, deja tu nombre… y un secreto de otro invitado. Tranquilo, está a salvo conmigo. A menos que fallen.
>
> *XOXO*

## 2. Flujo del juego

**Fase 0 · Invitación (hoy → 24 oct)**
RSVP con nombre + secreto (sobre quién + qué). Dirección bloqueada hasta la fecha que fije el admin.

**Fase 1 · Llegada (24 oct)**
El invitado marca "Estoy aquí" e instala la PWA. Cuando todos llegan, el admin pulsa "Repartir cartas": cada quien recibe **Asesino** o **Inocente** (1 asesino; 2 si hay más de 16 presentes).

**Fase 2 · Ronda (timer automático, default 20 min)**
Tiempo para platicar, sospechar y acusar en persona. Los muertos siguen en la fiesta pero ya no votan.

**Fase 3 · Votación (3 min)**
Cada jugador vivo vota a una persona. Gana **mayoría relativa** (no promedio). Empate → desempate relámpago de 60 s entre los empatados; si persiste, cuenta como fallo.

**Fase 4 · Veredicto (pantalla + notificación)**
- **Acierto:** el asesino se toma un shot, se revela quién era, cartas nuevas, todos reviven, nueva partida.
- **Fallo:** quienes votaron por el acusado se toman un shot + se revela un secreto aleatorio (anónimo) + el asesino elige una víctima en la app (90 s; si no elige, se asigna una al azar). La víctima recibe "Has muerto" y la /tv lo anuncia. El juego sigue con el mismo asesino.
- **Fin de partida:** si solo quedan vivos el asesino y un jugador, gana el asesino y se reparte de nuevo.

El admin puede pausar el timer, forzar veredicto o terminar la noche.

## 3. Stack

- **Front:** React + Vite + Tailwind, PWA con `vite-plugin-pwa` (manifest + service worker).
- **Back:** Supabase — Postgres, Realtime para estado del juego, Edge Functions para reparto, cierre de votación y veredicto.
- **Timer:** server-authoritative. Se guarda `ends_at` en la ronda; los clientes solo pintan el countdown; `pg_cron` cada 30 s avanza las rondas vencidas.
- **Push:** Web Push (VAPID) desde Edge Function. En iPhone solo funciona con la PWA instalada en pantalla de inicio (iOS 16.4+), así que es un extra, no el canal principal.
- **Identidad:** sin login. El RSVP genera un token por dispositivo. Admin con PIN.
- **Hosting:** Vercel.

**Seguridad no negociable:** con RLS, cada jugador solo puede leer su propio rol. Votos ocultos hasta el veredicto. Los secretos nunca llegan al cliente antes de revelarse.

## 4. Modelo de datos

| Tabla | Campos clave |
|---|---|
| `event` | fecha, dirección, `address_reveal_at`, fase (`invitacion`/`lobby`/`jugando`/`fin`), minutos de ronda y de voto |
| `players` | nombre, hash del token, `checked_in`, `is_admin`, `push_subscription` |
| `secrets` | `author_id`, `about_name`, texto, estado (`pendiente`/`aprobado`/`rechazado`/`revelado`) |
| `games` | número de partida, inicio, fin, resultado |
| `roles` | `game_id`, `player_id`, rol — RLS por jugador |
| `rounds` | `game_id`, estado, `ends_at`, `vote_ends_at`, `accused_id`, `correct`, `revealed_secret_id` |
| `kills` | `round_id`, `killer_id`, `victim_id` |
| `votes` | `round_id`, `voter_id`, `target_id` — único por votante y ronda |
| `shots` | `round_id`, `player_id`, motivo — para el ranking de fin de noche |

## 5. Pantallas

1. **Invitación:** copy, countdown al 24 oct, dress code, dirección bloqueada o revelada, CTA "Acepto".
2. **RSVP:** nombre, secreto, aviso de anonimato.
3. **Lobby:** "Estoy aquí", instalar PWA, esperando reparto.
4. **Mi carta:** carta tipo tarot, mantener presionado para verla (anti-espías).
5. **Ronda:** countdown, estado vivo/muerto.
6. **Votación:** grid de jugadores vivos, confirmar voto.
7. **Veredicto:** acierto o fallo, quién bebe, secreto revelado. Si fue fallo, el asesino ve aquí su selector de víctima.
8. **/tv:** pantalla para proyectar en la tele — countdown grande, veredictos y secretos estilo "blast".
9. **/admin:** aprobar secretos, repartir cartas, pausar timer, revelar dirección, cerrar juego.

## 6. Dirección visual

Gossip Girl original × Coven, como papelería grabada sobre cartulina negra: negro tintado, blanco hueso, peltre para el grabado y rojo sangre solo en el sello de cera. Bodoni Moda (moda, Upper East Side) para titulares y firma XOXO; Jost para texto e interfaz. Momento central: romper el sello para abrir la invitación. Cartas del juego con marco de tarot.

## 7. Supuestos a confirmar

- Confirmado: el asesino elige víctima en la app, una por cada votación fallida.
- Propuesta: una muerte de apertura al repartir cartas, para que la primera votación no sea a ciegas.
- 1 asesino; 2 con más de 16 presentes.
- Al fallar beben quienes votaron por el acusado.
- Rondas de 20 min + 3 min de votación.
