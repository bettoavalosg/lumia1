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
