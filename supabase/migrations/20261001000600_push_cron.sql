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
