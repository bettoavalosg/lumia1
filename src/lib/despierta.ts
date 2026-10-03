import { useEffect } from 'react'

/**
 * Mantiene la pantalla encendida mientras esta página esté a la vista (Screen Wake Lock). Una tele o una computadora conectada
 * a un proyector que se apaga a media votación arruina la noche. Si el navegador no lo soporta, no pasa nada.
 */
export function useMantenerDespierta(): void {
  useEffect(() => {
    let candado: WakeLockSentinel | null = null
    let vivo = true

    const pedir = async () => {
      if (!vivo || document.hidden || candado || !('wakeLock' in navigator)) return
      try {
        const nuevo = await navigator.wakeLock.request('screen')
        if (!vivo) {
          void nuevo.release()
          return
        }
        candado = nuevo
        // El sistema lo suelta solo (batería baja, pestaña oculta): se vuelve a pedir al regresar.
        nuevo.addEventListener('release', () => {
          if (candado === nuevo) candado = null
        })
      } catch {
        // Sin permiso o sin soporte: se sigue sin él.
      }
    }

    const alCambiarVisibilidad = () => void pedir()
    void pedir()
    document.addEventListener('visibilitychange', alCambiarVisibilidad)
    return () => {
      vivo = false
      document.removeEventListener('visibilitychange', alCambiarVisibilidad)
      void candado?.release().catch(() => undefined)
      candado = null
    }
  }, [])
}

/** Doble clic (o toque) para pasar a pantalla completa y salir; y el cursor se esconde tras unos segundos sin moverlo. */
export function usePantallaCompleta(): void {
  useEffect(() => {
    const raiz = document.documentElement
    let id: number | undefined
    const mostrar = () => {
      raiz.removeAttribute('data-cursor-quieto')
      clearTimeout(id)
      id = window.setTimeout(() => raiz.setAttribute('data-cursor-quieto', ''), 3000)
    }
    const alternar = () => {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined)
      else void raiz.requestFullscreen?.().catch(() => undefined)
    }
    mostrar()
    window.addEventListener('pointermove', mostrar)
    window.addEventListener('dblclick', alternar)
    return () => {
      clearTimeout(id)
      raiz.removeAttribute('data-cursor-quieto')
      window.removeEventListener('pointermove', mostrar)
      window.removeEventListener('dblclick', alternar)
    }
  }, [])
}
