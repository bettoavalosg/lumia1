import { useBackend } from '../servidor/BackendContexto'

/** En el modo demo, una pastilla discreta lleva al simulador. No aparece dentro del propio simulador. */
export function PastillaDemo() {
  const backend = useBackend()
  if (backend.modo !== 'demo' || window.parent !== window) return null
  return (
    <a className="pastilla-demo" href="/demo">
      Modo demo · abrir el simulador
    </a>
  )
}
