-- Mariela · 29 — TODO el servidor en un solo pegado.
-- Generado por scripts/generar_setup_sql.py a partir de supabase/migrations/. No lo edites a mano.
--
-- Cómo usarlo: Supabase → SQL Editor → New query → pega este archivo → Run.
-- Luego define tu PIN de admin (una sola vez):   select app.set_admin_pin('tu-pin-de-al-menos-6');

-- ================================================================================
-- 20261001000100_esquema.sql
-- ================================================================================

-- Mariela · 29 — esquema del juego.
--
-- Todo vive en el esquema privado `app`, que la API de Supabase NO expone. El cliente solo entra por
-- las funciones de `public` (ver 20261001000400_api.sql), que validan el token del dispositivo o la
-- sesión de admin. Las tablas tienen RLS activado y ninguna política: aunque alguien tenga la anon key,
-- no puede leer ni escribir nada directamente.

create schema if not exists app;
create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------------------------------
-- Evento: una sola fila con la configuración de la noche y el estado global.
-- ---------------------------------------------------------------------------------------------------
create table if not exists app.event (
  id                 int primary key default 1 check (id = 1),
  starts_at          timestamptz not null default timestamptz '2026-10-24 18:00:00-06',
  address            text,
  address_reveal_at  timestamptz,
  phase              text not null default 'invitacion' check (phase in ('invitacion', 'lobby', 'jugando', 'fin')),
  -- Tiempos, en segundos. El admin los edita en minutos.
  round_seconds      int not null default 1200 check (round_seconds between 5 and 14400),
  vote_seconds       int not null default 180  check (vote_seconds between 5 and 3600),
  tiebreak_seconds   int not null default 60   check (tiebreak_seconds between 5 and 1800),
  kill_seconds       int not null default 90   check (kill_seconds between 5 and 1800),
  pause_seconds      int not null default 30   check (pause_seconds between 0 and 600),
  killers_threshold  int not null default 16   check (killers_threshold between 1 and 100),
  opening_kill       boolean not null default false,
  door_code          text,
  tv_key             text not null default replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', ''),
  paused_at          timestamptz,
  -- Ensayo: reloj adelantable y bots. Se apaga para la noche real.
  rehearsal          boolean not null default false,
  clock_offset       interval not null default interval '0',
  bots_delay_seconds int not null default 4 check (bots_delay_seconds between 0 and 120),
  version            bigint not null default 0,
  updated_at         timestamptz not null default now()
);
-- Cuándo se avisó por push que la dirección ya se reveló (una vez por hora de revelado; se borra al cambiarla).
alter table app.event add column if not exists address_notified_at timestamptz;
insert into app.event (id) values (1) on conflict do nothing;

-- ---------------------------------------------------------------------------------------------------
-- Jugadores. Sin login: `token_hash` es el hash del token que vive en el dispositivo.
-- ---------------------------------------------------------------------------------------------------
create table if not exists app.players (
  id                 uuid primary key default gen_random_uuid(),
  name               text not null check (char_length(name) between 1 and 40),
  name_key           text not null unique,
  token_hash         bytea unique,
  recovery_hash      bytea,
  recovery_failures  int not null default 0,
  recovery_locked_until timestamptz,
  checked_in         boolean not null default false,
  is_bot             boolean not null default false,
  push_subscription  jsonb,
  created_at         timestamptz not null default now()
);

create table if not exists app.secrets (
  id                 uuid primary key default gen_random_uuid(),
  author_id          uuid not null references app.players (id) on delete cascade,
  about_name         text not null check (char_length(about_name) between 1 and 40),
  text               text not null check (char_length(text) between 1 and 280),
  status             text not null default 'pendiente' check (status in ('pendiente', 'aprobado', 'rechazado', 'revelado')),
  revealed_at        timestamptz,
  created_at         timestamptz not null default now()
);
create index if not exists secrets_status_idx on app.secrets (status);
create index if not exists secrets_author_idx on app.secrets (author_id);

-- ---------------------------------------------------------------------------------------------------
-- Partidas y rondas.
-- ---------------------------------------------------------------------------------------------------
create table if not exists app.games (
  id                 uuid primary key default gen_random_uuid(),
  number             int not null unique,
  started_at         timestamptz not null,
  ended_at           timestamptz,
  result             text check (result in ('atrapado', 'asesino_gana', 'cancelada')),
  next_deal_at       timestamptz
);

-- `alive` vive aquí: no hay otra fuente de verdad sobre quién sigue en juego.
create table if not exists app.roles (
  game_id            uuid not null references app.games (id) on delete cascade,
  player_id          uuid not null references app.players (id) on delete cascade,
  role               text not null check (role in ('asesino', 'inocente')),
  alive              boolean not null default true,
  died_at            timestamptz,
  primary key (game_id, player_id)
);
create index if not exists roles_player_idx on app.roles (player_id);

create table if not exists app.rounds (
  id                 uuid primary key default gen_random_uuid(),
  game_id            uuid not null references app.games (id) on delete cascade,
  number             int not null,
  state              text not null check (state in ('apertura', 'discusion', 'votacion', 'desempate', 'veredicto', 'cerrada')),
  -- Vencimiento del estado actual (`ends_at` del spec). Nulo cuando ya no hay nada que esperar.
  ends_at            timestamptz,
  state_since        timestamptz not null,
  stage              int not null default 1 check (stage in (1, 2)),
  candidates         uuid[] not null default '{}',
  accused_id         uuid references app.players (id) on delete set null,
  correct            boolean,
  tie                boolean not null default false,
  revealed_secret_id uuid references app.secrets (id) on delete set null,
  verdict_at         timestamptz,
  unique (game_id, number)
);

create table if not exists app.votes (
  round_id           uuid not null references app.rounds (id) on delete cascade,
  stage              int not null check (stage in (1, 2)),
  voter_id           uuid not null references app.players (id) on delete cascade,
  target_id          uuid not null references app.players (id) on delete cascade,
  created_at         timestamptz not null default now(),
  primary key (round_id, stage, voter_id)
);

create table if not exists app.kills (
  id                 uuid primary key default gen_random_uuid(),
  round_id           uuid not null references app.rounds (id) on delete cascade,
  killer_id          uuid not null references app.players (id) on delete cascade,
  victim_id          uuid not null references app.players (id) on delete cascade,
  auto               boolean not null default false,
  created_at         timestamptz not null default now(),
  unique (round_id)
);

create table if not exists app.shots (
  id                 uuid primary key default gen_random_uuid(),
  round_id           uuid not null references app.rounds (id) on delete cascade,
  player_id          uuid not null references app.players (id) on delete cascade,
  reason             text not null check (reason in ('atrapado', 'voto_fallido', 'empate')),
  created_at         timestamptz not null default now()
);
create index if not exists shots_player_idx on app.shots (player_id);

-- ---------------------------------------------------------------------------------------------------
-- Admin (PIN verificado en el servidor) y notificaciones push.
-- ---------------------------------------------------------------------------------------------------
create table if not exists app.admin (
  id                 int primary key default 1 check (id = 1),
  pin_hash           text,
  failed_attempts    int not null default 0,
  locked_until       timestamptz
);
insert into app.admin (id) values (1) on conflict do nothing;

create table if not exists app.admin_sessions (
  token_hash         bytea primary key,
  expires_at         timestamptz not null
);

create table if not exists app.push_queue (
  id                 bigint generated always as identity primary key,
  player_id          uuid not null references app.players (id) on delete cascade,
  title              text not null,
  body               text not null,
  tag                text,
  created_at         timestamptz not null default now(),
  sent_at            timestamptz,
  attempts           int not null default 0,
  last_error         text
);
create index if not exists push_queue_pending_idx on app.push_queue (id) where sent_at is null;

create table if not exists app.settings (
  key                text primary key,
  value              text not null
);

-- ---------------------------------------------------------------------------------------------------
-- RLS: activado en todo y sin políticas. Ningún rol de la API puede tocar estas tablas.
-- ---------------------------------------------------------------------------------------------------
do $$
declare
  t text;
begin
  for t in select tablename from pg_tables where schemaname = 'app' loop
    execute format('alter table app.%I enable row level security', t);
  end loop;
end $$;

do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on schema app from %I', r);
      execute format('revoke all on all tables in schema app from %I', r);
      execute format('revoke all on all sequences in schema app from %I', r);
      execute format('revoke all on all functions in schema app from %I', r);
    end if;
  end loop;
end $$;

-- ================================================================================
-- 20261001000200_motor.sql
-- ================================================================================

-- Mariela · 29 — el motor del juego.
--
-- Toda la lógica de estado vive aquí: el cliente solo pinta. Cada transición ocurre dentro de una
-- transacción que toma el mismo candado global (`app.lock`), así que dos votos simultáneos, o un voto
-- y el reloj, nunca se pisan. El reloj es `app.now()`: igual a `clock_timestamp()` salvo en ensayo,
-- donde el admin puede adelantarlo para recorrer una noche entera en minutos.

set check_function_bodies = off;

