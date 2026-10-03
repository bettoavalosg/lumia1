import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

type Tipo = 'info' | 'ok' | 'error'
interface Aviso {
  id: number
  texto: string
  tipo: Tipo
}

const Contexto = createContext<(texto: string, tipo?: Tipo) => void>(() => undefined)

/** Avisos breves, abajo, que no tapan lo que se está haciendo. Un lector de pantalla los anuncia. */
export function AvisosProvider({ children }: { children: ReactNode }) {
  const [lista, setLista] = useState<Aviso[]>([])
  const siguiente = useRef(1)
  const temporizadores = useRef(new Map<number, number>())

  const avisar = useCallback((texto: string, tipo: Tipo = 'info') => {
    const id = siguiente.current++
    setLista(l => [...l.slice(-2), { id, texto, tipo }])
    temporizadores.current.set(
      id,
      window.setTimeout(() => setLista(l => l.filter(a => a.id !== id)), tipo === 'error' ? 6000 : 4000),
    )
  }, [])

  useEffect(() => {
    const t = temporizadores.current
    return () => t.forEach(clearTimeout)
  }, [])

  const valor = useMemo(() => avisar, [avisar])
  return (
    <Contexto value={valor}>
      {children}
      <div className="avisos" role="status" aria-live="polite">
        {lista.map(a => (
          <p key={a.id} className={`aviso-toast ${a.tipo}`}>
            {a.texto}
          </p>
        ))}
      </div>
    </Contexto>
  )
}

export const useAvisos = () => useContext(Contexto)
