// Vacía la cola de notificaciones del juego y las manda con Web Push (VAPID).
//
// La llama Postgres (pg_cron → app.dispatch_push → pg_net) cada pocos segundos, con el secreto compartido en
// `x-push-secret`. No se expone al público: sin ese secreto responde 403. Nunca toca las tablas directamente;
// pide y reporta por las funciones `push_pending` y `push_report`, que solo acepta la service role.
//
// Secretos (supabase secrets set …):  PUSH_SECRET, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT (mailto:…)
import { createClient } from 'npm:@supabase/supabase-js@2'
import webpush from 'npm:web-push@3.6.7'

interface Pendiente {
  id: number
  title: string
  body: string
  tag: string | null
  subscription: webpush.PushSubscription
}

const env = (nombre: string) => Deno.env.get(nombre) ?? ''

Deno.serve(async req => {
  if (req.method !== 'POST') return new Response('método no permitido', { status: 405 })
  const secreto = env('PUSH_SECRET')
  if (!secreto || req.headers.get('x-push-secret') !== secreto) return new Response('sin permiso', { status: 403 })
  if (!env('VAPID_PUBLIC_KEY') || !env('VAPID_PRIVATE_KEY')) return new Response('faltan las llaves VAPID', { status: 500 })

  webpush.setVapidDetails(env('VAPID_SUBJECT') || 'mailto:admin@example.com', env('VAPID_PUBLIC_KEY'), env('VAPID_PRIVATE_KEY'))
  const supabase = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'), { auth: { persistSession: false } })

  const { data, error } = await supabase.rpc('push_pending', { p_limit: 100 })
  if (error) return Response.json({ error: error.message }, { status: 500 })

  const cola = (data ?? []) as Pendiente[]
  const enviados: number[] = []
  const fallidos: { id: number; error: string; gone: boolean }[] = []

  await Promise.all(
    cola.map(async n => {
      try {
        await webpush.sendNotification(n.subscription, JSON.stringify({ title: n.title, body: n.body, tag: n.tag ?? 'mariela', url: '/' }), {
          TTL: 120,
          urgency: 'high',
        })
        enviados.push(n.id)
      } catch (e) {
        const estado = (e as { statusCode?: number }).statusCode
        // 404 y 410: el navegador dio de baja esa suscripción; se borra para no insistir.
        fallidos.push({ id: n.id, error: String(estado ?? (e as Error).message), gone: estado === 404 || estado === 410 })
      }
    }),
  )

  if (cola.length) await supabase.rpc('push_report', { p_sent: enviados, p_failed: fallidos })
  return Response.json({ enviados: enviados.length, fallidos: fallidos.length })
})
