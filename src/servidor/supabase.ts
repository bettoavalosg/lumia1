import { RealtimeClient } from '@supabase/realtime-js'
import type { Backend } from './backend'
import { ErrorJuego } from './errores'

/** Supabase: las funciones de `public` por PostgREST y un canal de Realtime que solo avisa "algo cambió". */
export function crearSupabase(url: string, clave: string): Backend {
  const base = url.replace(/\/$/, '')
  const esJwt = clave.startsWith('eyJ')
  const oyentes = new Set<() => void>()
  const vigilantes = new Set<(enVivo: boolean) => void>()
  let cliente: RealtimeClient | null = null
  let enVivo = false

  const fijarVivo = (valor: boolean) => {
    if (valor === enVivo) return
    enVivo = valor
    vigilantes.forEach(f => f(valor))
  }

  const conectar = () => {
    if (cliente) return
    const socket = base.replace(/^http/, 'ws') + '/realtime/v1'
    cliente = new RealtimeClient(socket, { params: { apikey: clave } })
    // El aviso no lleva datos: quien lo recibe vuelve a pedir su estado, ya filtrado por el servidor.
    cliente
      .channel('noche', { config: { broadcast: { self: false }, private: false } })
      .on('broadcast', { event: 'cambio' }, () => oyentes.forEach(f => f()))
      .subscribe(estado => fijarVivo(estado === 'SUBSCRIBED'))
  }

  const desconectar = () => {
    if (!cliente) return
    void cliente.disconnect()
    cliente = null
    fijarVivo(false)
  }

  return {
    modo: 'supabase',

    async rpc<T>(nombre: string, args: Record<string, unknown> = {}): Promise<T> {
      const control = new AbortController()
      const plazo = setTimeout(() => control.abort(), 15_000)
      let respuesta: Response
      try {
        respuesta = await fetch(`${base}/rest/v1/rpc/${nombre}`, {
          method: 'POST',
          headers: {
            apikey: clave,
            // Las llaves nuevas (sb_publishable_…) van solo en `apikey`; las JWT clásicas también como Bearer.
            ...(esJwt ? { authorization: `Bearer ${clave}` } : {}),
            'content-type': 'application/json',
          },
          body: JSON.stringify(args),
          signal: control.signal,
        })
      } catch {
        throw new ErrorJuego('sin_red', 'No hay conexión con el servidor. Reintentando…')
      } finally {
        clearTimeout(plazo)
      }
      const texto = await respuesta.text()
      let cuerpo: unknown = null
      try {
        cuerpo = texto ? JSON.parse(texto) : null
      } catch {
        cuerpo = null
      }
      if (!respuesta.ok) {
        const e = cuerpo as { message?: string; hint?: string; code?: string } | null
        // Lo que ve quien configura el proyecto por primera vez: que el mensaje diga qué falta, no un número.
        if (respuesta.status === 404 && (e?.code === 'PGRST202' || e?.code === '42883')) {
          throw new ErrorJuego('sin_esquema', 'El servidor todavía no tiene el juego instalado. Pega supabase/setup.sql en el SQL Editor de Supabase y vuelve a intentar.')
        }
        if (respuesta.status === 401 || (respuesta.status === 403 && !e?.hint)) {
          throw new ErrorJuego('clave_invalida', 'Supabase no aceptó la clave pública. Revisa VITE_SUPABASE_ANON_KEY (la anon o publishable key, no la service_role).')
        }
        throw new ErrorJuego(e?.hint || `http_${respuesta.status}`, e?.message || `El servidor respondió ${respuesta.status}.`)
      }
      return cuerpo as T
    },

    suscribir(alCambiar, alEstado) {
      oyentes.add(alCambiar)
      if (alEstado) {
        vigilantes.add(alEstado)
        alEstado(enVivo)
      }
      conectar()
      return () => {
        oyentes.delete(alCambiar)
        if (alEstado) vigilantes.delete(alEstado)
        if (oyentes.size === 0) desconectar()
      }
    },
  }
}
