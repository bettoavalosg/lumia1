import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Cargando } from '../compartido/Cargando'
import { SinConexion } from '../compartido/SinConexion'
import { Cuenta } from '../compartido/Cuenta'
import { Premios } from '../compartido/Premios'
import { Cera } from '../compartido/Sprite'
import { Revelacion } from '../juego/Veredicto'
import { usePaso } from '../juego/paso'
import { partesRestantes, separador } from '../lib/cuenta'
import { useMantenerDespierta, usePantallaCompleta } from '../lib/despierta'
import { INICIO_FIESTA } from '../lib/evento'
import type { Backend } from '../servidor/backend'
import { useBackend } from '../servidor/BackendContexto'
import { lista, nombres, plazoDelJuego } from '../servidor/hooks'
import { llaveDeLaTv } from '../servidor/identidad'
import { useLatido } from '../servidor/reloj'
import { ServidorProvider, useServidor } from '../servidor/Servidor'
import type { Estado } from '../servidor/tipos'
import '../styles/juego.css'
import '../styles/tv.css'

// Todo se dibuja en rem: escalar la raíz agranda la interfaz entera para verla desde el sillón. Y la tele no se desplaza: si una escena
// trae de más (veinte nombres largos, dos filas de sellos), se achica lo justo para que quepa entera.
const MINIMO_TELE = 0.55
const MINIMO_PX = 12 // por debajo de esto nada se lee desde el sillón: mejor que una escena extrema se corte a que se vuelva ilegible

function ajustarTele() {
  const raiz = document.documentElement
  const base = Math.min(46, Math.max(11, Math.min(window.innerWidth, window.innerHeight) * 0.026))
  let px = base
  raiz.style.fontSize = `${px}px`
  for (let i = 0; i < 6; i++) {
    const alto = raiz.scrollHeight
    const piso = Math.max(base * MINIMO_TELE, MINIMO_PX)
    if (alto <= window.innerHeight + 1 || px <= piso + 0.01) break
    px = Math.max(piso, px * (window.innerHeight / alto) * 0.98)
    raiz.style.fontSize = `${px}px`
  }
  raiz.dataset.ajusteTele = (px / base).toFixed(2)
}

export default function Tv() {
  const backend = useBackend()
  const llave = useMemo(() => llaveDeLaTv(), [])
  useMantenerDespierta()
  usePantallaCompleta()

  useEffect(() => {
    ajustarTele()
    window.addEventListener('resize', ajustarTele)
    return () => {
      window.removeEventListener('resize', ajustarTele)
      document.documentElement.style.fontSize = ''
      delete document.documentElement.dataset.ajusteTele
    }
  }, [])

  if (!llave) {
    return (
      <div className="tv tv-aviso">
        <Cera className="tv-sello-chico" />
        <h1 className="j-titulo">Falta la llave de esta pantalla.</h1>
        <p className="j-texto">Ábrela desde el panel de admin: ahí está el enlace de la tele.</p>
      </div>
    )
  }
  const cargar = (b: Backend) => b.rpc<Estado>('tv_state', { p_key: llave })
  return (
    <ServidorProvider backend={backend} cargar={cargar} plazo={plazoDelJuego}>
      <Escenas />
    </ServidorProvider>
  )
}

function Escenas() {
  const { estado, error } = useServidor<Estado>()
  if (!estado) {
    if (error && error.codigo === 'sin_permiso') {
      return (
        <div className="tv tv-aviso">
          <h1 className="j-titulo">Esta pantalla no tiene permiso.</h1>
          <p className="j-texto">La llave de la tele no es la correcta. Vuelve a abrir el enlace desde el panel de admin.</p>
        </div>
      )
    }
    return <Cargando texto="Preparando la pantalla…" sinRed={Boolean(error)} />
  }
  return <Pantalla e={estado} />
}

