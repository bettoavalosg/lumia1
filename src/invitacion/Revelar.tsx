import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'

type Contexto = { registrar: (el: Element, orden: number) => () => void; maximo: number }

const RevelarContexto = createContext<Contexto | null>(null)

/**
 * Revela las piezas de la suite cuando llegan a la vista, en el orden de la página.
 * Si el scroll salta (un gesto rápido, un enlace), las piezas anteriores nunca "entran":
 * se revelan junto con la que sí entró.
 */
export function Revelador({ activo, children }: { activo: boolean; children: ReactNode }) {
  const [maximo, setMaximo] = useState(-1)
  const piezas = useRef(new Map<Element, number>())
  const observador = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    if (!activo) return
    if (!('IntersectionObserver' in window)) {
      setMaximo(Number.POSITIVE_INFINITY)
      return
    }
    const io = new IntersectionObserver(
      entradas => {
        const vistas = entradas.filter(e => e.isIntersecting).map(e => piezas.current.get(e.target) ?? -1)
        if (vistas.length) setMaximo(m => Math.max(m, ...vistas))
      },
      { rootMargin: '0px 0px -2% 0px', threshold: 0.05 },
    )
    piezas.current.forEach((_, el) => io.observe(el))
    observador.current = io
    return () => {
      io.disconnect()
      observador.current = null
    }
  }, [activo])

  const registrar = useCallback((el: Element, orden: number) => {
    piezas.current.set(el, orden)
    observador.current?.observe(el)
    return () => {
      piezas.current.delete(el)
      observador.current?.unobserve(el)
    }
  }, [])

  const valor = useMemo(() => ({ registrar, maximo }), [registrar, maximo])
  return <RevelarContexto value={valor}>{children}</RevelarContexto>
}

/** Ref para la pieza y si ya fue vista. `orden` sigue el orden de la página. */
export function useRevelado<T extends Element>(orden: number): [RefObject<T | null>, boolean] {
  const contexto = useContext(RevelarContexto)
  if (!contexto) throw new Error('useRevelado necesita un <Revelador>')
  const ref = useRef<T>(null)
  const { registrar, maximo } = contexto
  useEffect(() => (ref.current ? registrar(ref.current, orden) : undefined), [registrar, orden])
  return [ref, orden <= maximo]
}
