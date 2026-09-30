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
