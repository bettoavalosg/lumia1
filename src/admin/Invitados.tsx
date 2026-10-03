import { useMemo, useState, type FormEvent } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Hoja } from '../compartido/Hoja'
import type { InvitadoAdmin } from '../servidor/tipos'
import { Confirmar, copiar, Seccion, useAdmin } from './comun'

const enlaceDeLlave = (nombre: string, llave: string) => `${location.origin}/?nombre=${encodeURIComponent(nombre)}&llave=${encodeURIComponent(llave)}`

export function Invitados() {
  const { a, actuar } = useAdmin()
  const avisar = useAvisos()
  const [busca, setBusca] = useState('')
  const [nuevo, setNuevo] = useState('')
  const [llave, setLlave] = useState<{ nombre: string; llave: string } | null>(null)
  const [detalle, setDetalle] = useState<InvitadoAdmin | null>(null)
  const [quitar, setQuitar] = useState<InvitadoAdmin | null>(null)

  const lista = useMemo(() => {
    const q = busca.trim().toLowerCase()
    return a.players.filter(p => !q || p.name.toLowerCase().includes(q))
  }, [a.players, busca])
  const humanos = a.players.filter(p => !p.bot)
  const presentes = a.players.filter(p => p.checked_in).length

  const agregar = async (ev: FormEvent) => {
    ev.preventDefault()
    const nombre = nuevo.trim()
    if (!nombre) return
    const r = await actuar<{ recovery_key: string }>('admin_add_player', { p_name: nombre })
    if (r) {
      setLlave({ nombre, llave: r.recovery_key })
      setNuevo('')
    }
  }

  const nuevaLlave = async (p: InvitadoAdmin) => {
    const r = await actuar<{ recovery_key: string }>('admin_player', { p_id: p.id, p_action: 'new_key' })
    if (r) {
      setDetalle(null)
      setLlave({ nombre: p.name, llave: r.recovery_key })
    }
  }

  return (
    <>
      <Seccion titulo="Invitados" nota={`${presentes} presentes de ${a.players.length}${humanos.length !== a.players.length ? ` (${a.players.length - humanos.length} bots)` : ''}.`}>
        <div className="campo">
          <label htmlFor="busca">Buscar</label>
          <input id="busca" type="search" value={busca} onChange={ev => setBusca(ev.target.value)} autoComplete="off" />
        </div>
        <ul className="ad-invitados">
          {lista.map(p => (
            <li key={p.id} className="ad-invitado">
              <div className="ad-invitado-info">
                <b>{p.name}</b>
                <span className="ad-chips">
                  {p.bot && <i>bot</i>}
                  {!p.bot && !p.device && <i className="aviso">sin abrir la app</i>}
                  {p.push && <i>avisos</i>}
                  {p.in_game && <i className={p.alive ? '' : 'caido'}>{p.alive ? 'con vida' : 'sin vida'}</i>}
                </span>
              </div>
              <button
                type="button"
                className={`ad-interruptor${p.checked_in ? ' activo' : ''}`}
                aria-pressed={p.checked_in}
                onClick={() => void actuar('admin_player', { p_id: p.id, p_action: p.checked_in ? 'check_out' : 'check_in' })}
              >
                {p.checked_in ? 'Presente' : 'Ausente'}
              </button>
              <button type="button" className="ad-mas" aria-label={`Más acciones para ${p.name}`} onClick={() => setDetalle(p)}>
                ···
              </button>
            </li>
          ))}
          {lista.length === 0 && <li className="ad-vacio">Nadie coincide.</li>}
        </ul>
      </Seccion>

      <Seccion titulo="Agregar a alguien" nota="Para quien llegue sin haber respondido. Le das su llave y entra desde su teléfono.">
        <form className="ad-form-linea" onSubmit={agregar}>
          <div className="campo">
            <label htmlFor="nuevo">Nombre</label>
            <input id="nuevo" value={nuevo} maxLength={40} onChange={ev => setNuevo(ev.target.value)} />
          </div>
          <button type="submit" className="secundario" disabled={!nuevo.trim()}>
            Agregar
          </button>
        </form>
      </Seccion>

      <Hoja abierta={Boolean(llave)} alCerrar={() => setLlave(null)} titulo="Llave de acceso">
        {llave && (
          <>
            <p className="j-etiqueta">Llave de {llave.nombre}</p>
            <p className="llave-c grande">{llave.llave}</p>
            <p className="j-texto">Con ella entra desde su teléfono. O mándale este enlace y entra solo.</p>
            <div className="hoja-botones">
              <button type="button" className="primario" onClick={() => void copiar(enlaceDeLlave(llave.nombre, llave.llave), avisar, 'Enlace copiado')}>
                Copiar enlace
              </button>
              <button type="button" className="secundario" onClick={() => void copiar(llave.llave, avisar, 'Llave copiada')}>
                Copiar solo la llave
              </button>
            </div>
          </>
        )}
      </Hoja>

      <Hoja abierta={Boolean(detalle)} alCerrar={() => setDetalle(null)} titulo="Acciones del invitado">
        {detalle && (
          <>
            <p className="j-etiqueta">Invitado</p>
            <h2 className="j-titulo chico">{detalle.name}</h2>
            <div className="hoja-botones">
              {!detalle.bot && (
                <button type="button" className="secundario" onClick={() => void nuevaLlave(detalle)}>
                  Generar llave nueva
                </button>
              )}
              <button
                type="button"
                className="secundario peligro"
                onClick={() => {
                  setQuitar(detalle)
                  setDetalle(null)
                }}
              >
                Quitar de la noche
              </button>
            </div>
          </>
        )}
      </Hoja>

      <Confirmar
        abierta={Boolean(quitar)}
        titulo={`¿Quitar a ${quitar?.name ?? ''}?`}
        texto="Se borra su respuesta y su secreto. Si está jugando, sale de la partida."
        boton="Quitar"
        peligro
        alConfirmar={async () => {
          if (quitar) await actuar('admin_player', { p_id: quitar.id, p_action: 'remove' }, 'Listo.')
        }}
        alCerrar={() => setQuitar(null)}
      />
    </>
  )
}
