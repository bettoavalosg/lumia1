import { lazy, Suspense, useMemo } from 'react'
import { AvisosProvider } from './compartido/Avisos'
import { Cargando } from './compartido/Cargando'
import { Sprite } from './compartido/Sprite'
import { elegirBackend, perezoso } from './servidor/backend'
import { BackendContexto } from './servidor/BackendContexto'

const App = lazy(() => import('./App'))
const Tv = lazy(() => import('./tv/Tv'))
const Admin = lazy(() => import('./admin/Admin'))
const Simulador = lazy(() => import('./demo/Simulador'))

function rutaActual() {
  const p = location.pathname
  if (p.startsWith('/admin')) return Admin
  if (p.startsWith('/tv')) return Tv
  if (p.startsWith('/demo')) return Simulador
  return App
}

/** Elige el servidor (Supabase o el demo en el navegador) y monta la ruta sin esperar a que el servidor arranque. */
export function Raiz() {
  const backend = useMemo(() => perezoso(elegirBackend()), [])
  const Ruta = rutaActual()
  return (
    <>
      <Sprite />
      <BackendContexto value={backend}>
        <AvisosProvider>
          <Suspense fallback={<Cargando />}>
            <Ruta />
          </Suspense>
        </AvisosProvider>
      </BackendContexto>
    </>
  )
}
