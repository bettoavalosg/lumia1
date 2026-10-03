import type { DemoExpuesto } from './backend'
import { ErrorJuego } from './errores'

// El demo es Postgres de verdad (PGlite, en WebAssembly) con EXACTAMENTE las mismas migraciones que van a
// Supabase. Así el motor que se prueba aquí es el mismo que corre la noche de la fiesta.
const migraciones = import.meta.glob('../../supabase/migrations/*.sql', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

const BASE_IDB = 'mariela-demo'
export const PIN_DEMO = '000000'

// Lo que Supabase ya trae y las migraciones dan por hecho.
const PREPARAR = `
  do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
  end $$;
  create schema if not exists extensions;
  grant usage on schema public to anon, authenticated, service_role;
`

function huella(texto: string): string {
  let h = 5381
  for (let i = 0; i < texto.length; i++) h = ((h << 5) + h + texto.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
}

function borrarIdb(): Promise<void> {
  return new Promise(resolver => {
    const pedido = indexedDB.deleteDatabase(`/pglite/${BASE_IDB}`)
    pedido.onsuccess = pedido.onerror = pedido.onblocked = () => resolver()
  })
}

/** Una sola pestaña puede abrir el demo a la vez: dos escribiendo en la misma base la corromperían. */
async function tomarPestana(): Promise<void> {
  if (!('locks' in navigator)) return
  const obtenido = await new Promise<boolean>(resolver => {
    void navigator.locks.request('mariela-demo', { ifAvailable: true }, lock => {
      resolver(lock !== null)
      return lock ? new Promise<void>(() => undefined) : undefined
    })
  })
  if (!obtenido) {
    throw new ErrorJuego('demo_ocupado', 'El modo demo ya está abierto en otra pestaña. Ciérrala o usa esa.')
  }
}

let instancia: Promise<DemoExpuesto> | null = null

export function crearDemo(): Promise<DemoExpuesto> {
  instancia ??= iniciar()
  return instancia
}

async function iniciar(): Promise<DemoExpuesto> {
  await tomarPestana()
  const [{ PGlite }, { pgcrypto }] = await Promise.all([import('@electric-sql/pglite'), import('@electric-sql/pglite/contrib/pgcrypto')])
  const orden = Object.keys(migraciones).sort()
  const version = huella(orden.map(k => migraciones[k]).join('\n'))

  // Si las migraciones cambiaron desde la última vez, la base guardada ya no sirve.
  try {
    if (localStorage.getItem('mariela.demo.version') !== version) await borrarIdb()
  } catch {
    // sin localStorage: se sigue
  }

  let db: InstanceType<typeof PGlite>
  try {
    db = new PGlite(`idb://${BASE_IDB}`, { extensions: { pgcrypto } })
    await db.waitReady
  } catch {
    db = new PGlite({ extensions: { pgcrypto } })
    await db.waitReady
  }

  const existe = await db.query<{ ok: boolean }>(`select to_regclass('app.event') is not null as ok`)
  if (!existe.rows[0]?.ok) {
    await db.exec(PREPARAR)
    for (const nombre of orden) await db.exec(migraciones[nombre])
    await db.query('select app.set_admin_pin($1)', [PIN_DEMO])
  }
  try {
    localStorage.setItem('mariela.demo.version', version)
  } catch {
    // ok
  }

  // Las firmas de las funciones, para armar cada llamada con los tipos correctos.
  const firmas = new Map<string, { nombre: string; tipo: string }[]>()
  const filas = await db.query<{ fn: string; nombres: string[] | null; tipos: string[] | null }>(`
    select p.proname as fn, p.proargnames as nombres,
           (select array_agg(format_type(t, null) order by o) from unnest(p.proargtypes::oid[]) with ordinality as x(t, o)) as tipos
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'`)
  for (const { fn, nombres, tipos } of filas.rows) {
    firmas.set(fn, (nombres ?? []).map((nombre, i) => ({ nombre, tipo: tipos?.[i] ?? 'text' })))
  }

  const oyentes = new Set<() => void>()
  const vigilantes = new Set<(v: boolean) => void>()

  async function rpc<T>(nombre: string, args: Record<string, unknown> = {}): Promise<T> {
    const firma = firmas.get(nombre)
    if (!firma) throw new ErrorJuego('funcion_desconocida', `No existe la función ${nombre}.`)
    const claves = Object.keys(args).filter(k => args[k] !== undefined)
    for (const clave of claves) {
      if (!firma.some(f => f.nombre === clave)) throw new ErrorJuego('argumento_desconocido', `${nombre} no recibe ${clave}.`)
    }
    const partes = claves.map((clave, i) => `${clave} := $${i + 1}::${firma.find(f => f.nombre === clave)!.tipo}`)
    const valores = claves.map(clave => {
      const v = args[clave]
      return v !== null && typeof v === 'object' && !Array.isArray(v) ? JSON.stringify(v) : v
    })
    try {
      const r = await db.query<{ r: T }>(`select public.${nombre}(${partes.join(', ')}) as r`, valores)
      return r.rows[0].r
    } catch (e) {
      const err = e as { message?: string; hint?: string }
      throw new ErrorJuego(err.hint || 'error', err.message || 'Algo salió mal.')
    }
  }

  // Los iframes del simulador se suscriben aquí; si uno se destruyó, se le da de baja en lugar de romper el aviso.
  const avisar = () =>
    oyentes.forEach(f => {
      try {
        f()
      } catch {
        oyentes.delete(f)
      }
    })

  // El reloj y Realtime del demo: cada segundo vence lo vencido y, si algo cambió, avisa a todos.
  const version0 = await db.query<{ version: string }>('select version from app.event where id = 1')
  let ultima = Number(version0.rows[0].version)
  let ocupado = false
  setInterval(() => {
    if (ocupado) return
    ocupado = true
    void (async () => {
      try {
        await db.query('select app.advance_if_due()')
        const v = Number((await db.query<{ version: string }>('select version from app.event where id = 1')).rows[0].version)
        if (v !== ultima) {
          ultima = v
          avisar()
        }
      } catch {
        // la base se está reiniciando
      } finally {
        ocupado = false
      }
    })()
  }, 1000)

  const demo: DemoExpuesto = {
    modo: 'demo',
    rpc,
    suscribir(alCambiar, alEstado) {
      oyentes.add(alCambiar)
      if (alEstado) {
        vigilantes.add(alEstado)
        alEstado(true)
      }
      return () => {
        oyentes.delete(alCambiar)
        if (alEstado) vigilantes.delete(alEstado)
      }
    },
    async sql(consulta, params = []) {
      return (await db.query<Record<string, unknown>>(consulta, params)).rows
    },
    async reiniciar() {
      await db.close()
      await borrarIdb()
      location.reload()
    },
  }
  window.__marielaDemo = demo
  return demo
}
