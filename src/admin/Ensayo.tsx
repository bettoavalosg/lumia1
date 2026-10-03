import { useState } from 'react'
import { useBackend } from '../servidor/BackendContexto'
import { Confirmar, Seccion, useAdmin } from './comun'

interface Dios {
  roles: { name: string; role: string; alive: boolean }[]
  votes: { voter: string; target: string; stage: number }[]
}

export function Ensayo() {
  const { a, actuar } = useAdmin()
  const backend = useBackend()
  const [bots, setBots] = useState('12')
  const [dios, setDios] = useState<Dios | null>(null)
  const [reiniciar, setReiniciar] = useState(false)
  const adelantar = (segundos: number) => void actuar('admin_rehearsal', { p_action: 'advance', p_value: segundos }, `+${segundos >= 60 ? `${segundos / 60} min` : `${segundos} s`}`)

  return (
    <>
      <Seccion titulo="Bots" nota="Jugadores falsos que llegan, votan y matan solos unos segundos después de que se abre cada momento.">
        <div className="ad-form-linea">
          <div className="campo">
            <label htmlFor="e-bots">Cuántos</label>
            <input id="e-bots" inputMode="numeric" value={bots} onChange={ev => setBots(ev.target.value)} />
          </div>
          <button type="button" className="secundario" onClick={() => void actuar('admin_rehearsal', { p_action: 'bots', p_value: Number(bots) || 12 }, 'Bots agregados.')}>
            Agregar bots
          </button>
        </div>
        <p className="ad-nota">Ahora hay {a.players.filter(p => p.bot).length} bots.</p>
      </Seccion>

      <Seccion titulo="Reloj" nota={`Adelanta el reloj del servidor para recorrer la noche sin esperar. Desfase actual: ${Math.round(a.event.clock_offset_seconds / 60)} min.`}>
        <div className="ad-fila-botones">
          {[30, 60, 300, 1200].map(s => (
            <button key={s} type="button" className="secundario" onClick={() => adelantar(s)}>
              +{s >= 60 ? `${s / 60} min` : `${s} s`}
            </button>
          ))}
        </div>
      </Seccion>

      <Seccion titulo="Vista de depuración" nota="Solo existe en ensayo: quién es quién y cómo va la votación. Es un spoiler.">
        <div className="ad-fila-botones">
          <button
            type="button"
            className="secundario"
            onClick={async () => {
              const r = await actuar<Dios>('admin_rehearsal', { p_action: 'god' })
              if (r) setDios(r)
            }}
          >
            {dios ? 'Actualizar' : 'Mostrar roles y votos'}
          </button>
          {dios && (
            <button type="button" className="j-enlace" onClick={() => setDios(null)}>
              Ocultar
            </button>
          )}
        </div>
        {dios && (
          <div className="ad-dios">
            <ul>
              {dios.roles.map(r => (
                <li key={r.name} className={r.role === 'asesino' ? 'asesino' : ''}>
                  <span>{r.name}</span>
                  <em>{r.role}</em>
                  <span>{r.alive ? 'vivo' : 'muerto'}</span>
                </li>
              ))}
            </ul>
            {dios.votes.length > 0 && (
              <p className="ad-nota">
                Votos: {dios.votes.map(v => `${v.voter} → ${v.target}`).join(' · ')}
              </p>
            )}
          </div>
        )}
      </Seccion>

      <Seccion titulo="Empezar de cero">
        <div className="ad-fila-botones">
          <button type="button" className="secundario peligro" onClick={() => setReiniciar(true)}>
            Reiniciar el ensayo
          </button>
          {backend.modo === 'demo' && (
            <a className="secundario" href="/demo">
              Abrir el simulador
            </a>
          )}
        </div>
      </Seccion>

      <Confirmar
        abierta={reiniciar}
        titulo="¿Reiniciar el ensayo?"
        texto="Se borran las partidas, los votos y los bots; los secretos revelados vuelven al montón. Los invitados y sus respuestas se quedan."
        boton="Reiniciar"
        peligro
        alConfirmar={async () => {
          await actuar('admin_rehearsal', { p_action: 'reset' }, 'Ensayo reiniciado.')
        }}
        alCerrar={() => setReiniciar(false)}
      />
    </>
  )
}
