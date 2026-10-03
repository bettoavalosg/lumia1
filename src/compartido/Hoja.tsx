import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  abierta: boolean
  alCerrar: () => void
  titulo: string
  children: ReactNode
}

/**
 * Una hoja que sube desde abajo para confirmar algo que no tiene vuelta atrás.
 *
 * La capa es `position: fixed`, pero una capa fija se ancla al ancestro más cercano que tenga `transform`, `translate`, `filter`…
 * y no a la ventana: una pantalla que entra animada ya se queda con un `translate: 0px`, y con eso la hoja cerrada asomaba sobre la
 * barra de pestañas. Por eso no se dibuja donde se declara sino sobre la raíz de la app (`.juego`, que nunca se anima y conserva los
 * estilos de los botones de la noche), o sobre `body` si no hay ninguna.
 *
 * Como queda al final de la app, el título de lo que lleva dentro es un `h2` (válido después de cualquier encabezado): un `h3`
 * saltaría un nivel según el encabezado que le toque antes.
 */
export function Hoja({ abierta, alCerrar, titulo, children }: Props) {
  const ancla = useRef<HTMLSpanElement>(null)
  const [raiz, setRaiz] = useState<Element | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const previo = useRef<Element | null>(null)

  useLayoutEffect(() => {
    setRaiz(ancla.current?.closest('.juego') ?? document.body)
  }, [])

  useEffect(() => {
    if (!abierta || !raiz) return
    previo.current = document.activeElement
    ref.current?.focus()
    const tecla = (e: KeyboardEvent) => {
      if (e.key === 'Escape') alCerrar()
    }
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('keydown', tecla)
      if (previo.current instanceof HTMLElement) previo.current.focus({ preventScroll: true })
    }
  }, [abierta, alCerrar, raiz])

  return (
    <>
      <span ref={ancla} hidden />
      {raiz &&
        createPortal(
          <div className={`hoja-capa${abierta ? ' abierta' : ''}`} aria-hidden={!abierta} inert={!abierta}>
            <div className="hoja-fondo" onClick={alCerrar} />
            <div ref={ref} className="hoja" role="dialog" aria-modal="true" aria-label={titulo} tabIndex={-1}>
              <span className="hoja-asa" aria-hidden="true" />
              {children}
            </div>
          </div>,
          raiz,
        )}
    </>
  )
}
