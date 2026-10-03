import { Cera } from './Sprite'

/** Pantalla de espera: el sello de cera respira mientras llega el estado. */
export function Cargando({ texto = 'Un momento…', sinRed = false }: { texto?: string; sinRed?: boolean }) {
  return (
    <div className="cargando" role="status">
      <Cera className="cargando-sello" />
      <p>{texto}</p>
      {sinRed && <p className="cargando-nota">Sin conexión. Reintentando…</p>}
    </div>
  )
}
