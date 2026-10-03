import { createContext, useContext } from 'react'
import type { Backend } from './backend'

export const BackendContexto = createContext<Backend | null>(null)

export function useBackend(): Backend {
  const b = useContext(BackendContexto)
  if (!b) throw new Error('useBackend necesita estar dentro de <Raiz>')
  return b
}