-- ---------------------------------------------------------------------------------------------------
-- Utilidades
-- ---------------------------------------------------------------------------------------------------
create or replace function app.now() returns timestamptz
language sql volatile set search_path = pg_temp as
$fn$ select clock_timestamp() + coalesce((select clock_offset from app.event where id = 1), interval '0') $fn$;

create or replace function app.hash(p_text text) returns bytea
language sql immutable set search_path = pg_temp as
$fn$ select sha256(convert_to(coalesce(p_text, ''), 'UTF8')) $fn$;

-- Clave para comparar nombres: sin acentos, sin mayúsculas, con espacios normalizados.
create or replace function app.norm(p_text text) returns text
language sql immutable set search_path = pg_temp as
$fn$
  select lower(regexp_replace(
    translate(btrim(coalesce(p_text, '')),
      'ÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛÑáàäâãéèëêíìïîóòöôõúùüûñ',
      'AAAAAEEEEIIIIOOOOOUUUUNaaaaaeeeeiiiiooooouuuun'),
    '\s+', ' ', 'g'))
$fn$;

-- Error de juego: `hint` lleva el código para la máquina y `message` el texto para la persona.
create or replace function app.fail(p_code text, p_message text) returns void
language plpgsql set search_path = pg_temp as
$fn$ begin raise exception '%', p_message using errcode = 'P0001', hint = p_code; end $fn$;

create or replace function app.lock() returns void
language sql set search_path = pg_temp as
$fn$ select pg_advisory_xact_lock(7101) $fn$;

-- Sube la versión y avisa por Realtime. El aviso no lleva datos: los clientes vuelven a pedir su estado.
create or replace function app.touch() returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v bigint;
begin
  update app.event set version = version + 1, updated_at = clock_timestamp() where id = 1 returning version into v;
  begin
    if to_regprocedure('realtime.send(jsonb,text,text,boolean)') is not null then
      execute 'select realtime.send($1, $2, $3, $4)' using jsonb_build_object('v', v), 'cambio', 'noche', false;
    end if;
  exception when others then
    null; -- Realtime nunca debe romper una jugada; los clientes también consultan cada pocos segundos.
  end;
end
$fn$;

create or replace function app.enqueue_push(p_players uuid[], p_title text, p_body text, p_tag text default null) returns void
language sql set search_path = pg_temp as
$fn$
  insert into app.push_queue (player_id, title, body, tag)
  select p.id, p_title, p_body, p_tag
  from app.players p
  where p.id = any (coalesce(p_players, '{}')) and p.push_subscription is not null
$fn$;

create or replace function app.alive_count(p_game uuid, p_role text default null) returns int
language sql stable set search_path = pg_temp as
$fn$ select count(*)::int from app.roles where game_id = p_game and alive and (p_role is null or role = p_role) $fn$;

create or replace function app.game_players(p_game uuid, p_only_alive boolean default false) returns uuid[]
language sql stable set search_path = pg_temp as
$fn$ select coalesce(array_agg(player_id), '{}') from app.roles where game_id = p_game and (alive or not p_only_alive) $fn$;

