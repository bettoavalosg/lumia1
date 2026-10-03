import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Backend } from './backend'
import { esErrorDeRed, esErrorJuego, ErrorJuego } from './errores'

/** Lo que cualquier estado del servidor trae: su hora (para sincronizar el reloj) y su versión. */
interface ConHora {
  now: string
  version: number
}

export interface ContextoServidor<E extends ConHora = ConHora> {
  backend: Backend
  /** El último estado recibido, o el inicial (si lo hay) mientras llega el primero; null si no hay ninguno. */
  estado: E | null
  /** ¿Ya llegó al menos un estado real del servidor? */
  cargado: boolean
  /** El último error de red o del servidor al consultar; se limpia solo al recuperarse. */
  error: ErrorJuego | null
  /** ¿El canal en vivo (Realtime) está sano? Si no, se consulta más seguido. */
  enVivo: boolean
  /** Llama a una función del servidor y luego actualiza el estado. Lanza ErrorJuego si el servidor la rechaza. */
  llamar<T = unknown>(nombre: string, args?: Record<string, unknown>): Promise<T>
  refrescar(): Promise<void>
  /** La hora del servidor en milisegundos, corregida por la diferencia con este reloj. */
  ahora(): number
}

const Contexto = createContext<ContextoServidor | null>(null)

interface Props<E extends ConHora> {
  backend: Backend
  /** Cómo se pide el estado: player → get_state, tv → tv_state, admin → admin_state. */
  cargar: (backend: Backend) => Promise<E>
  /** El próximo vencimiento del juego (ISO). Al llegar, se le pide al servidor que avance y se refresca. */
  plazo?: (estado: E) => string | null
  /** Con qué pintar mientras llega el primer estado (la invitación no espera al servidor). */
  inicial?: E
  children: ReactNode
}

export function ServidorProvider<E extends ConHora>({ backend, cargar, plazo, inicial, children }: Props<E>) {
  const [estado, setEstado] = useState<E | null>(inicial ?? null)
  const [cargado, setCargado] = useState(false)
  const [error, setError] = useState<ErrorJuego | null>(null)
  const [enVivo, setEnVivo] = useState(false)
  const desfase = useRef(0)
  const enVuelo = useRef<Promise<void> | null>(null)
  const firmaAnterior = useRef('')
  const cargarRef = useRef(cargar)
  const despertar = useRef<(() => void) | null>(null)
  const pendiente = useRef(false)
  const hayError = useRef(false)

  useEffect(() => {
    cargarRef.current = cargar
  })

  const refrescar = useCallback((): Promise<void> => {
    if (enVuelo.current) return enVuelo.current
    const tarea = (async () => {
      const antes = Date.now()
      const t0 = performance.now()
      try {
        const nuevo = await cargarRef.current(backend)
        const viaje = performance.now() - t0
        // El servidor selló su hora a mitad del viaje. Con un viaje muy largo no se confía en la medición.
        if (viaje < 3000) desfase.current = Date.parse(nuevo.now) - (antes + viaje / 2)
        const firma = JSON.stringify({ ...nuevo, now: 0 })
        if (firma !== firmaAnterior.current) {
          firmaAnterior.current = firma
          setEstado(nuevo)
        }
        setCargado(true)
        hayError.current = false
        setError(null)
      } catch (e) {
        hayError.current = true
        setError(esErrorJuego(e) ? e : new ErrorJuego('error', 'No se pudo actualizar.'))
      } finally {
        enVuelo.current = null
      }
    })()
    enVuelo.current = tarea
    return tarea
  }, [backend])

  // Consulta al arrancar y luego cada tanto; el aviso de Realtime, volver a la pestaña o recuperar la red la adelantan.
  useEffect(() => {
    let vivo = true
    let conectado = false
    const alCambiar = () => {
      pendiente.current = true
      despertar.current?.()
    }
    const bajar = backend.suscribir(alCambiar, v => {
      conectado = v
      setEnVivo(v)
    })
    const dormir = (ms: number) =>
      new Promise<void>(resolver => {
        if (pendiente.current) {
          pendiente.current = false
          resolver()
          return
        }
        const id = setTimeout(resolver, ms)
        despertar.current = () => {
          clearTimeout(id)
          pendiente.current = false
          resolver()
        }
      })
    void (async () => {
      while (vivo) {
        await refrescar()
        await dormir(hayError.current ? 3000 : conectado ? 10_000 : 3000)
      }
    })()
    const volver = () => {
      if (!document.hidden) alCambiar()
    }
    document.addEventListener('visibilitychange', volver)
    window.addEventListener('online', volver)
    window.addEventListener('focus', volver)
    return () => {
      vivo = false
      bajar()
      despertar.current?.()
      document.removeEventListener('visibilitychange', volver)
      window.removeEventListener('online', volver)
      window.removeEventListener('focus', volver)
    }
  }, [backend, refrescar])

  // El servidor es quien avanza el juego. Cuando vence un plazo, este cliente solo se lo recuerda (con un poco
  // de azar para que veinte teléfonos no lo hagan en el mismo instante) y vuelve a pedir el estado.
  const vencimiento = estado && plazo ? plazo(estado) : null
  useEffect(() => {
    if (!vencimiento) return
    const falta = Date.parse(vencimiento) - (Date.now() + desfase.current)
    const id = setTimeout(
      () => {
        void backend.rpc('advance').catch(() => undefined).then(() => refrescar())
      },
      Math.max(0, falta) + 300 + Math.random() * 900,
    )
    return () => clearTimeout(id)
  }, [vencimiento, backend, refrescar])

  const llamar = useCallback(
    async <T,>(nombre: string, args?: Record<string, unknown>): Promise<T> => {
      const resultado = await backend.rpc<T>(nombre, args)
      await refrescar()
      return resultado
    },
    [backend, refrescar],
  )

  const ahora = useCallback(() => Date.now() + desfase.current, [])
  const valor = useMemo<ContextoServidor>(
    () => ({ backend, estado, cargado, error, enVivo, llamar, refrescar, ahora }) as ContextoServidor,
    [backend, estado, cargado, error, enVivo, llamar, refrescar, ahora],
  )
  return <Contexto value={valor}>{children}</Contexto>
}

export function useServidor<E extends ConHora = ConHora>(): ContextoServidor<E> {
  const c = useContext(Contexto)
  if (!c) throw new Error('useServidor necesita un <ServidorProvider>')
  return c as unknown as ContextoServidor<E>
}

export { esErrorDeRed }
