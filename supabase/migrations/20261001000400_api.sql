-- Mariela · 29 — la API que ve el cliente (PostgREST: POST /rest/v1/rpc/<función>).
--
-- Todas son `security definer` y validan quién llama: el token del dispositivo para jugadores, la
-- llave de la /tv, o la sesión de admin. El cliente nunca toca las tablas.

set check_function_bodies = off;

-- ---------------------------------------------------------------------------------------------------
-- Identidad
-- ---------------------------------------------------------------------------------------------------
create or replace function app.token_ok(p_token text) returns boolean
language sql immutable set search_path = pg_temp as
$fn$ select p_token is not null and p_token ~ '^[A-Za-z0-9_-]{32,200}$' $fn$;

create or replace function app.require_player(p_token text) returns app.players
language plpgsql stable set search_path = pg_temp as
$fn$
declare
  v_player app.players;
begin
  if not app.token_ok(p_token) then
    perform app.fail('sin_sesion', 'Este dispositivo no está registrado. Responde la invitación o entra con tu llave.');
  end if;
  select * into v_player from app.players where token_hash = app.hash(p_token);
  if not found then
    perform app.fail('sin_sesion', 'No reconocemos este dispositivo. Entra con tu llave.');
  end if;
  return v_player;
end
$fn$;

-- La llave para recuperar tu lugar si cambias de teléfono o de navegador. Sin O, I, L, 0 ni 1.
create or replace function app.new_key() returns text
language plpgsql volatile set search_path = pg_temp as
$fn$
declare
  c_alphabet constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  v_bytes bytea := extensions.gen_random_bytes(8);
  v_out text := '';
  i int;
begin
  for i in 0..7 loop
    v_out := v_out || substr(c_alphabet, (get_byte(v_bytes, i) % 31) + 1, 1);
  end loop;
  return substr(v_out, 1, 4) || '-' || substr(v_out, 5, 4);
end
$fn$;

create or replace function app.key_hash(p_key text) returns bytea
language sql immutable set search_path = pg_temp as
$fn$ select app.hash(upper(regexp_replace(coalesce(p_key, ''), '[^A-Za-z0-9]', '', 'g'))) $fn$;

-- ---------------------------------------------------------------------------------------------------
-- Estado
-- ---------------------------------------------------------------------------------------------------
create or replace function public.get_state(p_token text default null) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_now timestamptz;
  v_me app.players;
  v_game app.games;
begin
  perform app.advance_if_due();
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  if app.token_ok(p_token) then
    select * into v_me from app.players where token_hash = app.hash(p_token);
  end if;
  if v_me.id is null then
    -- Sin registro solo se ve lo que ve cualquiera: la fecha y la dirección, cuando ya se revela.
    return app.public_state(v_ev, v_now, false) || jsonb_build_object('known', false);
  end if;
  select * into v_game from app.games order by number desc limit 1;
  return app.public_state(v_ev, v_now, true) || jsonb_build_object(
    'known', true,
    'me', app.me_json(v_me, v_game, v_ev, v_now),
    'ranking', case when v_ev.phase = 'fin' then app.ranking_json() end
  );
end
$fn$;

