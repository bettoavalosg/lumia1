// Iconos de trazo fino, en el mismo tono que el grabado de las tarjetas.
const base = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: false } as const

export const IconoNoche = () => (
  <svg {...base}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
    <path d="M17 4.5v3M15.5 6h3" />
  </svg>
)
export const IconoCarta = () => (
  <svg {...base}>
    <rect x="6" y="3" width="12" height="18" rx="1.6" />
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 6.8v1.4M12 15.8v1.4M7.8 12h1.4M14.8 12h1.4" />
  </svg>
)
export const IconoBitacora = () => (
  <svg {...base}>
    <path d="M6 3h11a1 1 0 0 1 1 1v15a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a1 1 0 0 1 1-1Z" />
    <path d="M9 8h6M9 12h6M9 16h3.5" />
  </svg>
)
export const IconoCopa = () => (
  <svg {...base}>
    <path d="M7 3h10l-.7 6.2a4.3 4.3 0 0 1-8.6 0L7 3Z" />
    <path d="M12 13.5V20M8.5 20h7" />
  </svg>
)
export const IconoDaga = () => (
  <svg {...base}>
    <path d="M12 21 9.6 8.5 12 3l2.4 5.5L12 21Z" />
    <path d="M7 8.5h10" />
  </svg>
)
export const IconoCalavera = () => (
  <svg {...base}>
    <path d="M12 3.5c-4.4 0-7.2 2.9-7.2 6.8 0 2.4 1.1 4 2.7 5v3.2h9v-3.2c1.6-1 2.7-2.6 2.7-5 0-3.9-2.8-6.8-7.2-6.8Z" />
    <circle cx="9.2" cy="10.8" r="1.5" />
    <circle cx="14.8" cy="10.8" r="1.5" />
    <path d="M10.5 18.5v-2M13.5 18.5v-2" />
  </svg>
)
export const IconoPalomita = () => (
  <svg {...base}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
)
export const IconoCampana = () => (
  <svg {...base}>
    <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15L6 16.5Z" />
    <path d="M10 20.5a2 2 0 0 0 4 0" />
  </svg>
)
export const IconoCompartir = () => (
  <svg {...base}>
    <path d="M12 15V3.5M8 7.5l4-4 4 4" />
    <path d="M6 11.5H5a1 1 0 0 0-1 1V20a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7.5a1 1 0 0 0-1-1h-1" />
  </svg>
)