-- ---------------------------------------------------------------------------------------------------
-- Fin de partida y rondas nuevas
-- ---------------------------------------------------------------------------------------------------
create or replace function app.end_game(p_game app.games, p_result text, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
begin
  select * into v_ev from app.event where id = 1;
  update app.games
     set ended_at = p_now,
         result = p_result,
         next_deal_at = case when p_result = 'cancelada' then null else p_now + make_interval(secs => v_ev.pause_seconds) end
   where id = p_game.id;
  if p_result = 'asesino_gana' then
    perform app.enqueue_push(app.game_players(p_game.id), 'Ganó el asesino', 'Nadie lo vio venir. Cartas nuevas en un momento.', 'fin-partida');
  end if;
end
$fn$;

create or replace function app.start_round(p_game uuid, p_number int, p_state text, p_seconds int, p_now timestamptz) returns app.rounds
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_round app.rounds;
begin
  insert into app.rounds (game_id, number, state, ends_at, state_since)
  values (p_game, p_number, p_state, p_now + make_interval(secs => p_seconds), p_now)
  returning * into v_round;
  return v_round;
end
$fn$;

-- Tras una muerte: o termina la partida, o empieza otra ronda.
create or replace function app.after_death(p_game app.games, p_last_round int, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_killers int;
  v_innocents int;
begin
  select * into v_ev from app.event where id = 1;
  v_killers := app.alive_count(p_game.id, 'asesino');
  v_innocents := app.alive_count(p_game.id, 'inocente');
  if v_killers = 0 then
    perform app.end_game(p_game, 'cancelada', p_now);
    update app.games set next_deal_at = p_now + make_interval(secs => v_ev.pause_seconds) where id = p_game.id;
  elsif v_innocents <= 1 then
    perform app.end_game(p_game, 'asesino_gana', p_now);
  else
    perform app.start_round(p_game.id, p_last_round + 1, 'discusion', v_ev.round_seconds, p_now);
  end if;
end
$fn$;

-- La víctima cae. Vale para la muerte de apertura y para la que sigue a un fallo.
create or replace function app.apply_kill(p_round app.rounds, p_killer uuid, p_victim uuid, p_auto boolean, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_game app.games;
begin
  select * into v_game from app.games where id = p_round.game_id;
  insert into app.kills (round_id, killer_id, victim_id, auto, created_at) values (p_round.id, p_killer, p_victim, p_auto, p_now);
  update app.roles set alive = false, died_at = p_now where game_id = v_game.id and player_id = p_victim;
  update app.rounds set state = 'cerrada', ends_at = null where id = p_round.id;
  perform app.enqueue_push(array[p_victim], 'Has muerto', 'Sigues en la fiesta, pero ya no votas.', 'muerte');
  perform app.after_death(v_game, p_round.number, p_now);
end
$fn$;

-- Si el asesino no elige a tiempo, el azar elige por él.
create or replace function app.auto_kill(p_round app.rounds, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_victim uuid;
  v_killer uuid;
  v_game app.games;
begin
  select player_id into v_victim from app.roles
   where game_id = p_round.game_id and alive and role = 'inocente' order by random() limit 1;
  select player_id into v_killer from app.roles
   where game_id = p_round.game_id and alive and role = 'asesino' order by random() limit 1;
  if v_victim is null or v_killer is null then
    -- Nadie a quien matar o nadie que mate: la partida no puede seguir.
    select * into v_game from app.games where id = p_round.game_id;
    update app.rounds set state = 'cerrada', ends_at = null where id = p_round.id;
    perform app.after_death(v_game, p_round.number, p_now);
    return;
  end if;
  perform app.apply_kill(p_round, v_killer, v_victim, true, p_now);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Reparto
-- ---------------------------------------------------------------------------------------------------
-- Devuelve false si no hay jugadores suficientes y el reparto es automático.
create or replace function app.deal(p_now timestamptz, p_auto boolean default false) returns boolean
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_present uuid[];
  v_n int;
  v_k int;
  v_killers uuid[];
  v_game app.games;
  v_number int;
begin
  select * into v_ev from app.event where id = 1;
  select coalesce(array_agg(id), '{}') into v_present from app.players where checked_in;
  v_n := cardinality(v_present);
  if v_n < 3 then
    if p_auto then
      return false;
    end if;
    perform app.fail('pocos_jugadores', 'Se necesitan al menos 3 jugadores presentes para repartir.');
  end if;

  v_k := case when v_n > v_ev.killers_threshold then 2 else 1 end;

  -- Quien menos veces ha sido asesino esta noche tiene prioridad; entre iguales, el azar.
  select coalesce(array_agg(id), '{}') into v_killers from (
    select p.id
      from app.players p
     where p.id = any (v_present)
     order by (select count(*) from app.roles r where r.player_id = p.id and r.role = 'asesino'), random()
     limit v_k
  ) s;

  select coalesce(max(number), 0) + 1 into v_number from app.games;
  insert into app.games (number, started_at) values (v_number, p_now) returning * into v_game;
  insert into app.roles (game_id, player_id, role)
  select v_game.id, p, case when p = any (v_killers) then 'asesino' else 'inocente' end
    from unnest(v_present) p;

  update app.event set phase = 'jugando' where id = 1;

  if v_ev.opening_kill then
    perform app.start_round(v_game.id, 0, 'apertura', v_ev.kill_seconds, p_now);
    perform app.enqueue_push(v_killers, 'Elige a tu primera víctima', 'La noche empieza con sangre. Tienes poco tiempo.', 'apertura');
  else
    perform app.start_round(v_game.id, 1, 'discusion', v_ev.round_seconds, p_now);
  end if;
  perform app.enqueue_push(v_present, 'Tu carta ya está lista', 'Mantén presionado para verla. No se la enseñes a nadie.', 'reparto');
  return true;
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Votación, desempate y veredicto
-- ---------------------------------------------------------------------------------------------------
create or replace function app.open_vote(p_round app.rounds, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
begin
  select * into v_ev from app.event where id = 1;
  update app.rounds
     set state = 'votacion', stage = 1, candidates = '{}',
         ends_at = p_now + make_interval(secs => v_ev.vote_seconds), state_since = p_now
   where id = p_round.id;
  perform app.enqueue_push(app.game_players(p_round.game_id, true), 'Se abrió la votación',
    format('Tienes %s para decidir quién es el asesino.', case when v_ev.vote_seconds >= 60 then (v_ev.vote_seconds / 60) || ' min' else v_ev.vote_seconds || ' s' end), 'votacion');
end
$fn$;

create or replace function app.all_voted(p_round app.rounds) returns boolean
language sql stable set search_path = pg_temp as
$fn$
  select app.alive_count(p_round.game_id) > 0
     and (select count(*) from app.votes where round_id = p_round.id and stage = p_round.stage) >= app.alive_count(p_round.game_id)
$fn$;

create or replace function app.reveal_secret(p_now timestamptz) returns uuid
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_id uuid;
begin
  select id into v_id from app.secrets where status = 'aprobado' order by random() limit 1 for update skip locked;
  if v_id is not null then
    update app.secrets set status = 'revelado', revealed_at = p_now where id = v_id;
  end if;
  return v_id;
end
$fn$;

-- Cierra el veredicto de una ronda. `p_accused` es nulo cuando no hay acusado (empate o nadie votó).
create or replace function app.resolve(p_round app.rounds, p_accused uuid, p_tie boolean, p_finalists uuid[], p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_game app.games;
  v_is_killer boolean := false;
  v_secret uuid;
  v_killers uuid[];
begin
  select * into v_ev from app.event where id = 1;
  select * into v_game from app.games where id = p_round.game_id;
  if p_accused is not null then
    select coalesce(bool_or(role = 'asesino'), false) into v_is_killer
      from app.roles where game_id = v_game.id and player_id = p_accused;
  end if;

  if v_is_killer then
    -- Acierto: el asesino bebe, se revela quién era y la partida termina.
    update app.rounds
       set state = 'veredicto', accused_id = p_accused, correct = true, tie = false, verdict_at = p_now, ends_at = null
     where id = p_round.id;
    insert into app.shots (round_id, player_id, reason) values (p_round.id, p_accused, 'atrapado');
    perform app.end_game(v_game, 'atrapado', p_now);
    perform app.enqueue_push(app.game_players(v_game.id), 'La atraparon',
      'Se acabó la partida. Cartas nuevas en un momento.', 'veredicto');
    return;
  end if;

  -- Fallo: beben quienes votaron por el acusado (o los empatados), sale un secreto y el asesino elige.
  v_secret := app.reveal_secret(p_now);
  update app.rounds
     set state = 'veredicto', accused_id = p_accused, correct = false, tie = p_tie, verdict_at = p_now,
         ends_at = p_now + make_interval(secs => v_ev.kill_seconds), revealed_secret_id = v_secret
   where id = p_round.id;
  if p_accused is not null then
    insert into app.shots (round_id, player_id, reason)
    select p_round.id, voter_id, 'voto_fallido'
      from app.votes where round_id = p_round.id and stage = p_round.stage and target_id = p_accused;
  elsif p_tie then
    insert into app.shots (round_id, player_id, reason)
    select p_round.id, f, 'empate' from unnest(coalesce(p_finalists, '{}')) f;
  end if;

  select coalesce(array_agg(player_id), '{}') into v_killers
    from app.roles where game_id = v_game.id and alive and role = 'asesino';
  perform app.enqueue_push(v_killers, 'Elige a tu víctima', 'Fallaron. Tienes poco tiempo para decidir.', 'victima');
  perform app.enqueue_push(array(select unnest(app.game_players(v_game.id, true)) except select unnest(v_killers)),
    'Fallaron', 'Ya hay veredicto. Alguien lo va a pagar.', 'veredicto');
end
$fn$;

create or replace function app.close_vote(p_round app.rounds, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_max int;
  v_top uuid[];
begin
  select * into v_ev from app.event where id = 1;
  select max(n) into v_max from (
    select count(*) as n from app.votes where round_id = p_round.id and stage = p_round.stage group by target_id
  ) t;

  if v_max is null then
    -- Nadie votó.
    if p_round.stage = 1 then
      perform app.resolve(p_round, null, false, '{}', p_now);
    else
      perform app.resolve(p_round, null, true, p_round.candidates, p_now);
    end if;
    return;
  end if;

  select array_agg(target_id) into v_top from (
    select target_id from app.votes where round_id = p_round.id and stage = p_round.stage
     group by target_id having count(*) = v_max
  ) t;

  if cardinality(v_top) = 1 then
    perform app.resolve(p_round, v_top[1], false, '{}', p_now);
  elsif p_round.stage = 1 then
    -- Empate: desempate relámpago solo entre los empatados.
    update app.rounds
       set state = 'desempate', stage = 2, candidates = v_top,
           ends_at = p_now + make_interval(secs => v_ev.tiebreak_seconds), state_since = p_now
     where id = p_round.id;
    perform app.enqueue_push(app.game_players(p_round.game_id, true), 'Empate',
      format('Desempate relámpago: %s segundos.', v_ev.tiebreak_seconds), 'votacion');
  else
    -- El empate persiste: cuenta como fallo y beben los empatados.
    perform app.resolve(p_round, null, true, v_top, p_now);
  end if;
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Bots de ensayo: votan y matan solos, unos segundos después de que se abre cada momento.
-- ---------------------------------------------------------------------------------------------------
create or replace function app.bots_act(p_round app.rounds, p_now timestamptz) returns boolean
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_bot record;
  v_target uuid;
  v_acted boolean := false;
  v_victim uuid;
begin
  select * into v_ev from app.event where id = 1;
  if p_round.state_since + make_interval(secs => v_ev.bots_delay_seconds) > p_now then
    return false;
  end if;

  if p_round.state in ('votacion', 'desempate') then
    for v_bot in
      select r.player_id from app.roles r join app.players p on p.id = r.player_id
       where r.game_id = p_round.game_id and r.alive and p.is_bot
         and not exists (select 1 from app.votes v where v.round_id = p_round.id and v.stage = p_round.stage and v.voter_id = r.player_id)
    loop
      select r.player_id into v_target from app.roles r
       where r.game_id = p_round.game_id and r.alive and r.player_id <> v_bot.player_id
         and (p_round.state = 'votacion' or r.player_id = any (p_round.candidates))
       order by random() limit 1;
      if v_target is not null then
        insert into app.votes (round_id, stage, voter_id, target_id) values (p_round.id, p_round.stage, v_bot.player_id, v_target)
        on conflict do nothing;
        v_acted := true;
      end if;
    end loop;
    return v_acted;
  end if;

  if p_round.state = 'apertura' or (p_round.state = 'veredicto' and not coalesce(p_round.correct, false)) then
    select r.player_id into v_bot from app.roles r join app.players p on p.id = r.player_id
     where r.game_id = p_round.game_id and r.alive and r.role = 'asesino' and p.is_bot limit 1;
    if v_bot.player_id is not null then
      select player_id into v_victim from app.roles
       where game_id = p_round.game_id and alive and role = 'inocente' order by random() limit 1;
      if v_victim is not null then
        perform app.apply_kill(p_round, v_bot.player_id, v_victim, false, p_now);
        return true;
      end if;
    end if;
  end if;
  return false;
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- El reloj: una transición por paso, hasta que no quede nada vencido.
-- ---------------------------------------------------------------------------------------------------
create or replace function app.step() returns boolean
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_now timestamptz := app.now();
  v_game app.games;
  v_round app.rounds;
begin
  select * into v_ev from app.event where id = 1;
  if v_ev.phase <> 'jugando' or v_ev.paused_at is not null then
    return false;
  end if;

  select * into v_game from app.games order by number desc limit 1;
  if not found then
    return false;
  end if;

  if v_game.ended_at is not null then
    -- Entre partidas: al vencer la pausa se reparte otra vez, si hay gente.
    if v_game.next_deal_at is not null and v_game.next_deal_at <= v_now then
      if app.deal(v_now, true) then
        return true;
      end if;
      update app.games set next_deal_at = v_now + interval '10 seconds' where id = v_game.id;
    end if;
    return false;
  end if;

  select * into v_round from app.rounds where game_id = v_game.id order by number desc limit 1;
  if not found then
    return false;
  end if;

  if v_ev.rehearsal and app.bots_act(v_round, v_now) then
    -- Puede haber cambiado la ronda; el ciclo vuelve a evaluar.
    return true;
  end if;

  if v_round.state = 'apertura' and v_round.ends_at <= v_now then
    perform app.auto_kill(v_round, v_now);
    return true;
  elsif v_round.state = 'discusion' and v_round.ends_at <= v_now then
    perform app.open_vote(v_round, v_now);
    return true;
  elsif v_round.state in ('votacion', 'desempate') and (v_round.ends_at <= v_now or app.all_voted(v_round)) then
    perform app.close_vote(v_round, v_now);
    return true;
  elsif v_round.state = 'veredicto' and not coalesce(v_round.correct, false) and v_round.ends_at <= v_now then
    perform app.auto_kill(v_round, v_now);
    return true;
  end if;
  return false;
end
$fn$;

create or replace function app.advance() returns boolean
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_changed boolean := false;
  i int;
begin
  perform app.lock();
  for i in 1..12 loop
    exit when not app.step();
    v_changed := true;
  end loop;
  if v_changed then
    perform app.touch();
  end if;
  return v_changed;
end
$fn$;

-- La dirección se revela a su hora: quien tenga los avisos activados se entera sin abrir la app. Una sola vez por hora de revelado.
create or replace function app.avisar_direccion() returns void
language plpgsql set search_path = pg_temp as
$fn$
begin
  if not exists (select 1 from app.event e
                  where e.address is not null and e.address_reveal_at is not null
                    and e.address_reveal_at <= app.now() and e.address_notified_at is null) then
    return;
  end if;
  perform app.lock();
  -- Con el candado tomado se vuelve a comprobar: veinte teléfonos consultando a la vez avisan una sola vez.
  update app.event set address_notified_at = app.now()
   where id = 1 and address is not null and address_reveal_at is not null
     and address_reveal_at <= app.now() and address_notified_at is null;
  if found then
    perform app.enqueue_push(array(select id from app.players), 'Ya sabes dónde es',
                             'La dirección se reveló. Ábrela en la invitación.', 'direccion');
    perform app.touch();
  end if;
end
$fn$;

-- Barato: solo entra al candado si hay algo vencido. Lo llaman los clientes al consultar su estado.
create or replace function app.advance_if_due() returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_now timestamptz := app.now();
  v_due boolean;
begin
  perform app.avisar_direccion();
  select exists (
    select 1
      from app.event e
     where e.phase = 'jugando' and e.paused_at is null
       and (
         exists (select 1 from app.rounds r join app.games g on g.id = r.game_id
                  where g.ended_at is null and r.ends_at is not null and r.ends_at <= v_now
                    and r.state in ('apertura', 'discusion', 'votacion', 'desempate', 'veredicto'))
         or exists (select 1 from app.games g
                     where g.ended_at is not null and g.next_deal_at is not null and g.next_deal_at <= v_now
                       and not exists (select 1 from app.games g2 where g2.number > g.number))
         or (e.rehearsal and exists (select 1 from app.players b where b.is_bot))
         or exists (select 1 from app.rounds r join app.games g on g.id = r.game_id
                     where g.ended_at is null and r.state in ('votacion', 'desempate') and app.all_voted(r))
       )
  ) into v_due;
  if v_due then
    perform app.advance();
  end if;
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Alguien sale de la partida a medias (el admin lo quita o lo marca como ausente).
-- ---------------------------------------------------------------------------------------------------
create or replace function app.drop_from_game(p_player uuid, p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_game app.games;
  v_ev app.event;
begin
  select * into v_game from app.games order by number desc limit 1;
  if not found or v_game.ended_at is not null then
    return;
  end if;
  update app.roles set alive = false, died_at = p_now
   where game_id = v_game.id and player_id = p_player and alive;
  if not found then
    return;
  end if;
  select * into v_ev from app.event where id = 1;
  if app.alive_count(v_game.id, 'asesino') = 0 then
    perform app.end_game(v_game, 'cancelada', p_now);
    update app.games set next_deal_at = p_now + make_interval(secs => v_ev.pause_seconds) where id = v_game.id;
  elsif app.alive_count(v_game.id, 'inocente') <= 1 then
    perform app.end_game(v_game, 'asesino_gana', p_now);
  end if;
end
$fn$;

-- ================================================================================
-- 20261001000300_estado.sql
-- ================================================================================

-- Mariela · 29 — qué ve cada quien.
--
-- Estas funciones arman el JSON que recibe el cliente. Aquí se cumplen las reglas de visibilidad:
--   · Cada jugador recibe SOLO su propio rol (y el de su cómplice, si es asesino).
--   · Los votos no salen hasta que hay veredicto; antes solo se cuenta cuántos van.
--   · Un secreto solo sale cuando está `revelado`, y nunca con su autor.
--   · La dirección solo sale cuando ya pasó `address_reveal_at`.

set check_function_bodies = off;

create or replace function app.person_json(p_id uuid) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select case when p_id is null then null
              else (select jsonb_build_object('id', p.id, 'name', p.name) from app.players p where p.id = p_id) end
$fn$;

create or replace function app.event_json(p_ev app.event, p_now timestamptz) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select jsonb_build_object(
    'phase', p_ev.phase,
    'starts_at', p_ev.starts_at,
    'address_reveal_at', p_ev.address_reveal_at,
    'address_revealed', (p_ev.address is not null and p_ev.address_reveal_at is not null and p_now >= p_ev.address_reveal_at),
    'address', case when p_ev.address is not null and p_ev.address_reveal_at is not null and p_now >= p_ev.address_reveal_at
                    then p_ev.address end,
    'paused_at', p_ev.paused_at,
    'opening_kill', p_ev.opening_kill,
    'door_code_required', p_ev.door_code is not null,
    'rehearsal', p_ev.rehearsal,
    'durations', jsonb_build_object('round', p_ev.round_seconds, 'vote', p_ev.vote_seconds,
                                    'tiebreak', p_ev.tiebreak_seconds, 'kill', p_ev.kill_seconds, 'pause', p_ev.pause_seconds),
    'rsvp_count', (select count(*) from app.players),
    'present_count', (select count(*) from app.players where checked_in)
  )
$fn$;

create or replace function app.players_json(p_game uuid) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', p.id, 'name', p.name, 'checked_in', p.checked_in, 'bot', p.is_bot,
           'in_game', r.player_id is not null, 'alive', r.alive) order by p.name), '[]'::jsonb)
    from app.players p
    left join app.roles r on r.game_id = p_game and r.player_id = p.id
$fn$;

-- Lo que se sabe de una ronda una vez que hay veredicto.
create or replace function app.verdict_json(p_round app.rounds) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select jsonb_build_object(
    'at', p_round.verdict_at,
    'accused', app.person_json(p_round.accused_id),
    'correct', p_round.correct,
    'tie', p_round.tie,
    'stage', p_round.stage,
    'tally', (
      select coalesce(jsonb_agg(jsonb_build_object('id', t.target_id, 'name', p.name, 'votes', t.n) order by t.n desc, p.name), '[]'::jsonb)
        from (select target_id, count(*) as n from app.votes where round_id = p_round.id and stage = p_round.stage group by target_id) t
        join app.players p on p.id = t.target_id),
    'first_tally', case when p_round.stage = 2 then (
      select coalesce(jsonb_agg(jsonb_build_object('id', t.target_id, 'name', p.name, 'votes', t.n) order by t.n desc, p.name), '[]'::jsonb)
        from (select target_id, count(*) as n from app.votes where round_id = p_round.id and stage = 1 group by target_id) t
        join app.players p on p.id = t.target_id) end,
    'votes', (
      select coalesce(jsonb_agg(jsonb_build_object('voter', pv.name, 'target', pt.name) order by pv.name), '[]'::jsonb)
        from app.votes v
        join app.players pv on pv.id = v.voter_id
        join app.players pt on pt.id = v.target_id
       where v.round_id = p_round.id and v.stage = p_round.stage),
    'drinkers', (
      select coalesce(jsonb_agg(jsonb_build_object('id', s.player_id, 'name', p.name, 'reason', s.reason) order by p.name), '[]'::jsonb)
        from app.shots s join app.players p on p.id = s.player_id where s.round_id = p_round.id),
    'secret', (
      select jsonb_build_object('about', sc.about_name, 'text', sc.text)
        from app.secrets sc where sc.id = p_round.revealed_secret_id and sc.status = 'revelado'),
    'victim', (
      select jsonb_build_object('id', k.victim_id, 'name', p.name, 'auto', k.auto, 'at', k.created_at)
        from app.kills k join app.players p on p.id = k.victim_id where k.round_id = p_round.id),
    'kill_ends_at', case when p_round.state = 'veredicto' and p_round.correct is false then p_round.ends_at end
  )
$fn$;

create or replace function app.round_json(p_round app.rounds) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select jsonb_build_object(
    'id', p_round.id,
    'number', p_round.number,
    'state', p_round.state,
    'stage', p_round.stage,
    'ends_at', p_round.ends_at,
    'state_since', p_round.state_since,
    'votes_cast', (select count(*) from app.votes v where v.round_id = p_round.id and v.stage = p_round.stage),
    'votes_expected', app.alive_count(p_round.game_id),
    'candidates', case when p_round.state = 'desempate' then (
      select coalesce(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name) order by p.name), '[]'::jsonb)
        from app.players p where p.id = any (p_round.candidates)) else '[]'::jsonb end,
    'verdict', case when p_round.verdict_at is not null then app.verdict_json(p_round) end
  )
$fn$;

create or replace function app.game_json(p_game app.games) returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select jsonb_build_object(
    'id', p_game.id,
    'number', p_game.number,
    'started_at', p_game.started_at,
    'ended', p_game.ended_at is not null,
    'ended_at', p_game.ended_at,
    'result', p_game.result,
    'next_deal_at', p_game.next_deal_at,
    -- Los asesinos se revelan cuando la partida termina, no antes.
    'killers', case when p_game.ended_at is not null then (
      select coalesce(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name) order by p.name), '[]'::jsonb)
        from app.roles r join app.players p on p.id = r.player_id
       where r.game_id = p_game.id and r.role = 'asesino') end,
    'alive_count', app.alive_count(p_game.id),
    'round', (select app.round_json(r) from app.rounds r where r.game_id = p_game.id order by r.number desc limit 1),
    'history', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'number', r.number,
               'state', r.state,
               'verdict', case when r.verdict_at is not null then app.verdict_json(r) end,
               'victim', (select jsonb_build_object('id', k.victim_id, 'name', p.name, 'at', k.created_at)
                            from app.kills k join app.players p on p.id = k.victim_id where k.round_id = r.id)
             ) order by r.number), '[]'::jsonb)
        from app.rounds r
       where r.game_id = p_game.id and (r.state = 'cerrada' or r.verdict_at is not null)),
    'last_kill', (
      select jsonb_build_object('victim', app.person_json(k.victim_id), 'at', k.created_at)
        from app.kills k join app.rounds r on r.id = k.round_id
       where r.game_id = p_game.id order by k.created_at desc limit 1)
  )
