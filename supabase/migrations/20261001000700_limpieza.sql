-- Mariela · 29 — limpieza después de la fiesta.
--
-- Los nombres y los secretos de tus amigos no tienen por qué quedarse en una base de datos. Cuando termine la noche, corre esto
-- a mano en el SQL Editor:
--
--     select app.borrar_datos_de_la_fiesta();
--
-- Borra a los invitados (con sus tokens y llaves), sus secretos y todas las partidas; vacía la dirección y el código de la puerta,
-- apaga el modo ensayo y regresa la app a la invitación. Se queda con tu PIN y con los tiempos que ajustaste.
-- (Otra opción, más radical: borrar el proyecto de Supabase.)

set check_function_bodies = off;

create or replace function app.borrar_datos_de_la_fiesta() returns void
language plpgsql set search_path = pg_temp as
$fn$
begin
  truncate app.players, app.games cascade;
  delete from app.push_queue;
  delete from app.admin_sessions;
  update app.event
     set phase = 'invitacion', paused_at = null, clock_offset = interval '0', rehearsal = false,
         address = null, address_reveal_at = null, address_notified_at = null, door_code = null
   where id = 1;
  perform app.touch();
end
$fn$;
