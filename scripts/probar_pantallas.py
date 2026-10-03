"""Comprueba que ninguna pantalla se desborda ni deja controles imposibles de tocar: teléfono de 320 px, tableta, escritorio y la tele.

    python scripts/probar_pantallas.py                # compila el build de producción y lo prueba contra el servidor local
    python scripts/probar_pantallas.py --sin-build    # reutiliza dist-sb/
    python scripts/probar_pantallas.py -k tele        # solo las pruebas que coinciden

Las pantallas se arman con nombres largos (de 40 caracteres, con acentos) y 17 invitados, que es lo más apretado que puede pasar
en la fiesta. En cada una se mide, con el navegador:
  · que la página no se desplace de lado (nada más ancho que la pantalla);
  · que ningún control (botón, enlace, campo) mida menos de 44 × 44 px al tacto, salvo enlaces dentro de un párrafo;
  · que el texto legible no baje de 10 px;
  · en la tele, que todo quepa en una sola pantalla, sin desplazarse.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect

from banco import Banco, Sesion, correr, prueba
from probar_juego import (
    TIEMPO,
    elegir_ficha,
    hoja_abierta,
    pestana_admin,
    pestana_juego,
    revelacion_completa,
    telefono,
    ver,
)
from probar_motor import Jugador, Noche

APELLIDOS = ['Hernández-Castañeda', 'de los Ángeles Villarreal', 'Ochoa y Gutiérrez', 'Domínguez del Río', 'Fernández de la Vega', 'Ruiz-Esparza']
NOMBRES_LARGOS = [
    'María Fernanda', 'Juan Pablo', 'Ana Sofía', 'José Emiliano', 'Luz Elena', 'Carlos Alberto', 'Paola Alejandra', 'Diego Sebastián',
    'Valentina Isabel', 'Gabriela Montserrat', 'Andrés Eduardo', 'Regina Guadalupe', 'Rodrigo Ignacio', 'Camila Renata', 'Iker Santiago',
    'Ximena Abigail', 'Mateo Leonardo',
]

# Lo que se mide en cada pantalla. Devuelve los desbordes y los controles que no se pueden tocar bien.
MEDIR = """
([movil, minimoTexto]) => {
  const ancho = document.documentElement.clientWidth
  const alto = window.innerHeight
  const visible = el => {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return false
    for (let n = el; n; n = n.parentElement) {
      const e = getComputedStyle(n)
      if (e.display === 'none' || e.visibility === 'hidden' || parseFloat(e.opacity) === 0) return false
      if (n.hasAttribute('inert') || n.getAttribute('aria-hidden') === 'true' && n.matches('.hoja-capa')) return false
    }
    return !el.closest('.sr-only')
  }
  const nombre = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + [...el.classList].slice(0, 2).map(c => '.' + c).join('')
  // ¿Algún ancestro recorta o desplaza a propósito (una tira de pestañas que se desliza)?
  const recorta = el => { for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (o === 'auto' || o === 'hidden' || o === 'scroll' || o === 'clip') return true } return false }

  const desborde = []
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || recorta(el) || el.closest('[aria-hidden=true]') || getComputedStyle(el).position === 'fixed') continue
    const r = el.getBoundingClientRect()
    if (r.right > ancho + 1 || r.left < -1) desborde.push(`${nombre(el)} (${Math.round(r.left)}→${Math.round(r.right)} de ${ancho})`)
  }
  const toque = []
  for (const el of document.querySelectorAll('button, a[href], input:not([type=hidden]):not([type=checkbox]), select, textarea, summary, [role=button]')) {
    if (!visible(el) || el.disabled) continue
    const r = el.getBoundingClientRect()
    const enLinea = el.matches('a') && el.closest('p, li') && getComputedStyle(el).display === 'inline'
    if (enLinea) continue
    if (Math.min(r.width, r.height) < (movil ? 44 : 32)) toque.push(`${nombre(el)} ${Math.round(r.width)}×${Math.round(r.height)} «${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24)}»`)
  }
  let chico = 0
  const chicos = []
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue
    const px = parseFloat(getComputedStyle(el).fontSize)
    if (px < minimoTexto) { chico++; chicos.push(`${nombre(el)} ${px.toFixed(1)}px`) }
  }
  return {
    ancho, alto,
    scrollX: document.documentElement.scrollWidth - ancho,
    scrollY: document.documentElement.scrollHeight - alto,
    ajuste: parseFloat(document.documentElement.dataset.ajusteTele || '1'),
    desborde: desborde.slice(0, 6), toque: toque.slice(0, 8), chicos: chicos.slice(0, 4),
  }
}
"""


# Nombres como los de una fiesta de verdad: nombre y un apellido.
NOMBRES_NORMALES = [
    'Ana Sofía Ochoa', 'Luis Cárdenas', 'Fernanda Rivas', 'Diego Montes', 'Paola Aguilar', 'Mariana Solís', 'Emiliano Pardo', 'Regina Ibarra',
    'Santiago Lira', 'Valeria Núñez', 'Carlos Ortega', 'Daniela Fuentes', 'Rodrigo Salas', 'Camila Reyes', 'Javier Campos', 'Renata Vidal',
    'Andrés Mora', 'Ximena Castro', 'Bruno Paredes', 'Lucía Herrera',
]


def gente_larga(banco: Banco, cuantos: int = 17, largos: bool = True) -> Noche:
    """Invitados que ya respondieron (la puerta sigue cerrada): con nombres de hasta 40 caracteres y secretos largos, o corrientes."""
    n = Noche(banco.db, 0, lobby=False, aprobar=False)
    for i in range(cuantos):
        if largos:
            nombre = f'{NOMBRES_LARGOS[i % len(NOMBRES_LARGOS)]} {APELLIDOS[i % len(APELLIDOS)]}'[:40]
        else:
            nombre = NOMBRES_NORMALES[i % len(NOMBRES_NORMALES)]
        j = Jugador(n, nombre)
        sobre = NOMBRES_LARGOS[(i + 1) % len(NOMBRES_LARGOS)] if largos else NOMBRES_NORMALES[(i + 1) % len(NOMBRES_NORMALES)]
        j.responder(sobre, 'Secreto largo, con detalles de sobra y una anécdota que nadie pidió. ' * 3 if largos else 'Se sabe todas las canciones de Taylor Swift.')
        n.jugadores.append(j)
    return n


def noche_larga(banco: Banco, cuantos: int = 17) -> Noche:
    """Lo mismo, con la puerta abierta, todos presentes y las cartas repartidas."""
    n = gente_larga(banco, cuantos)
    n.adm('admin_approve_all')
    n.adm('admin_phase', p_phase='lobby')
    for j in n.jugadores:
        j.llegar()
    n.adm('admin_deal')
    return n


class Informe:
    """Junta lo que se mide en cada pantalla y, al final, falla con la lista completa."""

    def __init__(self) -> None:
        self.problemas: list[str] = []
        self.pantallas = 0
        # CAPTURAS=carpeta guarda una foto de cada pantalla medida, para verla con los propios ojos.
        carpeta = os.environ.get('CAPTURAS')
        self.carpeta = Path(carpeta) if carpeta else None
        if self.carpeta:
            self.carpeta.mkdir(parents=True, exist_ok=True)

    def medir(self, s: Sesion, etiqueta: str, *, movil: bool = True, tele: bool = False, minimo_ajuste: float = 0.0) -> None:
        s.pagina.wait_for_timeout(700)  # que terminen las entradas animadas
        m = s.pagina.evaluate(MEDIR, [movil, 9.5 if tele else 10])
        self.pantallas += 1
        if self.carpeta:
            nombre = re.sub(r'[^a-z0-9]+', '-', etiqueta.lower().replace('é', 'e').replace('á', 'a').replace('ó', 'o').replace('í', 'i').replace('ú', 'u')).strip('-')
            s.pagina.screenshot(path=str(self.carpeta / f'{self.pantallas:02d}-{nombre}.png'), full_page=True)
        if m['scrollX'] > 0 or m['desborde']:
            self.problemas.append(f'{etiqueta}: se desborda a los lados en {m["scrollX"]} px · {m["desborde"]}')
        if m['toque']:
            self.problemas.append(f'{etiqueta}: controles chicos → {m["toque"]}')
        if m['chicos']:
            self.problemas.append(f'{etiqueta}: texto demasiado chico → {m["chicos"]}')
        for v in self.axe(s):
            self.problemas.append(f'{etiqueta}: accesibilidad ({v})')
        if tele and m['scrollY'] > 1:
            self.problemas.append(f'{etiqueta}: no cabe en la pantalla, sobran {m["scrollY"]} px de alto (se achicó a {m["ajuste"]:.2f})')
        if tele and m['ajuste'] < minimo_ajuste:
            self.problemas.append(f'{etiqueta}: hubo que achicar la tele a {m["ajuste"]:.2f} de su tamaño, y aquí no debería pasar de {minimo_ajuste:.2f}')
        if tele:
            print(f'      {etiqueta}: tamaño de la tele al {m["ajuste"] * 100:.0f} %')

    def axe(self, s: Sesion) -> list[str]:
        """Si la página trae axe-core (AXE=1, ver probar_accesibilidad.py), lo corre y devuelve las violaciones de WCAG 2.2 AA."""
        if s.pagina.evaluate("typeof window.axe") != 'object':
            return []
        violaciones = s.pagina.evaluate("""async () => {
          const r = await axe.run(document, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
            resultTypes: ['violations'],
          })
          return r.violations.map(v => ({
            id: v.id, impacto: v.impact, nodos: v.nodes.length,
            ejemplos: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' → ' + ((n.any[0] || n.all[0] || n.none[0] || {}).message || '').slice(0, 150)),
          }))
        }""")
        return [f'{v["impacto"]} · {v["id"]} ×{v["nodos"]}: ' + ' | '.join(v['ejemplos']) for v in violaciones]

    def cerrar(self) -> None:
        assert not self.problemas, f'{len(self.problemas)} problema(s) en {self.pantallas} pantallas:\n  · ' + '\n  · '.join(self.problemas)


@prueba('supabase')
def el_teléfono_de_320_no_se_desborda(banco: Banco) -> None:
    """Cada pantalla del jugador, en un iPhone SE (320 px), con nombres largos y 17 invitados."""
    n = noche_larga(banco)
    asesino = n.asesinos()[0]
    inocente, acusado, victima = n.inocentes()[:3]
    inf = Informe()

    s = telefono(banco, inocente, perfil='iPhone SE')
    inf.medir(s, 'ronda (discusión)')
    pestana_juego(s, 'Mi carta')
    inf.medir(s, 'mi carta boca abajo')
    pestana_juego(s, 'Bitácora')
    inf.medir(s, 'bitácora vacía')
    pestana_juego(s, 'Noche')

    n.a_votacion()
    ver(s, '.j-votacion > .j-etiqueta', 'Votación', seg=9)
    inf.medir(s, 'votación (16 fichas)')
    elegir_ficha(s, acusado.nombre, 'Votar por')
    inf.medir(s, 'votación con una ficha elegida')
    s.tocar('#j-votar')
    expect(hoja_abierta(s)).to_contain_text(f'¿Votas por {acusado.nombre}?')
    s.pagina.wait_for_timeout(500)
    inf.medir(s, 'confirmar voto (hoja)')
    s.tocar('#j-confirmar-voto')
    ver(s, '.j-sellado .j-titulo', 'Voto sellado.')
    inf.medir(s, 'voto sellado')

    sa = telefono(banco, asesino, perfil='iPhone SE')
    for v in n.vivos():
        if v not in (inocente, acusado) and v is not asesino:
            v.votar(acusado)
    acusado.votar(victima)
    asesino.votar(acusado)
    ver(sa, '.j-golpe .j-titulo', 'Fallaron. Ahora te toca a ti.', seg=9)
    revelacion_completa(s, acierto=False)
    inf.medir(s, 'veredicto de un fallo (inocente)')
    inf.medir(sa, 'veredicto de un fallo (asesino, con selector)')
    elegir_ficha(sa, victima.nombre, 'Elegir a')
    sa.tocar('#j-elegir-victima')
    expect(hoja_abierta(sa)).to_contain_text(f'¿Será {victima.nombre}?')
    sa.pagina.wait_for_timeout(500)
    inf.medir(sa, 'confirmar víctima (hoja)')
    sa.tocar('#j-confirmar-victima')

    sv = telefono(banco, victima, perfil='iPhone SE')
    ver(sv, '.j-muerte .j-titulo', 'Has muerto.', seg=9)
    inf.medir(sv, 'has muerto (a pantalla completa)')
    sv.tocar('.j-muerte .secundario')
    inf.medir(sv, 'ronda de un muerto')
    pestana_juego(s, 'Bitácora')
    ver(s, '.j-bitacora-lista li', 'Acusaron a', seg=9)
    inf.medir(s, 'bitácora con una ronda')
    pestana_juego(s, 'Mi carta')
    s.pagina.evaluate("document.querySelector('#mi-carta').scrollIntoView()")
    caja = s.pagina.locator('#mi-carta').bounding_box()
    s.pagina.mouse.move(caja['x'] + caja['width'] / 2, caja['y'] + caja['height'] / 2)
    s.pagina.mouse.down()
    ver(s, '#mi-carta-nota', 'Eres inocente.')
    inf.medir(s, 'mi carta boca arriba')
    s.pagina.mouse.up()

    pestana_juego(s, 'Noche')
    n.a_votacion()
    for v in n.vivos():
        v.votar(asesino if v is not asesino else n.inocentes()[0])
    ver(s, '.j-fin-partida .j-titulo', 'La atraparon.', seg=9)
    revelacion_completa(s, acierto=True)
    inf.medir(s, 'fin de partida (atraparon al asesino)')

    n.adm('admin_control', p_action='end_night')
    ver(s, '.fin-noche .j-titulo', 'Se acabó la noche.', seg=9)
    inf.medir(s, 'fin de la noche con premios')
    inf.cerrar()


@prueba('supabase')
def la_antesala_y_la_puerta_caben(banco: Banco) -> None:
    """La antesala con los 17 nombres largos, con el código de la puerta, con un error y ya presente; en tres tamaños de pantalla."""
    n = gente_larga(banco)
    n.config(door_code='LUNA')
    n.adm('admin_phase', p_phase='lobby')
    for j in n.jugadores[1:]:
        j.llegar('LUNA')
    inf = Informe()
    s = telefono(banco, n.jugadores[0], perfil='iPhone SE')
    inf.medir(s, 'antesala, sin haber llegado (con código de puerta)')
    s.pagina.fill('#codigo-puerta', 'XXXX')
    s.tocar('#j-estoy-aqui')
    ver(s, '#codigo-error', 'código')
    inf.medir(s, 'antesala con el error del código')
    s.pagina.fill('#codigo-puerta', 'LUNA')
    s.tocar('#j-estoy-aqui')
    ver(s, '.j-contador', '17 de 17 ya llegaron')
    inf.medir(s, 'antesala, ya con 17 presentes')
    inf.medir(telefono(banco, n.jugadores[1], perfil='Pixel 7'), 'antesala en Pixel 7')
    inf.medir(telefono(banco, n.jugadores[2], perfil='iPad Mini'), 'antesala en iPad Mini')
    s.sin_errores(rechazos=True)
    inf.cerrar()


@prueba('supabase')
def el_admin_cabe_en_el_teléfono_y_en_el_escritorio(banco: Banco) -> None:
    """El panel de admin en 375 px y en 1280 px, pestaña por pestaña, con 17 invitados de nombres largos y secretos largos."""
    n = noche_larga(banco, 17)
    n.adm('admin_control', p_action='end_night')
    n.adm('admin_control', p_action='reopen')
    inf = Informe()
    for perfil, movil in (('iPhone 15', True), ('escritorio', False)):
        s = banco.sesion(perfil)
        s.pagina.set_default_timeout(TIEMPO)
        s.ir('admin', esperar_a='#pin')
        inf.medir(s, f'admin · entrada ({perfil})', movil=movil)
        s.pagina.fill('#pin', banco.pin)
        s.pagina.keyboard.press('Enter')
        s.pagina.wait_for_selector('.admin')
        for pestana in ('Noche', 'Invitados', 'Secretos', 'Ajustes'):
            pestana_admin(s, pestana)
            inf.medir(s, f'admin · {pestana} ({perfil})', movil=movil)
        s.pagina.locator('.ad-pestanas button', has_text=re.compile('^Noche')).click()
    inf.cerrar()


def recorrer_tele(banco: Banco, inf: Informe, *, cuantos: int, largos: bool, minimo_ajuste: float, tamanos=((1920, 1080), (1280, 720))) -> None:
    """Lleva la noche por todas las escenas de la tele y mide cada una. Las de un tamaño de pantalla van con una noche nueva."""
    for ancho, alto in tamanos:
        marca = f'{ancho}×{alto}'
        n = gente_larga(banco, cuantos, largos)
        llave = n.adm('admin_state')['event']['tv_key']
        t = banco.sesion('tele')
        t.pagina.set_default_timeout(TIEMPO)
        t.pagina.set_viewport_size({'width': ancho, 'height': alto})
        t.ir(f'tv#k={llave}', esperar_a='.tv-recibidor')
        ajuste = dict(movil=False, tele=True, minimo_ajuste=minimo_ajuste)
        inf.medir(t, f'tele · antes de abrir la puerta ({marca})', **ajuste)

        n.config(door_code='LUNA')
        n.adm('admin_approve_all')
        n.adm('admin_phase', p_phase='lobby')
        for j in n.jugadores:
            j.llegar('LUNA')
        ver(t, '.tv-llegados', f'{cuantos} de {cuantos}', seg=9)
        inf.medir(t, f'tele · puerta abierta, {cuantos} presentes ({marca})', **ajuste)

        n.adm('admin_deal')
        ver(t, '.tv-ronda .j-etiqueta', 'Ronda 1', seg=9)
        inf.medir(t, f'tele · ronda ({marca})', **ajuste)

        n.a_votacion()
        ver(t, '.tv-votacion .j-etiqueta', 'Votación', seg=9)
        inf.medir(t, f'tele · votación ({marca})', **ajuste)

        acusado, victima = n.inocentes()[:2]
        for v in n.vivos():
            v.votar(acusado if v is not acusado else victima)
        ver(t, '.tv-veredicto .j-etiqueta', 'Veredicto', seg=9)
        revelacion_completa(t, acierto=False)
        inf.medir(t, f'tele · veredicto de un fallo ({marca})', **ajuste)

        n.asesinos()[0].matar(victima)
        ver(t, '.tv-muerte', 'ha muerto', seg=9)
        inf.medir(t, f'tele · anuncio de una muerte ({marca})', **ajuste)
        expect(t.pagina.locator('.tv-muerte')).to_have_count(0, timeout=15_000)  # el anuncio dura unos segundos

        n.a_votacion()
        asesino = n.asesinos()[0]
        for v in n.vivos():
            v.votar(asesino if v is not asesino else next(x for x in n.vivos() if x is not v))
        ver(t, '.tv-veredicto .tv-gran-titulo', 'La atraparon.', seg=9)
        revelacion_completa(t, acierto=True)
        inf.medir(t, f'tele · fin de partida ({marca})', **ajuste)

        n.adm('admin_control', p_action='end_night')
        ver(t, '.tv-cierre .tv-gran-titulo', 'Se acabó la noche', seg=9)
        inf.medir(t, f'tele · cierre con premios ({marca})', **ajuste)
        t.sin_errores()


@prueba('supabase')
def la_tele_cabe_aunque_los_nombres_sean_larguisimos(banco: Banco) -> None:
    """Lo más apretado que puede pasar: 17 nombres de 40 caracteres. La tele se achica lo necesario, pero nunca se desplaza ni se corta."""
    inf = Informe()
    recorrer_tele(banco, inf, cuantos=17, largos=True, minimo_ajuste=0.55, tamanos=((1920, 1080),))
    inf.cerrar()


@prueba('supabase')
def la_tele_de_una_fiesta_normal_apenas_se_achica(banco: Banco) -> None:
    """Veinte invitados con nombre y apellido: la tele cabe entera casi a su tamaño natural (que se lea desde el sillón)."""
    inf = Informe()
    recorrer_tele(banco, inf, cuantos=20, largos=False, minimo_ajuste=0.75)
    inf.cerrar()


@prueba('supabase')
def la_invitacion_cabe_y_pasa_axe(banco: Banco) -> None:
    """La invitación (sobre cerrado, abierta, formulario con errores, aceptada) en un teléfono de 320 px y en escritorio."""
    inf = Informe()
    for perfil, movil in (('iPhone SE', True), ('escritorio', False)):
        s = banco.sesion(perfil)
        s.pagina.set_default_timeout(TIEMPO)
        s.ir()
        inf.medir(s, f'invitación · sobre cerrado ({perfil})', movil=movil)
        s.tocar('#sello')
        s.pagina.wait_for_selector('.escena.abierta', timeout=8000)
        s.recorrer()
        inf.medir(s, f'invitación · abierta ({perfil})', movil=movil)
        s.pagina.locator('#form').scroll_into_view_if_needed()
        s.tocar('#form button[type=submit]')
        s.pagina.wait_for_selector('#e-nombre:not(:empty)')
        inf.medir(s, f'invitación · formulario con errores ({perfil})', movil=movil)
        s.pagina.fill('#nombre', f'Ana {perfil}')
        s.pagina.fill('#sobre-quien', 'Mariela')
        s.pagina.fill('#secreto', 'Le tiene miedo a los pavos reales.')
        s.tocar('#form button[type=submit]')
        s.pagina.wait_for_selector('#aceptado:not([hidden])', timeout=25000)
        inf.medir(s, f'invitación · aceptada ({perfil})', movil=movil)
        s.sin_errores(rechazos=True)
    inf.cerrar()


@prueba('supabase')
def la_tele_achicada_no_parpadea(banco: Banco) -> None:
    """Cuando la tele se achica para caber, el tamaño se queda quieto: ni se mueve ni "respira" con cada latido de 500 ms."""
    n = gente_larga(banco, 17, True)
    llave = n.adm('admin_state')['event']['tv_key']
    n.config(door_code='LUNA')
    n.adm('admin_approve_all')
    n.adm('admin_phase', p_phase='lobby')
    for j in n.jugadores:
        j.llegar('LUNA')
    t = banco.sesion('tele')
    t.pagina.set_default_timeout(TIEMPO)
    t.ir(f'tv#k={llave}', esperar_a='.tv-recibidor')
    ver(t, '.tv-llegados', '17 de 17', seg=9)
    t.pagina.wait_for_timeout(2500)  # que terminen las entradas
    muestras = t.pagina.evaluate("""async () => {
      const salida = []
      for (let i = 0; i < 40; i++) {
        const r = document.querySelector('.tv-gran-titulo').getBoundingClientRect()
        salida.push({ y: r.top, alto: r.height, fuente: parseFloat(document.documentElement.style.fontSize) })
        await new Promise(res => setTimeout(res, 100))
      }
      return salida
    }""")
    assert muestras[0]['fuente'] < 27, f'esta escena debía achicarse (la base a 1080p es 28 px): {muestras[0]["fuente"]}'
    for campo in ('y', 'alto', 'fuente'):
        valores = [m[campo] for m in muestras]
        assert max(valores) - min(valores) < 0.5, f'{campo} se movió durante 4 s: {min(valores):.2f} → {max(valores):.2f}'
    t.sin_errores()


if __name__ == '__main__':
    correr(__doc__ or '', epilogo_modos=('supabase',))
