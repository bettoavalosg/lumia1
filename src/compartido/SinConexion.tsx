import { useEffect, useState } from 'react'
import { esErrorDeRed } from '../servidor/errores'
import { useServidor } from '../servidor/Servidor'

/**
 * Se enciende cuando llevan un rato fallando las consultas por falta de red y se apaga sola al volver.
 * Un tropiezo suelto (una consulta perdida entre dos buenas) no se anuncia.
 */
export function SinConexion({ clase = 'j-conexion' }: { clase?: string }) {
  const { error } = useServidor()
  const caido = Boolean(error && esErrorDeRed(error))
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!caido) {
      setVisible(false)
      return
    }
    const id = setTimeout(() => setVisible(true), 2500)
    return () => clearTimeout(id)
  }, [caido])

  if (!visible) return null
  return (
    <p className={clase} role="status">
      Sin conexión. Reintentando…
    </p>
  )
}