function Pantalla({ e }: { e: Estado }) {
  const { ahora } = useServidor<Estado>()
  useLatido(500)
  useLayoutEffect(ajustarTele)
  const g = e.game ?? null
  const r = g?.round ?? null
  const fase = e.event.phase

  // El anuncio de una muerte tiene prioridad sobre todo lo demás durante unos segundos.
  const muerte = g?.last_kill && ahora() - Date.parse(g.last_kill.at) < 11_000 ? g.last_kill.victim.name : null

  let escena: React.ReactNode
  if (fase === 'fin') escena = <TvCierre e={e} />
  else if (fase !== 'jugando' || !g) escena = <TvRecibidor e={e} />
  else if (g.ended) escena = g.next_deal_at ? <TvFinPartida e={e} /> : <TvRecibidor e={e} nota="La partida se canceló. Mariela va a repartir otra vez." />
  else if (!r) escena = <TvRecibidor e={e} />
  else if (r.state === 'apertura') escena = <TvApertura e={e} />
  else if (r.state === 'votacion' || r.state === 'desempate') escena = <TvVotacion e={e} />
  else if (r.state === 'veredicto' && r.verdict) escena = <TvVeredicto e={e} />
  else escena = <TvRonda e={e} />

  return (
    <div className="tv juego">
      <div className="bruma" aria-hidden="true" />
      <header className="tv-cab">
        <span className="tv-marca">
          <svg viewBox="0 0 80 80" aria-hidden="true" focusable="false">
            <use href="#blason" />
          </svg>
          Mariela · XXIX
        </span>
        {g && fase === 'jugando' && (
          <span className="tv-contexto">
            Partida {g.number}
            {r && !g.ended ? ` · Ronda ${r.number}` : ''}
          </span>
        )}
        <span className="tv-contexto">
          {e.event.present_count} presentes
          {e.event.paused_at ? ' · en pausa' : ''}
        </span>
      </header>
      <SinConexion clase="tv-conexion" />
      <main className="tv-centro" key={escena && typeof escena === 'object' && 'type' in escena ? String((escena.type as { name?: string }).name) : 'x'}>
        {escena}
      </main>
      <UltimaHora e={e} />
      {e.event.paused_at && (
        <div className="tv-pausa" role="status">
          Pausa
        </div>
      )}
      {muerte && <TvMuerte nombre={muerte} />}
    </div>
  )
}

/** Una línea al pie con lo último que pasó: quién llegó, quién cayó. */
function UltimaHora({ e }: { e: Estado }) {
  const [linea, setLinea] = useState<{ texto: string; id: number } | null>(null)
  const previo = useRef<Estado | null>(null)
  const siguiente = useRef(1)

  useEffect(() => {
    const antes = previo.current
    previo.current = e
    if (!antes) return
    const llegados = (e.players ?? []).filter(p => p.checked_in && !(antes.players ?? []).find(q => q.id === p.id)?.checked_in)
    let texto: string | null = null
    if (llegados.length) {
      // Con una oleada de llegadas la línea no debe ocupar media pantalla: dos nombres y "N más".
      const quienes = llegados.map(p => p.name)
      const resumen = quienes.length <= 3 ? lista(quienes) : `${lista(quienes.slice(0, 2))} y ${quienes.length - 2} más`
      texto = `Última hora: ${resumen} ${llegados.length === 1 ? 'acaba de llegar' : 'acaban de llegar'}.`
    }
    const lk = e.game?.last_kill
    if (lk && lk.at !== antes.game?.last_kill?.at) texto = `Última hora: ${lk.victim.name} ya no está entre nosotros.`
    if (e.game && e.game.number !== antes.game?.number) texto = 'Última hora: se repartieron las cartas.'
    if (texto) setLinea({ texto, id: siguiente.current++ })
  }, [e])

  useEffect(() => {
    if (!linea) return
    const id = setTimeout(() => setLinea(null), 12_000)
    return () => clearTimeout(id)
  }, [linea])

  return (
    <footer className="tv-pie" aria-live="polite">
      {linea && (
        <p key={linea.id} className="tv-ultima">
          {linea.texto} <span>XOXO</span>
        </p>
      )}
    </footer>
  )
}