$fn$;

-- Lo que sabe UN jugador de sí mismo: su rol, su voto y lo que puede hacer ahora.
create or replace function app.me_json(p_me app.players, p_game app.games, p_ev app.event, p_now timestamptz) returns jsonb
language plpgsql stable set search_path = pg_temp as
$fn$
declare
  v_role app.roles;
  v_round app.rounds;
  v_vote uuid;
  v_can_vote boolean := false;
  v_can_kill boolean := false;
  v_vote_targets jsonb := '[]'::jsonb;
  v_kill_targets jsonb := '[]'::jsonb;
  v_accomplices jsonb := '[]'::jsonb;
  v_secret jsonb;
begin
  if p_game.id is not null then
    select * into v_role from app.roles where game_id = p_game.id and player_id = p_me.id;
    select * into v_round from app.rounds where game_id = p_game.id order by number desc limit 1;
  end if;

  if v_role.player_id is not null and v_role.role = 'asesino' then
    select coalesce(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name) order by p.name), '[]'::jsonb) into v_accomplices
      from app.roles r join app.players p on p.id = r.player_id
     where r.game_id = p_game.id and r.role = 'asesino' and r.player_id <> p_me.id;
  end if;

  if v_role.player_id is not null and v_role.alive and p_game.ended_at is null and v_round.id is not null and p_ev.paused_at is null then
    if v_round.state in ('votacion', 'desempate') then
      select target_id into v_vote from app.votes where round_id = v_round.id and stage = v_round.stage and voter_id = p_me.id;
      if v_vote is null then
        v_can_vote := true;
        select coalesce(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name) order by p.name), '[]'::jsonb) into v_vote_targets
          from app.roles r join app.players p on p.id = r.player_id
         where r.game_id = p_game.id and r.alive and r.player_id <> p_me.id
           and (v_round.state = 'votacion' or r.player_id = any (v_round.candidates));
      end if;
    end if;
    if v_role.role = 'asesino'
       and (v_round.state = 'apertura' or (v_round.state = 'veredicto' and v_round.correct is false and v_round.ends_at > p_now))
       and not exists (select 1 from app.kills where round_id = v_round.id) then
      v_can_kill := true;
      select coalesce(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name) order by p.name), '[]'::jsonb) into v_kill_targets
        from app.roles r join app.players p on p.id = r.player_id
       where r.game_id = p_game.id and r.alive and r.role = 'inocente';
    end if;
  elsif v_round.id is not null and v_role.player_id is not null and v_round.state in ('votacion', 'desempate') then
    select target_id into v_vote from app.votes where round_id = v_round.id and stage = v_round.stage and voter_id = p_me.id;
  end if;

  select jsonb_build_object('id', s.id, 'status', s.status, 'about', s.about_name, 'text', s.text) into v_secret
    from app.secrets s where s.author_id = p_me.id order by s.created_at desc limit 1;

  return jsonb_build_object(
    'id', p_me.id,
    'name', p_me.name,
    'checked_in', p_me.checked_in,
    'in_game', v_role.player_id is not null,
    'alive', v_role.alive,
    'role', v_role.role,
    'accomplices', v_accomplices,
    'my_vote', case when v_vote is not null then app.person_json(v_vote) end,
    'can_vote', v_can_vote,
    'vote_targets', v_vote_targets,
    'can_kill', v_can_kill,
    'kill_targets', v_kill_targets,
    'secret', v_secret,
    'push', p_me.push_subscription is not null
  );
