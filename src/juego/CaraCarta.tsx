import type { Rol } from '../servidor/tipos'

/** 24 rayos alrededor del círculo, uno largo y uno corto: el mismo grabado del dorso. */
function Rayos() {
  return (
    <g stroke="currentColor" strokeWidth=".8" opacity=".6">
      {Array.from({ length: 24 }, (_, i) => {
        const a = ((i * 15 - 90) * Math.PI) / 180
        const r2 = i % 2 === 0 ? 118 : 107
        const punto = (r: number) => [(140 + r * Math.cos(a)).toFixed(1), (240 + r * Math.sin(a)).toFixed(1)]
        const [x1, y1] = punto(96)
        const [x2, y2] = punto(r2)
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} />
      })}
    </g>
  )
}

const Estrella = ({ x, y, s }: { x: number; y: number; s: number }) => <use href="#c-estrella" transform={`translate(${x} ${y}) scale(${s})`} />

/** El marco de tarot que comparten el dorso y las dos caras. */
function Marco({ numero, titulo, leyenda }: { numero: string; titulo: string; leyenda: string }) {
  return (
    <>
      <defs>
        <path id="c-estrella" d="M0-7L1.4-1.4L7 0L1.4 1.4L0 7L-1.4 1.4L-7 0L-1.4-1.4Z" />
        <path id="c-rombo" d="M0-4L4 0L0 4L-4 0Z" />
      </defs>
      <rect x="9" y="9" width="262" height="462" rx="10" fill="none" stroke="currentColor" />
      <rect x="17" y="17" width="246" height="446" rx="6" fill="none" stroke="currentColor" strokeWidth=".6" opacity=".55" />
      <g fill="currentColor" opacity=".8">
        <use href="#c-rombo" transform="translate(30 30)" />
        <use href="#c-rombo" transform="translate(250 30)" />
        <use href="#c-rombo" transform="translate(30 450)" />
        <use href="#c-rombo" transform="translate(250 450)" />
      </g>
      <text className="cara-num" x="140" y="66" textAnchor="middle">
        {numero}
      </text>
      <Rayos />
      <circle cx="140" cy="240" r="90" fill="none" stroke="currentColor" />
      <circle cx="140" cy="240" r="82" fill="none" stroke="currentColor" strokeWidth=".7" strokeDasharray="1 5" opacity=".7" />
      <g fill="currentColor">
        <Estrella x={62} y={116} s={0.55} />
        <Estrella x={218} y={116} s={0.55} />
        <Estrella x={62} y={364} s={0.55} />
        <Estrella x={218} y={364} s={0.55} />
      </g>
      <text className="cara-titulo" x="140" y="414" textAnchor="middle">
        {titulo}
      </text>
      <text className="cara-leyenda" x="140" y="440" textAnchor="middle">
        {leyenda}
      </text>
    </>
  )
}

/** Una daga con el sello de cera en la guarda. La única mancha de rojo de toda la baraja. */
function Daga() {
  return (
    <g>
      <path d="M140 205 L153 209 L149 300 L140 342 L131 300 L127 209 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M140 216 L140 322" stroke="currentColor" strokeWidth=".7" opacity=".7" />
      <path d="M102 197 Q140 185 178 197 L178 204 Q140 193 102 204 Z" fill="currentColor" />
      <rect x="135.5" y="156" width="9" height="38" rx="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <g stroke="currentColor" strokeWidth=".8" opacity=".7">
        <line x1="135.5" y1="164" x2="144.5" y2="168" />
        <line x1="135.5" y1="172" x2="144.5" y2="176" />
        <line x1="135.5" y1="180" x2="144.5" y2="184" />
      </g>
      <circle cx="140" cy="148" r="7" fill="currentColor" />
      <use href="#cera" x="119" y="176" width="42" height="42" />
    </g>
  )
}

/** Una vela encendida: la inocencia es una luz pequeña. */
function Vela() {
  return (
    <g>
      <path d="M140 176 C151 191 153 201 140 213 C127 201 129 191 140 176 Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M140 191 C145 198 145 204 140 209 C135 204 135 198 140 191 Z" fill="currentColor" opacity=".85" />
      <path d="M140 213 V222" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M127 224 H153 V296 Q153 300 149 300 H131 Q127 300 127 296 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M127 234 Q133 244 138 234 Q142 250 148 236 L153 236" fill="none" stroke="currentColor" strokeWidth=".9" opacity=".75" />
      <path d="M112 300 H168 L162 312 Q140 320 118 312 Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M124 262 V292 M140 258 V294" stroke="currentColor" strokeWidth=".6" opacity=".45" />
    </g>
  )
}

/** La carta boca arriba. Solo existe en pantalla mientras se mantiene presionada. */
export function CaraCarta({ rol }: { rol: Rol }) {
  const asesino = rol === 'asesino'
  return (
    <svg className="cara-svg" viewBox="0 0 280 480" aria-hidden="true" focusable="false">
      <Marco numero={asesino ? 'XIII' : '0'} titulo={asesino ? 'ASESINO' : 'INOCENTE'} leyenda={asesino ? 'La Muerte' : 'El Loco'} />
      {asesino ? <Daga /> : <Vela />}
    </svg>
  )
}