// -- antes de jugar ---------------------------------------------------------------------------------------
function TvRecibidor({ e, nota }: { e: Estado; nota?: string }) {
  const { ahora } = useServidor<Estado>()
  useLatido(1000)
  const puerta = e.event.phase === 'lobby' || e.event.phase === 'jugando'
  const presentes = (e.players ?? []).filter(p => p.checked_in)
  const partes = partesRestantes(INICIO_FIESTA.getTime() - ahora())

  return (
    <section className="tv-escena tv-recibidor">
      <p className="j-etiqueta">{puerta ? 'La puerta está abierta' : 'Sábado 24 de octubre · 6:00 pm'}</p>
      <h1 className="tv-gran-titulo">
        Mariela <em>cumple 29</em>
      </h1>
      {nota && <p className="j-texto destacado">{nota}</p>}
      {!puerta && partes && (
        <p className="tv-cuenta-fiesta">
          {partes.slice(0, 3).map((parte, i, a) => (
            <span key={parte.clave}>
              <b>{parte.valor}</b> {parte.unidad}
              {separador(i, a.length)}{' '}
            </span>
          ))}
        </p>
      )}
      {puerta && (
        <>
          {e.door_code && (
            <div className="tv-codigo">
              <span className="j-subetiqueta">Código de la puerta</span>
              <b>{e.door_code}</b>
            </div>
          )}
          <p className="tv-llegados">
            <b>{presentes.length}</b> de {e.event.rsvp_count} ya llegaron
          </p>
          <ul className="j-nombres tv-nombres">
            {presentes.map((p, i) => (
              <li key={p.id} style={{ '--i': Math.min(i, 24) }}>
                {p.name}
              </li>
            ))}
          </ul>
          <p className="j-susurro">Mírense bien. Después del reparto, nadie será quien dice ser.</p>
        </>
      )}
      {!puerta && <p className="j-susurro">Todavía no abren la puerta. Alguien va a escribir un secreto sobre ti.</p>}
    </section>
  )
}

