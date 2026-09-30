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
  update app.event set phase = p_phase, paused_at = null where id = 1;
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
create or replace function public.admin_rehearsal(p_session text, p_action text, p_value int default null) returns jsonb
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
