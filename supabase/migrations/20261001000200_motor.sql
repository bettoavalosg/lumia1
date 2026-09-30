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

-- Barato: solo entra al candado si hay algo vencido. Lo llaman los clientes al consultar su estado.
create or replace function app.advance_if_due() returns void
language plpgsql set search_path = pg_temp as
$fn$
declare
  v_now timestamptz := app.now();
  v_due boolean;
begin
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