end
$fn$;

-- Números de la noche. Sale al final y en la /tv: quién bebió, quién mató, quién acertó.
create or replace function app.ranking_json() returns jsonb
language sql stable set search_path = pg_temp as
$fn$
  select jsonb_build_object(
    'games', (select count(*) from app.games),
    'caught', (select count(*) from app.games where result = 'atrapado'),
    'killer_wins', (select count(*) from app.games where result = 'asesino_gana'),
    'players', (
      select coalesce(jsonb_agg(to_jsonb(x) order by x.shots desc, x.kills desc, x.name), '[]'::jsonb)
        from (
          select p.id, p.name,
                 (select count(*) from app.shots s where s.player_id = p.id) as shots,
                 (select count(*) from app.kills k where k.killer_id = p.id and not k.auto) as kills,
                 (select count(*) from app.votes v
                    join app.rounds rr on rr.id = v.round_id
                    join app.roles ro on ro.game_id = rr.game_id and ro.player_id = v.target_id
                   where v.voter_id = p.id and ro.role = 'asesino') as correct_votes,
                 (select count(*) from app.votes v where v.target_id = p.id) as votes_received,
                 (select count(*) from app.roles ro where ro.player_id = p.id and ro.role = 'asesino') as times_killer
            from app.players p
           where exists (select 1 from app.roles ro where ro.player_id = p.id)
        ) x)
  )
$fn$;

create or replace function app.public_state(p_ev app.event, p_now timestamptz, p_names boolean) returns jsonb
language plpgsql stable set search_path = pg_temp as
$fn$
declare
  v_game app.games;
begin
  select * into v_game from app.games order by number desc limit 1;
  if not p_names then
    return jsonb_build_object('now', p_now, 'version', p_ev.version, 'event', app.event_json(p_ev, p_now));
  end if;
  return jsonb_build_object(
    'now', p_now,
    'version', p_ev.version,
    'event', app.event_json(p_ev, p_now),
    'players', app.players_json(v_game.id),
    'game', case when v_game.id is not null then app.game_json(v_game) end
  );
end
$fn$;

-- ================================================================================
-- 20261001000400_api.sql
-- ================================================================================

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

-- ================================================================================
-- 20261001000500_admin.sql
-- ================================================================================

-- Mariela · 29 — panel de admin.
--
-- El PIN se verifica aquí, en el servidor, y nunca sale. `admin_login` entrega una sesión de 12 horas;
-- cada función de admin la exige. El panel NO muestra roles ni votos (quien organiza también juega);
-- solo en modo ensayo existe una vista "dios" para depurar.

set check_function_bodies = off;

-- Se corre una vez desde el SQL Editor de Supabase:  select app.set_admin_pin('tu-pin');
create or replace function app.set_admin_pin(p_pin text) returns void
language plpgsql set search_path = pg_temp as
$fn$
begin
  if char_length(coalesce(p_pin, '')) < 6 then
    raise exception 'El PIN debe tener al menos 6 caracteres.';
  end if;
  update app.admin
     set pin_hash = extensions.crypt(p_pin, extensions.gen_salt('bf', 10)), failed_attempts = 0, locked_until = null
   where id = 1;
  delete from app.admin_sessions;
end
$fn$;

create or replace function app.require_admin(p_session text) returns void
language plpgsql set search_path = pg_temp as
$fn$
begin
  if p_session is null or char_length(p_session) < 20
     or not exists (select 1 from app.admin_sessions where token_hash = app.hash(p_session) and expires_at > clock_timestamp()) then
    perform app.fail('sin_permiso', 'Tu sesión de admin venció. Entra otra vez con tu PIN.');
  end if;
end
$fn$;

