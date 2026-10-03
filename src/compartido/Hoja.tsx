import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  abierta: boolean
  alCerrar: () => void
  titulo: string
  children: ReactNode
}

/** Una hoja que sube desde abajo para confirmar algo que no tiene vuelta atrás. */
export function Hoja({ abierta, alCerrar, titulo, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const previo = useRef<Element | null>(null)

  useEffect(() => {
    if (!abierta) return
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
  }, [abierta, alCerrar])

  return (
    <div className={`hoja-capa${abierta ? ' abierta' : ''}`} aria-hidden={!abierta} inert={!abierta}>
      <div className="hoja-fondo" onClick={alCerrar} />
      <div ref={ref} className="hoja" role="dialog" aria-modal="true" aria-label={titulo} tabIndex={-1}>
        <span className="hoja-asa" aria-hidden="true" />
        {children}
      </div>
    </div>
  )
}
