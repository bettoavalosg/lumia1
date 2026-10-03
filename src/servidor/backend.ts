/** Cómo habla la app con el servidor. Hay tres: Supabase (la noche real), el demo en el navegador y un puente hacia el demo. */
export interface Backend {
  readonly modo: 'supabase' | 'demo'
  rpc<T = unknown>(nombre: string, args?: Record<string, unknown>): Promise<T>
  /** Avisa cuando el servidor cambió (Realtime). `alEstado(true)` indica que el canal en vivo está sano. */
  suscribir(alCambiar: () => void, alEstado?: (enVivo: boolean) => void): () => void
}

declare global {
  interface Window {
    /** El demo expone su backend para que los iframes del simulador lo compartan. */
    __marielaDemo?: DemoExpuesto
  }
}

export interface DemoExpuesto extends Backend {
  sql(consulta: string, params?: unknown[]): Promise<Record<string, unknown>[]>
  reiniciar(): Promise<void>
}

const URL_SUPABASE = (import.meta.env.VITE_SUPABASE_URL as string | undefined)?.trim()
const CLAVE_SUPABASE = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined)?.trim()

/** ¿Este build está conectado a un Supabase de verdad? */
export const haySupabase = Boolean(URL_SUPABASE && CLAVE_SUPABASE)

/** Qué servidor va a ser, sin esperar a que arranque: el modo se decide por la ruta y por la configuración. */
export const modoPrevisto = (): Backend['modo'] => (location.pathname.startsWith('/demo') || !haySupabase ? 'demo' : 'supabase')

/**
 * Un servidor que todavía está arrancando (el demo tarda unos segundos la primera vez; Supabase carga un chunk).
 * La app se pinta de inmediato y cada llamada espera a que el real esté listo.
 */
export function perezoso(listo: Promise<Backend>): Backend {
  let real: Backend | null = null
  listo.then(
    b => {
      real = b
    },
    () => undefined,
  )
  return {
    get modo() {
      return real?.modo ?? modoPrevisto()
    },
    rpc: async (nombre, args) => (await listo).rpc(nombre, args),
    suscribir(alCambiar, alEstado) {
      let baja: () => void = () => undefined
      let cancelado = false
      listo.then(
        b => {
          if (!cancelado) baja = b.suscribir(alCambiar, alEstado)
        },
        () => undefined,
      )
      return () => {
        cancelado = true
        baja()
      }
    },
  }
}

/**
 * Elige el servidor:
 *  · dentro del simulador (iframe), el demo de la ventana madre;
 *  · en /demo, o si no hay Supabase configurado, un Postgres completo en el navegador (PGlite);
 *  · si no, Supabase.
 */
export async function elegirBackend(): Promise<Backend> {
  let madre: DemoExpuesto | undefined
  try {
    madre = window.parent !== window ? window.parent.__marielaDemo : undefined
  } catch {
    madre = undefined
  }
  if (madre) return madre
  if (location.pathname.startsWith('/demo') || !haySupabase) {
    const { crearDemo } = await import('./demo')
    return crearDemo()
  }
  const { crearSupabase } = await import('./supabase')
  return crearSupabase(URL_SUPABASE!, CLAVE_SUPABASE!)
}