create or replace function public.admin_login(p_pin text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_admin app.admin;
  v_now timestamptz := clock_timestamp();
  v_token text;
  v_wait int;
  v_failed int;
begin
  select * into v_admin from app.admin where id = 1 for update;
  if v_admin.pin_hash is null then
    return jsonb_build_object('ok', false, 'error', 'sin_pin',
      'message', 'Falta definir el PIN del admin. Corre  select app.set_admin_pin(''tu-pin'');  en el SQL Editor.');
  end if;
  if v_admin.locked_until is not null and v_admin.locked_until > v_now then
    v_wait := ceil(extract(epoch from v_admin.locked_until - v_now));
    return jsonb_build_object('ok', false, 'error', 'bloqueado', 'retry_after', v_wait,
      'message', format('Demasiados intentos. Espera %s s.', v_wait));
  end if;

  if extensions.crypt(coalesce(p_pin, ''), v_admin.pin_hash) is distinct from v_admin.pin_hash then
    v_failed := v_admin.failed_attempts + 1;
    -- A partir del quinto fallo: 1, 2, 4… minutos de bloqueo, hasta 30.
    update app.admin
       set failed_attempts = v_failed,
           locked_until = case when v_failed >= 5
                               then v_now + make_interval(mins => least(30, (2 ^ (v_failed - 5))::int)) end
     where id = 1;
    return jsonb_build_object('ok', false, 'error', 'pin_incorrecto', 'message', 'PIN incorrecto.');
  end if;

  update app.admin set failed_attempts = 0, locked_until = null where id = 1;
  delete from app.admin_sessions where expires_at <= v_now;
  v_token := translate(encode(extensions.gen_random_bytes(24), 'base64'), '+/=', '-_');
  insert into app.admin_sessions (token_hash, expires_at) values (app.hash(v_token), v_now + interval '12 hours');
  return jsonb_build_object('ok', true, 'session', v_token, 'expires_at', v_now + interval '12 hours');
end
$fn$;

create or replace function public.admin_logout(p_session text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
begin
  delete from app.admin_sessions where token_hash = app.hash(p_session);
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.admin_set_pin(p_session text, p_new text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
begin
  perform app.require_admin(p_session);
  if char_length(coalesce(p_new, '')) < 6 then
    perform app.fail('pin_corto', 'El PIN debe tener al menos 6 caracteres.');
  end if;
  perform app.set_admin_pin(p_new);
  return jsonb_build_object('ok', true, 'relogin', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Lectura
-- ---------------------------------------------------------------------------------------------------
create or replace function public.admin_state(p_session text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_now timestamptz;
  v_game app.games;
begin
  perform app.require_admin(p_session);
  perform app.advance_if_due();
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  select * into v_game from app.games order by number desc limit 1;
  return jsonb_build_object(
    'now', v_now,
    'version', v_ev.version,
    'event', app.event_json(v_ev, v_now) || jsonb_build_object(
      'address', v_ev.address,
      'door_code', v_ev.door_code,
      'tv_key', v_ev.tv_key,
      'killers_threshold', v_ev.killers_threshold,
      'bots_delay_seconds', v_ev.bots_delay_seconds,
      'clock_offset_seconds', extract(epoch from v_ev.clock_offset)::bigint),
    'players', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'id', p.id, 'name', p.name, 'checked_in', p.checked_in, 'bot', p.is_bot,
               'has_secret', exists (select 1 from app.secrets s where s.author_id = p.id),
               'push', p.push_subscription is not null,
               'device', p.token_hash is not null,
               'in_game', r.player_id is not null, 'alive', r.alive) order by p.created_at), '[]'::jsonb)
        from app.players p
        left join app.roles r on r.game_id = v_game.id and r.player_id = p.id),
    -- Sin autor: quien modera lee los secretos sin saber de quién son.
    'secrets', (
      select coalesce(jsonb_agg(jsonb_build_object('id', s.id, 'about', s.about_name, 'text', s.text, 'status', s.status)
               order by case s.status when 'pendiente' then 0 when 'aprobado' then 1 when 'rechazado' then 2 else 3 end, md5(s.id::text)),
             '[]'::jsonb)
        from app.secrets s),
    'game', case when v_game.id is not null then app.game_json(v_game) end,
    'ranking', app.ranking_json()
  );
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Escritura
-- ---------------------------------------------------------------------------------------------------
create or replace function app.rehearsal_off(p_now timestamptz) returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_bot record;
begin
  for v_bot in select id from app.players where is_bot loop
    perform app.drop_from_game(v_bot.id, p_now);
  end loop;
  delete from app.players where is_bot;
  update app.event set clock_offset = interval '0' where id = 1;
end
$fn$;

create or replace function public.admin_config(p_session text, p_changes jsonb) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  c_allowed constant text[] := array['starts_at', 'address', 'address_reveal_at', 'round_seconds', 'vote_seconds',
    'tiebreak_seconds', 'kill_seconds', 'pause_seconds', 'killers_threshold', 'opening_kill', 'door_code', 'rehearsal',
    'bots_delay_seconds'];
  v_key text;
  v_ev app.event;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
    perform app.fail('valor_invalido', 'No llegaron cambios.');
  end if;
  for v_key in select jsonb_object_keys(p_changes) loop
    if not (v_key = any (c_allowed)) then
      perform app.fail('campo_desconocido', format('Campo desconocido: %s', v_key));
    end if;
  end loop;
  select * into v_ev from app.event where id = 1;

  begin
    update app.event set
      starts_at = case when p_changes ? 'starts_at' then (p_changes->>'starts_at')::timestamptz else starts_at end,
      address = case when p_changes ? 'address' then nullif(btrim(p_changes->>'address'), '') else address end,
      address_reveal_at = case when p_changes ? 'address_reveal_at' then nullif(p_changes->>'address_reveal_at', '')::timestamptz else address_reveal_at end,
      address_notified_at = case when p_changes ? 'address_reveal_at' then null else address_notified_at end,
      round_seconds = case when p_changes ? 'round_seconds' then (p_changes->>'round_seconds')::int else round_seconds end,
      vote_seconds = case when p_changes ? 'vote_seconds' then (p_changes->>'vote_seconds')::int else vote_seconds end,
      tiebreak_seconds = case when p_changes ? 'tiebreak_seconds' then (p_changes->>'tiebreak_seconds')::int else tiebreak_seconds end,
      kill_seconds = case when p_changes ? 'kill_seconds' then (p_changes->>'kill_seconds')::int else kill_seconds end,
      pause_seconds = case when p_changes ? 'pause_seconds' then (p_changes->>'pause_seconds')::int else pause_seconds end,
      killers_threshold = case when p_changes ? 'killers_threshold' then (p_changes->>'killers_threshold')::int else killers_threshold end,
      opening_kill = case when p_changes ? 'opening_kill' then (p_changes->>'opening_kill')::boolean else opening_kill end,
      door_code = case when p_changes ? 'door_code' then nullif(upper(btrim(p_changes->>'door_code')), '') else door_code end,
      rehearsal = case when p_changes ? 'rehearsal' then (p_changes->>'rehearsal')::boolean else rehearsal end,
      bots_delay_seconds = case when p_changes ? 'bots_delay_seconds' then (p_changes->>'bots_delay_seconds')::int else bots_delay_seconds end
    where id = 1;
  exception when check_violation or invalid_text_representation or invalid_datetime_format
                or datetime_field_overflow or numeric_value_out_of_range then
    perform app.fail('valor_invalido', 'Alguno de los valores no es válido.');
  end;

  -- Al apagar el ensayo se van los bots y el reloj vuelve a la hora real.
  if v_ev.rehearsal and not (select rehearsal from app.event where id = 1) then
    perform app.rehearsal_off(app.now());
  end if;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.admin_phase(p_session text, p_phase text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_game app.games;
  v_previa text;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  if p_phase not in ('invitacion', 'lobby') then
    perform app.fail('fase_invalida', 'Solo puedes volver a la invitación o abrir la puerta (lobby). El juego empieza al repartir.');
  end if;
  select * into v_game from app.games order by number desc limit 1;
  if found and v_game.ended_at is null then
    perform app.fail('partida_en_curso', 'Hay una partida en curso. Termina la noche primero.');
  end if;
  select phase into v_previa from app.event where id = 1;
  update app.event set phase = p_phase, paused_at = null where id = 1;
  if p_phase = 'lobby' and v_previa <> 'lobby' then
    perform app.enqueue_push(array(select id from app.players where not checked_in), 'La puerta está abierta',
                             'Ya puedes marcar "Estoy aquí" cuando llegues.', 'puerta');
  end if;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.admin_secret(p_session text, p_id uuid, p_status text default null, p_about text default null, p_text text default null)
returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_secret app.secrets;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  select * into v_secret from app.secrets where id = p_id for update;
  if not found then
    perform app.fail('no_existe', 'Ese secreto ya no existe.');
  end if;
  if p_status is not null and p_status not in ('pendiente', 'aprobado', 'rechazado') then
    perform app.fail('estado_invalido', 'Un secreto solo puede quedar pendiente, aprobado o rechazado.');
  end if;
  if v_secret.status = 'revelado' then
    perform app.fail('ya_revelado', 'Ese secreto ya salió a la luz.');
  end if;
  if p_about is not null and (btrim(p_about) = '' or char_length(btrim(p_about)) > 40) then
    perform app.fail('sobre_vacio', 'El nombre del secreto tiene que tener entre 1 y 40 caracteres.');
  end if;
  if p_text is not null and (btrim(p_text) = '' or char_length(btrim(p_text)) > 280) then
    perform app.fail('secreto_vacio', 'El secreto tiene que tener entre 1 y 280 caracteres.');
  end if;
  update app.secrets
     set status = coalesce(p_status, status),
         about_name = coalesce(nullif(btrim(p_about), ''), about_name),
         text = coalesce(nullif(btrim(p_text), ''), text)
   where id = p_id;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.admin_approve_all(p_session text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_n int;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  update app.secrets set status = 'aprobado' where status = 'pendiente';
  get diagnostics v_n = row_count;
  perform app.touch();
  return jsonb_build_object('ok', true, 'approved', v_n);
end
$fn$;

create or replace function public.admin_player(p_session text, p_id uuid, p_action text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_now timestamptz;
  v_key text;
  v_player app.players;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  v_now := app.now();
  select * into v_player from app.players where id = p_id for update;
  if not found then
    perform app.fail('no_existe', 'Ese invitado ya no existe.');
  end if;

  if p_action = 'check_in' then
    update app.players set checked_in = true where id = p_id;
  elsif p_action = 'check_out' then
    update app.players set checked_in = false where id = p_id;
    perform app.drop_from_game(p_id, v_now);
  elsif p_action = 'remove' then
    perform app.drop_from_game(p_id, v_now);
    delete from app.players where id = p_id;
  elsif p_action = 'new_key' then
    v_key := app.new_key();
    update app.players
       set recovery_hash = app.key_hash(v_key), recovery_failures = 0, recovery_locked_until = null
     where id = p_id;
    perform app.touch();
    return jsonb_build_object('ok', true, 'recovery_key', v_key);
  else
    perform app.fail('accion_invalida', 'Acción desconocida.');
  end if;
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- Para quien llega sin haber respondido: el admin lo agrega y le da su llave para entrar desde su teléfono.
create or replace function public.admin_add_player(p_session text, p_name text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_name text;
  v_key text;
  v_player app.players;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  v_name := btrim(regexp_replace(coalesce(p_name, ''), '\s+', ' ', 'g'));
  if v_name = '' or char_length(v_name) > 40 then
    perform app.fail('nombre_vacio', 'Escribe un nombre de hasta 40 caracteres.');
  end if;
  v_key := app.new_key();
  begin
    insert into app.players (name, name_key, recovery_hash) values (v_name, app.norm(v_name), app.key_hash(v_key))
    returning * into v_player;
  exception when unique_violation then
    perform app.fail('nombre_repetido', 'Ya hay alguien con ese nombre.');
  end;
  perform app.touch();
  return jsonb_build_object('ok', true, 'player', jsonb_build_object('id', v_player.id, 'name', v_player.name), 'recovery_key', v_key);
end
$fn$;

create or replace function public.admin_deal(p_session text, p_force boolean default false) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_game app.games;
  v_now timestamptz;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  if v_ev.phase not in ('lobby', 'jugando') then
    perform app.fail('fase_incorrecta', 'Abre la puerta (lobby) antes de repartir.');
  end if;
  if v_ev.paused_at is not null then
    perform app.fail('pausa', 'Quita la pausa primero.');
  end if;
  select * into v_game from app.games order by number desc limit 1;
  if found and v_game.ended_at is null then
    if not p_force then
      perform app.fail('partida_en_curso', 'Ya hay una partida en curso. Reiníciala para repartir otra vez.');
    end if;
    perform app.end_game(v_game, 'cancelada', v_now);
  end if;
  perform app.deal(v_now, false);
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

create or replace function public.admin_control(p_session text, p_action text) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_ev app.event;
  v_game app.games;
  v_round app.rounds;
  v_now timestamptz;
  v_shift interval;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  v_now := app.now();
  select * into v_ev from app.event where id = 1;
  select * into v_game from app.games order by number desc limit 1;

  if p_action = 'pause' then
    if v_ev.phase <> 'jugando' then
      perform app.fail('fase_incorrecta', 'Solo se puede pausar mientras se juega.');
    end if;
    update app.event set paused_at = coalesce(paused_at, v_now) where id = 1;

  elsif p_action = 'resume' then
    if v_ev.paused_at is not null then
      v_shift := v_now - v_ev.paused_at;
      update app.rounds set ends_at = ends_at + v_shift, state_since = state_since + v_shift
       where game_id = v_game.id and ends_at is not null;
      update app.games set next_deal_at = next_deal_at + v_shift where id = v_game.id and next_deal_at is not null;
      update app.event set paused_at = null where id = 1;
    end if;

  elsif p_action = 'force' then
    -- "Adelantar": vence el momento actual, sea discusión, votación, desempate o elección de víctima.
    if v_ev.paused_at is not null then
      perform app.fail('pausa', 'Quita la pausa primero.');
    end if;
    if v_ev.phase <> 'jugando' or v_game.id is null then
      perform app.fail('sin_partida', 'No hay una partida en curso.');
    end if;
    if v_game.ended_at is not null then
      perform app.deal(v_now, false);
    else
      select * into v_round from app.rounds where game_id = v_game.id order by number desc limit 1;
      if v_round.state in ('apertura') or (v_round.state = 'veredicto' and v_round.correct is false) then
        perform app.auto_kill(v_round, v_now);
      elsif v_round.state = 'discusion' then
        perform app.open_vote(v_round, v_now);
      elsif v_round.state in ('votacion', 'desempate') then
        perform app.close_vote(v_round, v_now);
      end if;
    end if;

  elsif p_action = 'end_night' then
    if v_game.id is not null and v_game.ended_at is null then
      perform app.end_game(v_game, 'cancelada', v_now);
    end if;
    update app.event set phase = 'fin', paused_at = null where id = 1;
    perform app.enqueue_push(array(select id from app.players), 'Se acabó la noche', 'Gracias por venir. Mira quién bebió más.', 'fin');

  elsif p_action = 'reopen' then
    if v_ev.phase = 'fin' then
      update app.event set phase = 'lobby' where id = 1;
    end if;

  else
    perform app.fail('accion_invalida', 'Acción desconocida.');
  end if;

  perform app.advance();
  perform app.touch();
  return jsonb_build_object('ok', true);
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Ensayo: bots, reloj adelantable, reinicio y vista de depuración.
-- ---------------------------------------------------------------------------------------------------
create or replace function public.admin_rehearsal(p_session text, p_action text, p_value int default null, p_player uuid default null) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  c_names constant text[] := array['Ximena', 'Renata', 'Camila', 'Valeria', 'Regina', 'Fernanda', 'Daniela', 'Paulina', 'Andrea',
    'Mariana', 'Luciana', 'Jimena', 'Natalia', 'Romina', 'Ivanna', 'Ámbar', 'Emiliano', 'Santiago', 'Mateo', 'Leonardo',
    'Sebastián', 'Diego', 'Rodrigo', 'Adrián', 'Bruno', 'Gael', 'Íker', 'Ulises', 'Dante', 'Lorenzo'];
  c_secrets constant text[] := array[
    'Lloró viendo el final de un comercial de seguros.',
    'Finge que entiende de vino. No entiende de vino.',
    'Se metió a una fiesta ajena por la comida y se quedó hasta el final.',
    'Escucha los audios al doble de velocidad para no sentir culpa.',
    'Lleva desde 2023 con 47 pestañas abiertas.',
    'Se sabe todos los diálogos de Gossip Girl y no lo admite.',
    'Le dio like a una foto de hace cuatro años y lo quitó a los dos segundos.',
    'Dice "ya voy saliendo" mientras sigue en la regadera.',
    'Ha fingido tener otra llamada para huir de una plática.',
    'Nunca ha visto la película que dice que es su favorita.',
    'Tiene una playlist para llorar con un nombre muy dramático en inglés.',
    'Se echó una siesta "de cinco minutos" en una boda y se perdió el brindis.',
    'Se aprendió la coreografía de moda solo para no bailarla nunca.',
    'Tiene silenciado un grupo de WhatsApp desde 2021, pero lee todo.',
    'Dijo "yo invito" sabiendo que no traía cartera.',
    'Nunca devolvió un suéter prestado. Ya es suyo.',
    'Practica frente al espejo cómo responder "¿y tú a qué te dedicas?".',
    'Compró un libro por la portada. Lleva tres años en la primera página.',
    'Fingió estar dormido para no ayudar en una mudanza.',
    'Contestó "no me llegó" a un mensaje que sí le llegó.',
    'Cree que es puntual. No es puntual.',
    'Opina de Succession sin haberla terminado.',
    'Grabó una historia de cumpleaños para alguien y nunca la publicó.',
    'Le tiene miedo a los pavos reales.'];
  v_ev app.event;
  v_now timestamptz;
  v_i int;
  v_name text;
  v_bot app.players;
  v_about text;
  v_added int := 0;
  v_result jsonb;
  v_token text;
begin
  perform app.lock();
  perform app.require_admin(p_session);
  select * into v_ev from app.event where id = 1;
  if not v_ev.rehearsal then
    perform app.fail('no_ensayo', 'Activa el modo ensayo primero.');
  end if;
  v_now := app.now();

  if p_action = 'bots' then
    for v_i in 1..greatest(1, least(coalesce(p_value, 12), 40)) loop
      select n into v_name from unnest(c_names) n
       where not exists (select 1 from app.players where name_key = app.norm(n))
       order by random() limit 1;
      if v_name is null then
        v_name := 'Bot ' || (select count(*) + 1 from app.players where is_bot);
      end if;
      insert into app.players (name, name_key, checked_in, is_bot) values (v_name, app.norm(v_name), true, true)
      returning * into v_bot;
      select name into v_about from app.players where id <> v_bot.id order by random() limit 1;
      if v_about is not null then
        insert into app.secrets (author_id, about_name, text, status)
        values (v_bot.id, v_about, c_secrets[1 + floor(random() * cardinality(c_secrets))::int], 'aprobado');
      end if;
      v_added := v_added + 1;
    end loop;
    v_result := jsonb_build_object('ok', true, 'added', v_added);

  elsif p_action = 'advance' then
    update app.event
       set clock_offset = clock_offset + make_interval(secs => greatest(0, least(coalesce(p_value, 60), 86400)))
     where id = 1;
    perform app.advance();
    v_result := jsonb_build_object('ok', true);

  elsif p_action = 'reset' then
    delete from app.games;
    update app.secrets set status = 'aprobado', revealed_at = null where status = 'revelado';
    delete from app.players where is_bot;
    delete from app.push_queue where sent_at is null;
    update app.event
       set phase = case when phase in ('jugando', 'fin') then 'lobby' else phase end,
           paused_at = null, clock_offset = interval '0'
     where id = 1;
    v_result := jsonb_build_object('ok', true);

  elsif p_action = 'impersonate' then
    -- Un token nuevo para jugar como esa persona (el simulador lo usa para mostrar su teléfono).
    v_token := translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_');
    update app.players set token_hash = app.hash(v_token) where id = p_player;
    if not found then
      perform app.fail('no_existe', 'Ese invitado ya no existe.');
    end if;
    return jsonb_build_object('ok', true, 'token', v_token);

  elsif p_action = 'god' then
    -- Solo para depurar en ensayo: roles y votos de la ronda actual.
    select jsonb_build_object(
      'roles', (select coalesce(jsonb_agg(jsonb_build_object('name', p.name, 'role', r.role, 'alive', r.alive) order by p.name), '[]'::jsonb)
                  from app.roles r join app.players p on p.id = r.player_id
                 where r.game_id = (select id from app.games order by number desc limit 1)),
      'votes', (select coalesce(jsonb_agg(jsonb_build_object('voter', pv.name, 'target', pt.name, 'stage', v.stage) order by pv.name), '[]'::jsonb)
                  from app.votes v join app.players pv on pv.id = v.voter_id join app.players pt on pt.id = v.target_id
                 where v.round_id = (select r.id from app.rounds r where r.game_id = (select id from app.games order by number desc limit 1)
                                      order by r.number desc limit 1))
    ) into v_result;
    return v_result;

  else
    perform app.fail('accion_invalida', 'Acción desconocida.');
  end if;

  perform app.touch();
  return v_result;
end
$fn$;

-- ---------------------------------------------------------------------------------------------------
-- Permisos
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
       and p.proname in ('admin_login', 'admin_logout', 'admin_set_pin', 'admin_state', 'admin_config', 'admin_phase', 'admin_secret',
                         'admin_approve_all', 'admin_player', 'admin_add_player', 'admin_deal', 'admin_control', 'admin_rehearsal')
  loop
    execute format('revoke all on function %s from public', r.sig);
    foreach v_role in array array['anon', 'authenticated'] loop
      if exists (select 1 from pg_roles where rolname = v_role) then
        execute format('grant execute on function %s to %I', r.sig, v_role);
      end if;
    end loop;
  end loop;
end $$;

-- ================================================================================
-- 20261001000600_push_cron.sql
-- ================================================================================

-- Mariela · 29 — notificaciones push y reloj del servidor.
--
-- El motor mete los avisos en `app.push_queue`; la Edge Function `enviar-push` los manda con Web Push
-- (VAPID). El reloj (`pg_cron`) llama a `app.advance_if_due()` cada pocos segundos. Si pg_cron o pg_net
-- no están disponibles el juego sigue funcionando: los clientes también empujan el reloj al consultar.

set check_function_bodies = off;

-- Solo la Edge Function (service_role) puede vaciar la cola.
create or replace function public.push_pending(p_limit int default 50) returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
begin
  -- Un aviso de hace diez minutos ya no le sirve a nadie.
  update app.push_queue set sent_at = now(), last_error = 'vencida'
   where sent_at is null and created_at < now() - interval '10 minutes';
  return (
    select coalesce(jsonb_agg(jsonb_build_object('id', q.id, 'title', q.title, 'body', q.body, 'tag', q.tag,
                                                  'subscription', p.push_subscription) order by q.id), '[]'::jsonb)
      from (select * from app.push_queue where sent_at is null and attempts < 3 order by id
             limit least(greatest(coalesce(p_limit, 50), 1), 200)) q
      join app.players p on p.id = q.player_id
     where p.push_subscription is not null
  );
end
$fn$;

-- p_failed: [{ "id": 12, "error": "410", "gone": true }]. `gone` borra la suscripción muerta.
create or replace function public.push_report(p_sent bigint[], p_failed jsonb default '[]') returns jsonb
language plpgsql volatile security definer set search_path = pg_temp as
$fn$
declare
  v_item jsonb;
begin
  update app.push_queue set sent_at = now() where id = any (coalesce(p_sent, '{}'));
  for v_item in select * from jsonb_array_elements(coalesce(p_failed, '[]'::jsonb)) loop
    update app.push_queue
       set attempts = attempts + 1, last_error = left(coalesce(v_item->>'error', ''), 200),
           sent_at = case when coalesce((v_item->>'gone')::boolean, false) then now() end
     where id = (v_item->>'id')::bigint;
    if coalesce((v_item->>'gone')::boolean, false) then
      update app.players set push_subscription = null
       where id = (select player_id from app.push_queue where id = (v_item->>'id')::bigint);
    end if;
  end loop;
  return jsonb_build_object('ok', true);
end
$fn$;

do $$
declare
  r record;
  v_role text;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public' and p.proname in ('push_pending', 'push_report')
  loop
    execute format('revoke all on function %s from public', r.sig);
    foreach v_role in array array['anon', 'authenticated'] loop
      if exists (select 1 from pg_roles where rolname = v_role) then
        execute format('revoke all on function %s from %I', r.sig, v_role);
      end if;
    end loop;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
      execute format('grant execute on function %s to service_role', r.sig);
    end if;
  end loop;
end $$;

-- Configuración desde el SQL Editor:  select app.configure_push('https://<ref>.supabase.co/functions/v1/enviar-push', '<secreto>');
create or replace function app.configure_push(p_url text, p_secret text) returns void
language sql set search_path = pg_temp as
$fn$
  insert into app.settings (key, value) values ('push_url', p_url), ('push_secret', p_secret)
  on conflict (key) do update set value = excluded.value
$fn$;

-- Despierta a la Edge Function cuando hay avisos pendientes (pg_net hace la llamada en segundo plano).
create or replace function app.dispatch_push() returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_url text;
  v_secret text;
begin
  if not exists (select 1 from app.push_queue where sent_at is null and attempts < 3 and created_at > now() - interval '10 minutes') then
    return;
  end if;
  select value into v_url from app.settings where key = 'push_url';
  select value into v_secret from app.settings where key = 'push_secret';
  if v_url is null or v_secret is null then
    return;
  end if;
  if to_regprocedure('net.http_post(text,jsonb,jsonb,jsonb,integer)') is null then
    return;
  end if;
  execute 'select net.http_post(url := $1, body := $2, headers := $3)'
    using v_url, '{}'::jsonb, jsonb_build_object('content-type', 'application/json', 'x-push-secret', v_secret);
end
$fn$;

-- El reloj del servidor. Todo esto es opcional: si falla, se avisa y el juego sigue.
do $$
begin
  if not exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    raise notice 'pg_cron no está disponible: el juego avanza cuando los clientes consultan su estado.';
    return;
  end if;
  begin
    create extension if not exists pg_cron;
  exception when others then
    raise notice 'No pude activar pg_cron (%). Actívalo en Database → Extensions y vuelve a correr esta migración.', sqlerrm;
    return;
  end;
  perform cron.unschedule(jobid) from cron.job where jobname in ('mariela-advance', 'mariela-push');
  begin
    perform cron.schedule('mariela-advance', '5 seconds', 'select app.advance_if_due()');
    perform cron.schedule('mariela-push', '10 seconds', 'select app.dispatch_push()');
  exception when others then
    -- pg_cron viejo: sin intervalos de segundos, el mínimo es un minuto.
    perform cron.schedule('mariela-advance', '* * * * *', 'select app.advance_if_due()');
    perform cron.schedule('mariela-push', '* * * * *', 'select app.dispatch_push()');
  end;
end $$;

-- ================================================================================
-- 20261001000700_limpieza.sql
-- ================================================================================

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

-- ================================================================================
-- Listo. Ahora:  select app.set_admin_pin('tu-pin-de-al-menos-6');
-- ================================================================================
