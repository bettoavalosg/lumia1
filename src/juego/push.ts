import type { Backend } from '../servidor/backend'

const VAPID = (import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined)?.trim()

/** ¿Este build y este navegador pueden recibir notificaciones? Sin llave VAPID la opción no se ofrece. */
export const pushDisponible = () => Boolean(VAPID) && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

export const esStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true

export const esIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)

function llaveAplicacion(base64: string): Uint8Array<ArrayBuffer> {
  const relleno = '='.repeat((4 - (base64.length % 4)) % 4)
  const crudo = atob((base64 + relleno).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(crudo, c => c.charCodeAt(0))
}

export type ResultadoPush = 'ok' | 'denegado' | 'no_disponible'

/** Pide permiso, se suscribe al servicio de push del navegador y le pasa la suscripción al servidor. */
export async function activarPush(backend: Backend, token: string): Promise<ResultadoPush> {
  if (!pushDisponible() || !VAPID) return 'no_disponible'
  const permiso = await Notification.requestPermission()
  if (permiso !== 'granted') return 'denegado'
  const registro = await navigator.serviceWorker.ready
  const suscripcion =
    (await registro.pushManager.getSubscription()) ??
    (await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: llaveAplicacion(VAPID) }))
  await backend.rpc('save_push', { p_token: token, p_subscription: suscripcion.toJSON() })
  return 'ok'
}

export async function desactivarPush(backend: Backend, token: string): Promise<void> {
  try {
    const registro = await navigator.serviceWorker.ready
    await (await registro.pushManager.getSubscription())?.unsubscribe()
  } catch {
    // sin suscripción local
  }
  await backend.rpc('save_push', { p_token: token, p_subscription: null })
}
