import { useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Cera } from '../compartido/Sprite'
import { Cuenta } from '../compartido/Cuenta'
import { Hoja } from '../compartido/Hoja'
import { vibrar } from '../lib/movimiento'
import { mensajeDe } from '../servidor/errores'
import { lista, nombres, useJuego } from '../servidor/hooks'
import { tokenDispositivo } from '../servidor/identidad'
import { Fichas } from './Fichas'

/** La votación y el desempate: un voto por persona, sin vuelta atrás. */
export function Votacion() {
  const { e, me, ronda, pausadoEn, llamar } = useJuego()
  const avisar = useAvisos()
  const [elegido, setElegido] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const r = ronda!
  const desempate = r.state === 'desempate'
  const total = desempate ? e.event.durations.tiebreak : e.event.durations.vote
  const objetivo = me.vote_targets.find(t => t.id === elegido)

  const votar = async () => {
    if (!elegido) return
    setEnviando(true)
    try {
      await llamar('cast_vote', { p_token: tokenDispositivo(), p_target: elegido })
      vibrar(24)
      setConfirmando(false)
    } catch (err) {
      avisar(mensajeDe(err), 'error')
      setConfirmando(false)
    }
    setEnviando(false)
  }

  const progreso = (
    <div className="j-progreso" aria-live="polite">
      <div className="j-barra-progreso" role="progressbar" aria-label="Votos emitidos" aria-valuemin={0} aria-valuemax={r.votes_expected} aria-valuenow={r.votes_cast}>
        <span style={{ width: `${r.votes_expected ? (r.votes_cast / r.votes_expected) * 100 : 0}%` }} />
      </div>
      <p className="j-nota chica">
        Ya votaron {r.votes_cast} de {r.votes_expected}.
      </p>
    </div>
  )

  return (
    <section className="j-pantalla j-votacion">
      <p className="j-etiqueta">{desempate ? 'Desempate relámpago' : 'Votación'}</p>
      <h1 className="j-titulo">
        {desempate ? (
          <>
            Empate entre <em>{lista(nombres(r.candidates))}</em>.
          </>
        ) : (
          '¿Quién es el asesino?'
        )}
      </h1>
      <Cuenta hasta={r.ends_at} total={total} pausadoEn={pausadoEn} tamano={desempate ? 9 : 10} />

      {me.can_vote ? (
        <>
          <p className="j-texto">Un voto por persona. No se cambia.</p>
          <Fichas personas={me.vote_targets} elegido={elegido} alElegir={setElegido} verbo="Votar por" />
          {progreso}
          <div className="j-pie-fijo">
            <button type="button" id="j-votar" className="primario" disabled={!elegido} onClick={() => setConfirmando(true)}>
              {elegido ? 'Votar' : 'Elige a alguien'}
            </button>
          </div>
          <Hoja abierta={confirmando} alCerrar={() => setConfirmando(false)} titulo="Confirmar voto">
            <p className="j-etiqueta">Sin vuelta atrás</p>
            <h2 className="j-titulo chico">
              ¿Votas por <em>{objetivo?.name}</em>?
            </h2>
            <p className="j-texto">Si te equivocas, bebes tú. Y con quien votó igual.</p>
            <div className="hoja-botones">
              <button type="button" id="j-confirmar-voto" className="primario" disabled={enviando} onClick={() => void votar()}>
                {enviando ? 'Sellando…' : 'Sí, votar'}
              </button>
              <button type="button" className="secundario" onClick={() => setConfirmando(false)}>
                Todavía no
              </button>
            </div>
          </Hoja>
        </>
      ) : me.my_vote ? (
        <div className="j-sellado" role="status">
          <Cera className="j-sello-voto" />
          <p className="j-titulo chico">Voto sellado.</p>
          <p className="j-texto">
            Votaste por <em>{me.my_vote.name}</em>. Nadie más lo sabe hasta el veredicto.
          </p>
          {progreso}
        </div>
      ) : (
        <div className="j-sellado">
          <p className="j-titulo chico">{me.in_game && me.alive === false ? 'Los muertos no votan.' : 'Esta partida empezó sin ti.'}</p>
          <p className="j-texto">Mira cómo se decide.</p>
          {progreso}
        </div>
      )}
    </section>
  )
}