-- La pantalla de la tele no tiene sesión: entra con la llave del enlace que muestra el admin.
create or replace function public.tv_state(p_key text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_now timestamptz;
begin
  perform app.advance_if_due();
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  if p_key is null or p_key <> v_ev.tv_key then
    perform app.fail('sin_permiso', 'Esta pantalla no tiene permiso. Abre el enlace de la /tv desde el admin.');
  end if;
  return app.public_state(v_ev, v_now, true) || jsonb_build_object(
    'door_code', v_ev.door_code,
    'ranking', app.ranking_json()
  );
end
$fn$;

-- Cualquiera puede empujar el reloj: solo hace algo si de verdad venció algo.
create or replace function public.advance() returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
begin
  perform app.advance_if_due();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- RSVP y recuperación
-- ---------------------------------------------------------------------------------------------------
create or replace function public.rsvp(p_token text, p_name text, p_about text, p_text text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_existing app.players;
  v_name text;
  v_about text;
  v_body text;
  v_key text;
  v_player app.players;
begin
  if not app.token_ok(p_token) then
    perform app.fail('token_invalido', 'Este dispositivo no pudo identificarse. Recarga la página e inténtalo otra vez.');
  end if;
  select * into v_existing from app.players where token_hash = app.hash(p_token);
  if found then
    return jsonb_build_object('ok', true, 'existing', true, 'player', jsonb_build_object('id', v_existing.id, 'name', v_existing.name));
  end if;

  select * into v_ev from app.event where id = 1;
  if v_ev.phase = 'fin' then
    perform app.fail('noche_terminada', 'La noche ya terminó.');
  end if;

  v_name := btrim(regexp_replace(regexp_replace(coalesce(p_name, ''), '[[:cntrl:]]', '', 'g'), '\s+', ' ', 'g'));
  v_about := btrim(regexp_replace(regexp_replace(coalesce(p_about, ''), '[[:cntrl:]]', '', 'g'), '\s+', ' ', 'g'));
  v_body := btrim(coalesce(p_text, ''));

  if v_name = '' then perform app.fail('nombre_vacio', 'Escribe tu nombre.'); end if;
  if char_length(v_name) > 40 then perform app.fail('nombre_largo', 'Tu nombre es demasiado largo.'); end if;
  if v_about = '' then perform app.fail('sobre_vacio', 'Escribe de quién es el secreto.'); end if;
  if char_length(v_about) > 40 then perform app.fail('sobre_largo', 'Ese nombre es demasiado largo.'); end if;
  if app.norm(v_about) = app.norm(v_name) then perform app.fail('secreto_propio', 'Tiene que ser de otro invitado.'); end if;
  if v_body = '' then perform app.fail('secreto_vacio', 'Escribe el secreto.'); end if;
  if char_length(v_body) > 280 then perform app.fail('secreto_largo', 'El secreto no puede pasar de 280 caracteres.'); end if;
  if (select count(*) from app.players) >= 80 then perform app.fail('lleno', 'Ya no caben más invitados.'); end if;

  v_key := app.new_key();
  begin
    insert into app.players (name, name_key, token_hash, recovery_hash)
    values (v_name, app.norm(v_name), app.hash(p_token), app.key_hash(v_key))
    returning * into v_player;
  exception when unique_violation then
    perform app.fail('nombre_repetido', 'Ese nombre ya respondió. Si eres tú, entra con tu llave.');
  end;
  insert into app.secrets (author_id, about_name, text) values (v_player.id, v_about, v_body);
  perform app.touch();
  return jsonb_build_object('ok', true, 'existing', false,
                            'player', jsonb_build_object('id', v_player.id, 'name', v_player.name),
                            'recovery_key', v_key);
end
$fn$;

-- Entrar con nombre y llave desde otro dispositivo. Los fallos se devuelven (no se lanzan) para que
-- el contador de intentos sobreviva; con 5 fallos ese nombre se bloquea 10 minutos.
create or replace function public.recover(p_name text, p_key text, p_token text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_player app.players;
  v_now timestamptz := clock_timestamp();
begin
  if not app.token_ok(p_token) then
    perform app.fail('token_invalido', 'Este dispositivo no pudo identificarse. Recarga la página e inténtalo otra vez.');
  end if;
  select * into v_player from app.players where name_key = app.norm(p_name) for update;
  if not found or v_player.recovery_hash is null then
    return jsonb_build_object('ok', false, 'error', 'llave_incorrecta', 'message', 'Ese nombre o esa llave no coinciden.');
  end if;
  if v_player.recovery_locked_until is not null and v_player.recovery_locked_until > v_now then
    return jsonb_build_object('ok', false, 'error', 'bloqueado',
                              'message', 'Demasiados intentos. Espera unos minutos o pídele al admin una llave nueva.');
  end if;
  if v_player.recovery_hash <> app.key_hash(p_key) then
    if v_player.recovery_failures + 1 >= 5 then
      update app.players set recovery_failures = 0, recovery_locked_until = v_now + interval '10 minutes' where id = v_player.id;
    else
      update app.players set recovery_failures = recovery_failures + 1 where id = v_player.id;
    end if;
    return jsonb_build_object('ok', false, 'error', 'llave_incorrecta', 'message', 'Ese nombre o esa llave no coinciden.');
  end if;
  -- El dispositivo anterior pierde el acceso: un solo token por jugador.
  update app.players
     set token_hash = app.hash(p_token), recovery_failures = 0, recovery_locked_until = null
   where id = v_player.id;
  perform app.touch();
  return jsonb_build_object('ok', true, 'player', jsonb_build_object('id', v_player.id, 'name', v_player.name));
end
$fn$;

create or replace function public.replace_secret(p_token text, p_about text, p_text text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_me app.players;
  v_about text;
  v_body text;
  v_secret app.secrets;
begin
  v_me := app.require_player(p_token);
  v_about := btrim(regexp_replace(coalesce(p_about, ''), '\s+', ' ', 'g'));
  v_body := btrim(coalesce(p_text, ''));
  if v_about = '' then perform app.fail('sobre_vacio', 'Escribe de quién es el secreto.'); end if;
  if char_length(v_about) > 40 then perform app.fail('sobre_largo', 'Ese nombre es demasiado largo.'); end if;
  if app.norm(v_about) = v_me.name_key then perform app.fail('secreto_propio', 'Tiene que ser de otro invitado.'); end if;
  if v_body = '' then perform app.fail('secreto_vacio', 'Escribe el secreto.'); end if;
  if char_length(v_body) > 280 then perform app.fail('secreto_largo', 'El secreto no puede pasar de 280 caracteres.'); end if;

  select * into v_secret from app.secrets where author_id = v_me.id order by created_at desc limit 1 for update;
  if found and v_secret.status in ('pendiente', 'rechazado') then
    update app.secrets set about_name = v_about, text = v_body, status = 'pendiente' where id = v_secret.id;
  elsif found then
    perform app.fail('secreto_cerrado', 'Tu secreto ya entró al juego y no se puede cambiar.');
  else
    insert into app.secrets (author_id, about_name, text) values (v_me.id, v_about, v_body);
  end if;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Llegada
-- ---------------------------------------------------------------------------------------------------
create or replace function public.check_in(p_token text, p_code text default null) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_me app.players;
  v_ev app.event;
begin
  v_me := app.require_player(p_token);
  select * into v_ev from app.event where id = 1;
  if v_ev.phase not in ('lobby', 'jugando') then
    perform app.fail('todavia_no', 'Todavía no abren la puerta.');
  end if;
  if v_ev.door_code is not null and upper(btrim(coalesce(p_code, ''))) <> upper(v_ev.door_code) then
    perform app.fail('codigo_incorrecto', 'Ese código no es. Míralo en la pantalla de la entrada.');
  end if;
  update app.players set checked_in = true where id = v_me.id;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Jugadas
-- ---------------------------------------------------------------------------------------------------
create or replace function public.cast_vote(p_token text, p_target uuid) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_me app.players;
  v_ev app.event;
  v_game app.games;
  v_round app.rounds;
  v_role app.roles;
  v_rows int;
begin
  perform app.lock();
  v_me := app.require_player(p_token);
  -- Si la votación ya venció, esto la cierra antes de aceptar nada.
  perform app.advance();
  select * into v_ev from app.event where id = 1;
  if v_ev.paused_at is not null then
    perform app.fail('pausa', 'El juego está en pausa.');
  end if;
  select * into v_game from app.games order by number desc limit 1;
  if not found or v_game.ended_at is not null then
    perform app.fail('sin_partida', 'No hay una partida en curso.');
  end if;
  select * into v_round from app.rounds where game_id = v_game.id order by number desc limit 1;
  if v_round.state not in ('votacion', 'desempate') then
    perform app.fail('no_es_momento', 'La votación no está abierta.');
  end if;
  select * into v_role from app.roles where game_id = v_game.id and player_id = v_me.id;
  if not found then
    perform app.fail('sin_carta', 'Esta partida empezó sin ti. Entras en la siguiente.');
  end if;
  if not v_role.alive then
    perform app.fail('muerto', 'Los muertos no votan.');
  end if;
  if p_target is null or p_target = v_me.id then
    perform app.fail('voto_propio', 'No puedes votar por ti.');
  end if;
  if not exists (select 1 from app.roles where game_id = v_game.id and player_id = p_target and alive) then
    perform app.fail('objetivo_invalido', 'Ese jugador no está en la partida.');
  end if;
  if v_round.state = 'desempate' and not (p_target = any (v_round.candidates)) then
    perform app.fail('fuera_de_desempate', 'En el desempate solo puedes votar a los empatados.');
  end if;

  insert into app.votes (round_id, stage, voter_id, target_id) values (v_round.id, v_round.stage, v_me.id, p_target)
  on conflict do nothing;
  get diagnostics v_rows = row_count;
  if v_rows = 0 then
    perform app.fail('ya_votaste', 'Ya votaste. Los votos no se cambian.');
  end if;

  -- Si ya votaron todos, la votación cierra sin esperar al reloj.
  perform app.advance();
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.kill(p_token text, p_victim uuid) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_me app.players;
  v_ev app.event;
  v_game app.games;
  v_round app.rounds;
  v_role app.roles;
  v_now timestamptz;
begin
  perform app.lock();
  v_me := app.require_player(p_token);
  perform app.advance();
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  if v_ev.paused_at is not null then
    perform app.fail('pausa', 'El juego está en pausa.');
  end if;
  select * into v_game from app.games order by number desc limit 1;
  if not found or v_game.ended_at is not null then
    perform app.fail('sin_partida', 'No hay una partida en curso.');
  end if;
  select * into v_round from app.rounds where game_id = v_game.id order by number desc limit 1;
  select * into v_role from app.roles where game_id = v_game.id and player_id = v_me.id;
  if not found or v_role.role <> 'asesino' or not v_role.alive then
    perform app.fail('no_eres_asesino', 'Solo el asesino puede elegir.');
  end if;
  if not (v_round.state = 'apertura' or (v_round.state = 'veredicto' and v_round.correct is false and v_round.ends_at > v_now)) then
    perform app.fail('fuera_de_ventana', 'Ya no es momento de elegir.');
  end if;
  if exists (select 1 from app.kills where round_id = v_round.id) then
    perform app.fail('ya_elegida', 'La víctima ya fue elegida.');
  end if;
  if p_victim is null or p_victim = v_me.id
     or not exists (select 1 from app.roles where game_id = v_game.id and player_id = p_victim and alive and role = 'inocente') then
    perform app.fail('victima_invalida', 'Esa persona no puede ser tu víctima.');
  end if;

  perform app.apply_kill(v_round, v_me.id, p_victim, false, v_now);
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Push
-- ---------------------------------------------------------------------------------------------------
create or replace function public.save_push(p_token text, p_subscription jsonb) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_me app.players;
begin
  v_me := app.require_player(p_token);
  if p_subscription is not null then
    if jsonb_typeof(p_subscription) <> 'object'
       or coalesce(p_subscription->>'endpoint', '') !~ '^https://'
       or p_subscription->'keys'->>'p256dh' is null
       or p_subscription->'keys'->>'auth' is null then
      perform app.fail('suscripcion_invalida', 'La suscripción a notificaciones no es válida.');
    end if;
  end if;
  update app.players set push_subscription = p_subscription where id = v_me.id;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Permisos: solo estas funciones son alcanzables desde la API pública.
-- ---------------------------------------------------------------------------------------------------
do $$
declare
  r record;
  v_role text;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'
       and p.proname in ('get_state', 'tv_state', 'advance', 'rsvp', 'recover', 'replace_secret', 'check_in', 'cast_vote', 'kill', 'save_push')
  loop
    execute format('revoke all on function %s from public', r.sig);
    foreach v_role in array array['anon', 'authenticated'] loop
      if exists (select 1 from pg_roles where rolname = v_role) then
        execute format('grant execute on function %s to %I', r.sig, v_role);
      end if;
    end loop;
  end loop;
end $$;
