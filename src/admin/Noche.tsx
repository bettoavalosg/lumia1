import { useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Cuenta } from '../compartido/Cuenta'
import type { EstadoRonda } from '../servidor/tipos'
import { Confirmar, copiar, Seccion, useAdmin } from './comun'

const ESTADO_RONDA: Record<EstadoRonda, string> = {
  apertura: 'Muerte de apertura',
  discusion: 'Discusión',
  votacion: 'Votación',
  desempate: 'Desempate',
  veredicto: 'Veredicto · el asesino elige',
  cerrada: 'Cerrada',
}

const ADELANTAR: Partial<Record<EstadoRonda, string>> = {
  apertura: 'Elegir la víctima al azar ya',
  discusion: 'Abrir la votación ya',
  votacion: 'Cerrar la votación ya',
  desempate: 'Cerrar el desempate ya',
  veredicto: 'Elegir la víctima al azar ya',
}

export function Noche({ irA }: { irA: (p: 'invitados' | 'secretos' | 'ajustes') => void }) {
  const { a, actuar } = useAdmin()
  const avisar = useAvisos()
  const [confirmar, setConfirmar] = useState<'terminar' | 'repartir' | null>(null)
  const ev = a.event
  const g = a.game
  const r = g?.round ?? null
  const activa = Boolean(g && !g.ended && ev.phase === 'jugando')
  const entreJuegos = Boolean(g && g.ended && ev.phase === 'jugando')
  const pausado = Boolean(ev.paused_at)
  const aprobados = a.secrets.filter(s => s.status === 'aprobado').length
  const pendientes = a.secrets.filter(s => s.status === 'pendiente').length
  const urlTv = `${location.origin}/tv#k=${ev.tv_key}`

  return (
    <>
      <Seccion titulo="Ahora">
        <div className="ad-estado">
          {activa && r ? (
            <>
              <p className="j-etiqueta">
                Partida {g!.number} · Ronda {r.number}
              </p>
              <p className="ad-grande">{ESTADO_RONDA[r.state]}</p>
              {r.ends_at && r.state !== 'veredicto' && (
                <Cuenta
                  hasta={r.ends_at}
                  total={r.state === 'discusion' ? ev.durations.round : r.state === 'votacion' ? ev.durations.vote : r.state === 'desempate' ? ev.durations.tiebreak : ev.durations.kill}
                  pausadoEn={ev.paused_at}
                  tamano={8}
                />
              )}
              {r.state === 'veredicto' && r.verdict?.kill_ends_at && <Cuenta hasta={r.verdict.kill_ends_at} total={ev.durations.kill} pausadoEn={ev.paused_at} tamano={8} />}
              <p className="j-nota">
                {g!.alive_count} con vida
                {(r.state === 'votacion' || r.state === 'desempate') && ` · ${r.votes_cast} de ${r.votes_expected} votos`}
                {pausado && ' · en pausa'}
              </p>
            </>
          ) : entreJuegos && g ? (
            <>
              <p className="j-etiqueta">Partida {g.number} terminada</p>
              <p className="ad-grande">{g.result === 'atrapado' ? 'Atraparon al asesino' : g.result === 'asesino_gana' ? 'Ganó el asesino' : 'Partida cancelada'}</p>
              {g.next_deal_at && <Cuenta hasta={g.next_deal_at} total={ev.durations.pause} pausadoEn={ev.paused_at} tamano={7} etiqueta="cartas nuevas" />}
            </>
          ) : (
            <>
              <p className="j-etiqueta">{ev.phase === 'invitacion' ? 'Invitación' : ev.phase === 'lobby' ? 'Puerta abierta' : ev.phase === 'fin' ? 'Terminó' : 'Sin partida'}</p>
              <p className="ad-grande">
                {ev.present_count} de {ev.rsvp_count} presentes
              </p>
            </>
          )}
        </div>
      </Seccion>

      <Seccion titulo="Controles">
        <div className="ad-acciones">
          {ev.phase === 'invitacion' && (
            <button type="button" className="primario" onClick={() => void actuar('admin_phase', { p_phase: 'lobby' }, 'La puerta está abierta.')}>
              Abrir la puerta
            </button>
          )}
          {ev.phase === 'lobby' && (
            <>
              <button
                type="button"
                className="primario"
                id="ad-repartir"
                disabled={ev.present_count < 3}
                onClick={() => void actuar('admin_deal', { p_force: false }, 'Cartas repartidas.')}
              >
                Repartir cartas
              </button>
              {ev.present_count < 3 && <p className="ad-nota">Se necesitan al menos 3 personas presentes.</p>}
              <button type="button" className="secundario" onClick={() => void actuar('admin_phase', { p_phase: 'invitacion' }, 'Puerta cerrada.')}>
                Cerrar la puerta
              </button>
            </>
          )}
          {ev.phase === 'jugando' && (
            <>
              <button type="button" className="secundario" onClick={() => void actuar('admin_control', { p_action: pausado ? 'resume' : 'pause' }, pausado ? 'El juego sigue.' : 'Juego en pausa.')}>
                {pausado ? 'Reanudar' : 'Pausar'}
              </button>
              {(activa && r && ADELANTAR[r.state]) || entreJuegos ? (
                <button type="button" className="secundario" disabled={pausado} onClick={() => void actuar('admin_control', { p_action: 'force' })}>
                  {entreJuegos ? 'Repartir ahora' : ADELANTAR[r!.state]}
                </button>
              ) : null}
              <button type="button" className="secundario" onClick={() => setConfirmar('repartir')}>
                Repartir de nuevo
              </button>
              <button type="button" className="secundario peligro" onClick={() => setConfirmar('terminar')}>
                Terminar la noche
              </button>
            </>
          )}
          {ev.phase === 'fin' && (
            <button type="button" className="primario" onClick={() => void actuar('admin_control', { p_action: 'reopen' }, 'La noche sigue abierta.')}>
              Reabrir la noche
            </button>
          )}
        </div>
      </Seccion>

      {(ev.phase === 'invitacion' || ev.phase === 'lobby') && (
        <Seccion titulo="Antes de repartir">
          <ul className="ad-lista-check">
            <li className={ev.present_count >= 3 ? 'ok' : 'falta'}>
              <span>{ev.present_count} presentes de {ev.rsvp_count} invitados</span>
              <button type="button" className="j-enlace" onClick={() => irA('invitados')}>
                Ver
              </button>
            </li>
            <li className={aprobados >= 3 && pendientes === 0 ? 'ok' : 'falta'}>
              <span>
                {aprobados} secretos aprobados{pendientes ? `, ${pendientes} por revisar` : ''}
              </span>
              <button type="button" className="j-enlace" onClick={() => irA('secretos')}>
                Revisar
              </button>
            </li>
            <li className={ev.address ? 'ok' : 'falta'}>
              <span>{ev.address ? (ev.address_revealed ? 'Dirección revelada' : 'Dirección lista, todavía oculta') : 'Falta la dirección'}</span>
              <button type="button" className="j-enlace" onClick={() => irA('ajustes')}>
                Ajustes
              </button>
            </li>
            <li className={ev.door_code ? 'ok' : 'neutro'}>
              <span>{ev.door_code ? `Código de la puerta: ${ev.door_code}` : 'Sin código de puerta (todos entran con un toque)'}</span>
              <button type="button" className="j-enlace" onClick={() => irA('ajustes')}>
                Ajustes
              </button>
            </li>
            {ev.rehearsal && (
              <li className="falta">
                <span>El modo ensayo sigue encendido: hay bots y el reloj puede ir adelantado. Apágalo antes de la fiesta.</span>
                <button type="button" className="j-enlace" onClick={() => irA('ajustes')}>
                  Ajustes
                </button>
              </li>
            )}
          </ul>
        </Seccion>
      )}

      <Seccion titulo="La tele" nota="Abre este enlace en la pantalla que van a proyectar. Tiene una llave: no la compartas.">
        <div className="ad-enlace">
          <code>{urlTv}</code>
          <div className="ad-fila-botones">
            <button type="button" className="secundario" onClick={() => void copiar(urlTv, avisar, 'Enlace de la tele copiado')}>
              Copiar
            </button>
            <a className="secundario" href={urlTv} target="_blank" rel="noreferrer">
              Abrir
            </a>
          </div>
        </div>
      </Seccion>

      <Confirmar
        abierta={confirmar === 'terminar'}
        titulo="¿Terminar la noche?"
        texto="Se cancela la partida en curso y la tele muestra el ranking. Puedes reabrirla después."
        boton="Terminar la noche"
        peligro
        alConfirmar={async () => {
          await actuar('admin_control', { p_action: 'end_night' }, 'La noche terminó.')
        }}
        alCerrar={() => setConfirmar(null)}
      />
      <Confirmar
        abierta={confirmar === 'repartir'}
        titulo="¿Repartir de nuevo?"
        texto="La partida en curso se cancela y todos reciben cartas nuevas ahora mismo."
        boton="Repartir de nuevo"
        peligro
        alConfirmar={async () => {
          await actuar('admin_deal', { p_force: true }, 'Cartas nuevas.')
        }}
        alCerrar={() => setConfirmar(null)}
      />
    </>
  )
}