// -- durante la partida ------------------------------------------------------------------------------------
function Vivos({ e }: { e: Estado }) {
  const jugadores = (e.players ?? []).filter(p => p.in_game)
  const vivos = jugadores.filter(p => p.alive)
  const caidos = jugadores.filter(p => !p.alive)
  return (
    <div className="tv-vivos">
      <p className="j-subetiqueta">
        Con vida · <b>{vivos.length}</b>
      </p>
      <ul className="j-nombres tv-nombres">
        {vivos.map(p => (
          <li key={p.id}>{p.name}</li>
        ))}
      </ul>
      {caidos.length > 0 && (
        <>
          <p className="j-subetiqueta">Ya no están · {caidos.length}</p>
          <ul className="j-nombres caidos tv-nombres">
            {caidos.map(p => (
              <li key={p.id}>{p.name}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function TvRonda({ e }: { e: Estado }) {
  const r = e.game!.round!
  return (
    <section className="tv-escena tv-ronda">
      <h1 className="sr-only">Ronda {r.number}</h1>
      <div className="tv-reloj">
        <p className="j-etiqueta" aria-hidden="true">
          Ronda {r.number}
        </p>
        <Cuenta hasta={r.ends_at} total={e.event.durations.round} pausadoEn={e.event.paused_at} tamano={18} etiqueta="para votar" />
        <p className="j-frase">Platiquen. Sospechen. Acusen.</p>
      </div>
      <Vivos e={e} />
    </section>
  )
}

function TvApertura({ e }: { e: Estado }) {
  const r = e.game!.round!
  return (
    <section className="tv-escena">
      <p className="j-etiqueta">Antes de la primera ronda</p>
      <h1 className="tv-gran-titulo">La noche empieza <em>con sangre</em>.</h1>
      <Cuenta hasta={r.ends_at} total={e.event.durations.kill} pausadoEn={e.event.paused_at} tamano={14} />
      <p className="j-texto">Alguien está eligiendo a la primera víctima.</p>
    </section>
  )
}

function TvVotacion({ e }: { e: Estado }) {
  const r = e.game!.round!
  const desempate = r.state === 'desempate'
  return (
    <section className="tv-escena tv-votacion">
      <p className="j-etiqueta">{desempate ? 'Desempate relámpago' : 'Votación'}</p>
      <h1 className="tv-gran-titulo">
        {desempate ? (
          <>
            Empate entre <em>{lista(nombres(r.candidates))}</em>
          </>
        ) : (
          <>
            ¿Quién es <em>el asesino</em>?
          </>
        )}
      </h1>
      <Cuenta hasta={r.ends_at} total={desempate ? e.event.durations.tiebreak : e.event.durations.vote} pausadoEn={e.event.paused_at} tamano={12.5} />
      <div className="tv-sellos" role="img" aria-label={`Han votado ${r.votes_cast} de ${r.votes_expected}`}>
        {Array.from({ length: r.votes_expected }, (_, i) => (
          <Cera key={i} className={i < r.votes_cast ? 'lleno' : 'vacio'} />
        ))}
      </div>
      <p className="j-nota">
        Han votado <b>{r.votes_cast}</b> de {r.votes_expected}. Los votos se revelan con el veredicto.
      </p>
    </section>
  )
}

function TvVeredicto({ e }: { e: Estado }) {
  const r = e.game!.round!
  const v = r.verdict!
  const paso = usePaso(v.at, [0, 900, 2600, 4100, 5500, 7100])
  return (
    <section className="tv-escena tv-veredicto">
      <p className="j-etiqueta">Veredicto</p>
      <Revelacion v={v} paso={paso} />
      <div className="tv-espera">
        <Cuenta hasta={v.kill_ends_at} total={e.event.durations.kill} pausadoEn={e.event.paused_at} tamano={6.5} />
        <p className="j-subetiqueta">El asesino elige</p>
      </div>
    </section>
  )
}

function TvFinPartida({ e }: { e: Estado }) {
  const g = e.game!
  const v = g.round?.verdict ?? null
  const paso = usePaso(v?.at, [0, 900, 2600, 4100, 5500, 7100])
  const asesinos = nombres(g.killers)
  return (
    <section className="tv-escena tv-veredicto">
      <p className="j-etiqueta">Fin de la partida {g.number}</p>
      <h1 className="tv-gran-titulo">{g.result === 'atrapado' ? 'La atraparon.' : 'Ganó el asesino.'}</h1>
      <p className="j-texto destacado">
        {asesinos.length > 1 ? 'Los asesinos eran ' : 'El asesino era '}
        <em>{lista(asesinos)}</em>.
      </p>
      {v && g.result === 'atrapado' && <Revelacion v={v} paso={paso} />}
      {g.next_deal_at && (
        <div className="tv-espera">
          <Cuenta hasta={g.next_deal_at} total={e.event.durations.pause} pausadoEn={e.event.paused_at} tamano={6.5} />
          <p className="j-subetiqueta">Cartas nuevas</p>
        </div>
      )}
    </section>
  )
}

function TvCierre({ e }: { e: Estado }) {
  return (
    <section className="tv-escena tv-cierre">
      <p className="j-etiqueta">Fin de la noche</p>
      <h1 className="tv-gran-titulo">
        Se acabó <em>la noche</em>.
      </h1>
      {e.ranking ? <Premios ranking={e.ranking} clase="tv-premios" /> : <p className="j-texto">Nadie bebió. Sospechoso.</p>}
      <p className="j-firma">XOXO</p>
    </section>
  )
}

/** Alguien cayó: la tele lo anuncia con el sello roto. */
function TvMuerte({ nombre }: { nombre: string }) {
  return (
    <div className="tv-muerte" role="alert">
      <div className="j-muerte-sello" aria-hidden="true">
        <Cera />
        <svg viewBox="0 0 240 240" focusable="false">
          <polyline pathLength={100} points="127,0 123,16 120,32 113,50 119,65 125,84 132,96 122,111 116,126 110,142 119,156 122,172 127,187 125,205 117,222 115,240" />
        </svg>
      </div>
      <p className="j-etiqueta">Última hora</p>
      <h1 className="tv-gran-titulo">
        <em>{nombre}</em> ha muerto.
      </h1>
      <p className="j-firma">XOXO</p>
    </div>
  )
}
