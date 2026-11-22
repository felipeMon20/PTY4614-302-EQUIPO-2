"""Vistas de la caja de detalle de Catálogos > Ejecutivos para mover la cartera:
reasignar los contratos de un ejecutivo, asignarle un cliente y eliminarlo.
Todo se hace por cliente (razón social). Cada función arma la vista dentro del
PanelCatalogo y avisa con sus señales; quien guarda es CatalogosModule."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QCheckBox, QPushButton, QFrame, QAbstractItemView, QSizePolicy)

from src.services import ejecutivos_service
from src.ui.administracion import estilo as admin_estilo
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.comercial_estilo import ComboTarjeta, _PopupSelector, ubicar_popup_selector

_ESTILO_LISTA = (
    f"QListWidget {{ background: {estilo_com.SUPERFICIE}; border: 1px solid #DCE3EC; border-radius: 10px; outline: none; }}"
    f"QListWidget::item {{ color: {estilo_com.TINTA}; border-bottom: 1px solid #EEF1F6; }}"
    "QListWidget::item:hover { background: #F1F4F9; }"
    "QListWidget::item:selected { background: #E3E8F0; color: #1B2B4E; }"
    "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
    "QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 3px; min-height: 28px; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
_ESTILO_CASILLA = (
    "QCheckBox { spacing: 8px; background: transparent; border: none; }"
    "QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #66748D; border-radius: 5px; background: #FFFFFF; }"
    "QCheckBox::indicator:checked { background-color: #1F6FEB; border-color: #1F6FEB; }")


def _miles(n):
    return f"{int(n):,}".replace(",", ".")


def texto_carga(n):
    return "sin contratos" if n == 0 else f"{_miles(n)} {'contrato' if n == 1 else 'contratos'}"


def _etiqueta(texto, color=None, tam=12, negrita=False):
    lbl = QLabel(texto)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(f"color: {color or estilo_com.TINTA}; font-size: {tam}px; "
                      f"{'font-weight: 800; ' if negrita else ''}background: transparent; border: none;")
    return lbl


def _pildora(texto, apagada=False):
    lbl = QLabel(texto)
    fondo, color = ("#F1F5F9", "#8A97AB") if apagada else ("#E0F2FE", "#0369A1")
    lbl.setStyleSheet(f"background: {fondo}; color: {color}; border: none; border-radius: 10px; "
                      "padding: 0 10px; font-size: 11px; font-weight: 700;")
    lbl.setFixedHeight(20)
    return lbl


def _casilla_con_texto(texto, marcada):
    """Casilla con un texto que se parte en varias líneas (una QCheckBox no lo hace y ensancharía el panel)."""
    contenedor = QWidget()
    lay = QHBoxLayout(contenedor)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    casilla = QCheckBox()
    casilla.setStyleSheet(_ESTILO_CASILLA)
    casilla.setChecked(marcada)
    etiqueta = _etiqueta(texto, tam=11)
    etiqueta.setCursor(Qt.CursorShape.PointingHandCursor)
    etiqueta.mousePressEvent = lambda _e: casilla.toggle()
    lay.addWidget(casilla, 0, Qt.AlignmentFlag.AlignTop)
    lay.addWidget(etiqueta, 1)
    return casilla, contenedor


def _caja_aviso(titulo, texto, rojo=False):
    marco = QFrame()
    marco.setObjectName("avisoCartera")
    borde, fondo = ("#E04848", "#FEF2F2") if rojo else ("#E9C46A", "#FFF8E8")
    marco.setStyleSheet(f"QFrame#avisoCartera {{ background: {fondo}; border: 1px solid {borde}; border-radius: 10px; }}"
                        "QFrame#avisoCartera QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(3)
    lay.addWidget(_etiqueta(titulo, tam=12, negrita=True))
    if texto:
        lay.addWidget(_etiqueta(texto, color=estilo_com.APAGADO, tam=11))
    return marco


def _caja_resumen(texto):
    marco = QFrame()
    marco.setObjectName("resumenCartera")
    marco.setStyleSheet("QFrame#resumenCartera { background: #EEF4FF; border: 1px solid #C9DBFA; border-radius: 10px; }"
                        "QFrame#resumenCartera QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(12, 10, 12, 10)
    etiqueta = _etiqueta(texto, tam=12)
    lay.addWidget(etiqueta)
    return marco, etiqueta


class ComboEjecutivo(ComboTarjeta):
    """Combo de ejecutivos activos en orden alfabético; cada opción lleva a la derecha
    la cantidad de contratos que tiene hoy."""

    def __init__(self, titulo, destinos, parent=None):
        super().__init__(titulo, parent)
        self._destinos = sorted(destinos, key=lambda d: ejecutivos_service.normalizar_nombre(d[0]))
        self.addItem("Elige un ejecutivo activo…")
        for nombre, n in self._destinos:
            self.addItem(f"{nombre}  ·  {texto_carga(n)}")

    def ejecutivo(self):
        indice = self.currentIndex()
        return self._destinos[indice - 1][0] if indice > 0 else ""

    def elegir(self, nombre):
        for i, (n, _c) in enumerate(self._destinos, start=1):
            if n == nombre:
                self.setCurrentIndex(i)
                return

    def showPopup(self):
        if not self._destinos:
            return
        popup = _PopupSelector(self._titulo_popup, self._elegir)
        lista = popup.lista
        for i, (nombre, n) in enumerate(self._destinos, start=1):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, nombre)
            item.setSizeHint(QSize(0, 40))
            lista.addItem(item)
            fila = QWidget()
            fila.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(12, 0, 8, 0)
            lay.addWidget(_etiqueta(nombre, tam=13, negrita=(i == self.currentIndex())), 1)
            lay.addWidget(_pildora(texto_carga(n), apagada=(n == 0)))
            lista.setItemWidget(item, fila)
        lista.setCurrentRow(max(0, self.currentIndex() - 1))
        lista.setFixedHeight(int(min(len(self._destinos) * 42, 340)) + 4)
        popup.setFixedWidth(max(self.width(), 250) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()


def _cancelar(panel):
    return panel._boton("Cancelar", False, panel.volver_detalle.emit)


# ------------------------------------------------------------------ reasignar
def mostrar_reasignar(panel, ejecutivo, cartera, destinos, estilo_combo, estado=None):
    """`destinos`: [(nombre, contratos)] de los ejecutivos activos que pueden recibir.
    `estado` (opcional) restituye lo marcado al volver desde la confirmación."""
    panel._vaciar()
    panel.titulo = ("Detalle", "Reasignar cartera")
    estado = estado or {}
    clientes = cartera['clientes']
    cuerpo = panel._cuerpo
    panel._nombre(f"De {ejecutivo['nombre']}")
    cuerpo.addWidget(admin_estilo.rotulo_campo("Pasar a"))
    combo = ComboEjecutivo("Pasar a", destinos)
    combo.setStyleSheet(estilo_combo)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    if estado.get('destino'):
        combo.elegir(estado['destino'])
    cuerpo.addWidget(combo)

    cuerpo.addWidget(admin_estilo.rotulo_campo(f"Qué pasar ({_miles(len(clientes))} clientes)"))
    fila_buscar = QHBoxLayout()
    fila_buscar.setSpacing(6)
    buscar = QLineEdit()
    buscar.setPlaceholderText("Buscar cliente…")
    buscar.setClearButtonEnabled(True)
    fila_buscar.addWidget(buscar, 1)
    btn_todo, btn_nada = QPushButton("Todo"), QPushButton("Nada")
    for b in (btn_todo, btn_nada):
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedWidth(52)
        b.setStyleSheet(f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid #DCE3EC; "
                        "border-radius: 10px; padding: 0 10px; min-height: 34px; font-size: 12px; font-weight: 700; }"
                        "QPushButton:hover { background: #F1F4F9; }")
        fila_buscar.addWidget(b)
    cuerpo.addLayout(fila_buscar)

    lista = QListWidget()
    lista.setStyleSheet(_ESTILO_LISTA)
    lista.setFixedHeight(250)
    lista.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    marcadas = set(estado.get('clientes', ()))
    casillas = {}
    items = {}
    for c in clientes:
        item = QListWidgetItem()
        extra = c['otros']
        notas = []
        if extra:
            notas.append(f"También tiene camiones: {_miles(extra)} de {c['otro_nombre']}")
        item.setSizeHint(QSize(0, 34 + 15 * len(notas)))
        lista.addItem(item)
        fila = QWidget()
        lay = QVBoxLayout(fila)
        lay.setContentsMargins(8, 4, 10, 4)
        lay.setSpacing(0)
        arriba = QHBoxLayout()
        arriba.setSpacing(10)
        casilla = QCheckBox(c['cliente'])
        casilla.setToolTip(c['cliente'])
        casilla.setStyleSheet(_ESTILO_CASILLA + f"QCheckBox {{ color: {estilo_com.TINTA}; font-size: 12px; font-weight: 600; }}")
        casilla.setChecked(c['cliente'] in marcadas)
        casilla.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        arriba.addWidget(casilla, 1)
        cuenta = _etiqueta(_miles(c['actuales']), tam=12, negrita=True)
        cuenta.setMinimumWidth(34)
        cuenta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        arriba.addWidget(cuenta)
        lay.addLayout(arriba)
        for nota in notas:
            lay.addWidget(_etiqueta(nota, color=estilo_com.APAGADO, tam=10))
        lista.setItemWidget(item, fila)
        casillas[c['cliente']] = casilla
        items[c['cliente']] = item
    cuerpo.addWidget(lista)

    caja, lbl_resumen = _caja_resumen("")
    cuerpo.addWidget(caja)

    def elegidos():
        return [c for c in clientes if casillas[c['cliente']].isChecked()]

    def actualizar(*_):
        sel = elegidos()
        n = sum(c['actuales'] for c in sel)
        destino = combo.ejecutivo()
        if not sel:
            lbl_resumen.setText("Marca los clientes que quieres pasar.")
        elif destino:
            lbl_resumen.setText(f"<b>{_miles(n)} contratos</b> en {_miles(len(sel))} {'cliente' if len(sel) == 1 else 'clientes'} "
                                f"pasarán a <b>{destino}</b>.")
        else:
            lbl_resumen.setText(f"<b>{_miles(n)} contratos</b> en {_miles(len(sel))} {'cliente' if len(sel) == 1 else 'clientes'}. "
                                "Falta elegir a quién.")
        boton_seguir.setEnabled(bool(sel) and n > 0 and bool(destino))

    def filtrar(texto):
        t = texto.strip().lower()
        for nombre, item in items.items():
            item.setHidden(bool(t) and t not in nombre.lower())

    def marcar_todo(valor):
        for nombre, casilla in casillas.items():
            if not items[nombre].isHidden():
                casilla.setChecked(valor)

    def seguir():
        sel = elegidos()
        _mostrar_confirmar(panel, ejecutivo, cartera, destinos, estilo_combo, combo.ejecutivo(), sel,
                           sum(c['actuales'] for c in sel))

    boton_seguir = panel._boton("Revisar y reasignar", True, seguir)
    _cancelar(panel)
    for casilla in casillas.values():
        casilla.toggled.connect(actualizar)
    combo.currentIndexChanged.connect(actualizar)
    buscar.textChanged.connect(filtrar)
    btn_todo.clicked.connect(lambda: marcar_todo(True))
    btn_nada.clicked.connect(lambda: marcar_todo(False))
    actualizar()


def _mostrar_confirmar(panel, ejecutivo, cartera, destinos, estilo_combo, destino, sel, n):
    panel._vaciar()
    panel.titulo = ("Detalle", "Confirmar")
    nombres = [c['cliente'] for c in sel]
    caja, _lbl = _caja_resumen(
        f"<b>{_miles(n)} contratos</b> de {ejecutivo['nombre']} pasarán a <b>{destino}</b> "
        f"({_miles(len(sel))} {'cliente' if len(sel) == 1 else 'clientes'}).")
    panel._cuerpo.addWidget(caja)
    for paso in ("Se hace una copia de seguridad del Registro Maestro.",
                 "Se cambia el campo Ejecutivo en un solo guardado.",
                 "Cada cambio queda en el Historial con el valor anterior."):
        panel._cuerpo.addWidget(_etiqueta(f"•  {paso}", color=estilo_com.TINTA, tam=11))
    panel._nota("Solo cambia el ejecutivo: el estado de cada contrato (por ejemplo Baja Solicitada) queda igual. "
                "Los camiones de otros ejecutivos en esos mismos clientes y los contratos anteriores no se tocan.")
    boton = panel._boton(f"Reasignar {_miles(n)} contratos", True, lambda: _enviar())

    def _enviar():
        boton.setEnabled(False)
        panel.aplicar_reasignar.emit(ejecutivo['id_ejecutivo'], nombres, destino)

    estado = {'destino': destino, 'clientes': nombres}
    panel._boton("Volver", False, lambda: mostrar_reasignar(panel, ejecutivo, cartera, destinos, estilo_combo, estado))


# ------------------------------------------------------------------- asignar
def _texto_duenos(duenos):
    partes = [f"{n} ({_miles(c)})" if len(duenos) > 1 else n for n, c in duenos[:2]]
    return " + ".join(partes) + (" …" if len(duenos) > 2 else "")


def mostrar_asignar(panel, ejecutivo, clientes, contar):
    """`clientes`: lista de cartera_ejecutivos_service.clientes_para_asignar. `contar(cliente, solo)`
    devuelve cuántos contratos pasarían a este ejecutivo."""
    panel._vaciar()
    panel.titulo = ("Detalle", "Asignar cliente")
    cuerpo = panel._cuerpo
    destino = ejecutivo['nombre']
    panel._nombre(f"Para {destino}")
    cuerpo.addWidget(admin_estilo.rotulo_campo(f"Cliente · razón social ({_miles(len(clientes))})"))
    buscar = QLineEdit()
    buscar.setPlaceholderText("Buscar cliente…")
    buscar.setClearButtonEnabled(True)
    cuerpo.addWidget(buscar)
    lista = QListWidget()
    lista.setStyleSheet(_ESTILO_LISTA + "QListWidget::item { padding: 4px 8px; font-size: 12px; font-weight: 600; }")
    lista.setFixedHeight(260)
    lista.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lista.setTextElideMode(Qt.TextElideMode.ElideRight)
    for c in clientes:
        segunda = f"Hoy: {_texto_duenos(c['duenos'])}"
        if len(c['duenos']) == 1:
            segunda += f" · {_miles(c['contratos'])} {'contrato' if c['contratos'] == 1 else 'contratos'}"
        item = QListWidgetItem(f"{c['cliente']}\n{segunda}")
        item.setData(Qt.ItemDataRole.UserRole, c['cliente'])
        item.setToolTip(f"{c['cliente']}\n{segunda}")
        item.setSizeHint(QSize(0, 46))
        lista.addItem(item)
    cuerpo.addWidget(lista)
    chk_solo, fila_solo = _casilla_con_texto("Solo los contratos sin ejecutivo activo (inactivos o Desconocido)", True)
    cuerpo.addWidget(fila_solo)
    caja, lbl_resumen = _caja_resumen("")
    cuerpo.addWidget(caja)
    estado = {'n': 0}

    def cliente_elegido():
        item = lista.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def actualizar(*_):
        cliente = cliente_elegido()
        if cliente is None:
            estado['n'] = 0
            lbl_resumen.setText("Elige el cliente que quieres asignar.")
        else:
            n = estado['n'] = contar(cliente, chk_solo.isChecked())
            if n:
                lbl_resumen.setText(f"<b>{_miles(n)} {'contrato' if n == 1 else 'contratos'}</b> de «{cliente}» pasarán a <b>{destino}</b>.")
            elif chk_solo.isChecked():
                lbl_resumen.setText(f"«{cliente}» no tiene contratos sin ejecutivo activo. Desmarca la casilla para pasar "
                                    "también los de otros ejecutivos.")
            else:
                lbl_resumen.setText(f"«{cliente}» ya es de {destino}.")
        boton.setEnabled(estado['n'] > 0)
        boton.setText(f"Asignar {_miles(estado['n'])} contratos" if estado['n'] else "Asignar")

    def filtrar(texto):
        t = texto.strip().lower()
        for i in range(lista.count()):
            item = lista.item(i)
            item.setHidden(bool(t) and t not in item.data(Qt.ItemDataRole.UserRole).lower())

    def enviar():
        cliente = cliente_elegido()
        if cliente is None or not estado['n']:
            return
        boton.setEnabled(False)
        panel.aplicar_asignar.emit(destino, cliente, chk_solo.isChecked())

    boton = panel._boton("Asignar", True, enviar)
    _cancelar(panel)
    lista.currentItemChanged.connect(actualizar)
    chk_solo.toggled.connect(actualizar)
    buscar.textChanged.connect(filtrar)
    actualizar()


# ------------------------------------------------------------------ eliminar
def mostrar_eliminar(panel, ejecutivo, contratos):
    panel._vaciar()
    panel.titulo = ("Detalle", "Eliminar ejecutivo")
    panel._nombre(ejecutivo['nombre'])
    if contratos:
        panel._cuerpo.addWidget(_caja_aviso(
            f"«{ejecutivo['nombre']}» todavía tiene {_miles(contratos)} contratos",
            "Si aceptas, esos contratos quedarán con el ejecutivo Desconocido. Podrás asignarlos después a otro "
            "ejecutivo, cliente por cliente.", rojo=True))
    else:
        caja, _lbl = _caja_resumen(f"«{ejecutivo['nombre']}» no tiene contratos. Se quita del catálogo.")
        panel._cuerpo.addWidget(caja)
    panel._nota("Se hace una copia de seguridad y los cambios quedan en el Historial. Sus contratos anteriores "
                "(si tiene) también pasan a Desconocido para que no vuelva a aparecer.")

    def enviar():
        boton.setEnabled(False)
        panel.aplicar_eliminar.emit(ejecutivo['id_ejecutivo'])

    boton = panel._boton("Aceptar y eliminar" if contratos else "Eliminar", "peligro", enviar)
    _cancelar(panel)


# --------------------------------------------------------------------- otros
def mostrar_listo(panel, mensaje):
    panel._vaciar()
    panel.titulo = ("Detalle", "Listo")
    caja, _lbl = _caja_resumen(mensaje)
    caja.setStyleSheet("QFrame#resumenCartera { background: #ECFDF3; border: 1px solid #ABEFC6; border-radius: 10px; }"
                       "QFrame#resumenCartera QLabel { background: transparent; border: none; }")
    panel._cuerpo.addWidget(caja)
    panel._boton("Cerrar", True, panel.cerrar_listo.emit)


def mostrar_desconocido(panel, contratos):
    panel._vaciar()
    panel.titulo = ("Detalle", "Sin ejecutivo")
    panel._nombre(ejecutivos_service.NOMBRE_DESCONOCIDO)
    panel._chips((texto_carga(contratos), "#E0F2FE", "#0369A1"), ("Sin ejecutivo", "#FEF3C7", "#92400E"))
    panel._nota("Son contratos que no están a cargo de ningún ejecutivo del directorio (por ejemplo, los de un "
                "ejecutivo que se eliminó, o los que nunca tuvieron uno).")
    panel._nota("Elige los clientes y el ejecutivo activo que los recibe. También puedes abrir un ejecutivo activo y "
                "usar «Asignar un cliente».")
    panel._boton("Reasignar cartera…", True, lambda: panel.abrir_cartera.emit('reasignar', ''))
