import { useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Cuenta } from '../compartido/Cuenta'
import { Hoja } from '../compartido/Hoja'
import { vibrar } from '../lib/movimiento'
import { mensajeDe } from '../servidor/errores'
import { useJuego } from '../servidor/hooks'
import { tokenDispositivo } from '../servidor/identidad'
import { Fichas } from './Fichas'

interface Props {
  hasta: string | null
  total: number
  titulo: string
  texto: string
}

/** Solo lo ve el asesino: elegir a quién le toca caer. Si se acaba el tiempo, el azar elige por él. */
export function SelectorVictima({ hasta, total, titulo, texto }: Props) {
  const { me, llamar, pausadoEn } = useJuego()
  const avisar = useAvisos()
  const [elegido, setElegido] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const victima = me.kill_targets.find(t => t.id === elegido)

  const golpear = async () => {
    if (!elegido) return
    setEnviando(true)
    try {
      await llamar('kill', { p_token: tokenDispositivo(), p_victim: elegido })
      vibrar([30, 40, 90])
    } catch (e) {
      avisar(mensajeDe(e), 'error')
      setConfirmando(false)
    }
    setEnviando(false)
  }

  return (
    <section className="j-golpe" aria-labelledby="golpe-t">
      <p className="j-etiqueta rojo">Solo tú ves esto</p>
      <h2 id="golpe-t" className="j-titulo chico">
        {titulo}
      </h2>
      <p className="j-texto">{texto}</p>
      <Cuenta hasta={hasta} total={total} pausadoEn={pausadoEn} tamano={8} />
      <Fichas personas={me.kill_targets} elegido={elegido} alElegir={setElegido} verbo="Elegir a" />
      <div className="j-pie-fijo">
        <button type="button" id="j-elegir-victima" className="primario rojo" disabled={!elegido} onClick={() => setConfirmando(true)}>
          {elegido ? 'Elegir víctima' : 'Elige a alguien'}
        </button>
      </div>
      <Hoja abierta={confirmando} alCerrar={() => setConfirmando(false)} titulo="Confirmar víctima">
        <p className="j-etiqueta rojo">Sin vuelta atrás</p>
        <h3 className="j-titulo chico">
          ¿Será <em>{victima?.name}</em>?
        </h3>
        <p className="j-texto">Se entera en cuanto lo confirmes. Y la tele lo va a anunciar.</p>
        <div className="hoja-botones">
          <button type="button" id="j-confirmar-victima" className="primario rojo" disabled={enviando} onClick={() => void golpear()}>
            {enviando ? 'Un momento…' : 'Confirmar'}
          </button>
          <button type="button" className="secundario" onClick={() => setConfirmando(false)}>
            Todavía no
          </button>
        </div>
      </Hoja>
    </section>
  )
}
