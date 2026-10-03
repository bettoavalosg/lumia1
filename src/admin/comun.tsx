import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Hoja } from '../compartido/Hoja'
import { mensajeDe } from '../servidor/errores'
import { useServidor } from '../servidor/Servidor'
import type { EstadoAdmin } from '../servidor/tipos'

export const SesionContexto = createContext<string>('')

/** El estado del admin y una forma de actuar que avisa si algo sale mal. */
export function useAdmin() {
  const contexto = useServidor<EstadoAdmin>()
  const sesion = useContext(SesionContexto)
  const avisar = useAvisos()
  const { llamar } = contexto

  const actuar = useCallback(
    async <T = { ok: boolean }>(fn: string, args: Record<string, unknown> = {}, exito?: string): Promise<T | null> => {
      try {
        const r = await llamar<T>(fn, { p_session: sesion, ...args })
        if (exito) avisar(exito, 'ok')
        return r
      } catch (e) {
        avisar(mensajeDe(e), 'error')
        return null
      }
    },
    [llamar, sesion, avisar],
  )
  return { ...contexto, a: contexto.estado as EstadoAdmin, actuar, sesion }
}

export async function copiar(texto: string, avisar: (t: string, tipo?: 'info' | 'ok' | 'error') => void, etiqueta = 'Copiado') {
  try {
    await navigator.clipboard.writeText(texto)
    avisar(etiqueta, 'ok')
  } catch {
    avisar('No pude copiar. Selecciónalo y cópialo a mano.', 'error')
  }
}

interface ConfirmarProps {
  abierta: boolean
  titulo: string
  texto: string
  boton: string
  peligro?: boolean
  alConfirmar: () => void | Promise<void>
  alCerrar: () => void
}

/** Una pregunta antes de algo que no se deshace. */
export function Confirmar({ abierta, titulo, texto, boton, peligro = false, alConfirmar, alCerrar }: ConfirmarProps) {
  const [trabajando, setTrabajando] = useState(false)
  return (
    <Hoja abierta={abierta} alCerrar={alCerrar} titulo={titulo}>
      <p className={`j-etiqueta${peligro ? ' rojo' : ''}`}>{peligro ? 'Sin vuelta atrás' : 'Confirmar'}</p>
      <h2 className="j-titulo chico">{titulo}</h2>
      <p className="j-texto">{texto}</p>
      <div className="hoja-botones">
        <button
          type="button"
          className={`primario${peligro ? ' rojo' : ''}`}
          disabled={trabajando}
          onClick={async () => {
            setTrabajando(true)
            await alConfirmar()
            setTrabajando(false)
            alCerrar()
          }}
        >
          {trabajando ? 'Un momento…' : boton}
        </button>
        <button type="button" className="secundario" onClick={alCerrar}>
          Cancelar
        </button>
      </div>
    </Hoja>
  )
}

export function Seccion({ titulo, nota, children }: { titulo: string; nota?: string; children: ReactNode }) {
  return (
    <section className="ad-seccion">
      <h2 className="ad-titulo">{titulo}</h2>
      {nota && <p className="ad-nota">{nota}</p>}
      {children}
    </section>
  )
}

/** Convierte un instante ISO al valor que espera <input type="datetime-local"> (hora del dispositivo). */
export function aLocal(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const dos = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}T${dos(d.getHours())}:${dos(d.getMinutes())}`
}

export const aIso = (local: string): string | null => (local ? new Date(local).toISOString() : null)
