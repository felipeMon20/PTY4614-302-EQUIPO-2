"""Combo de selección múltiple con el mismo look que ComboTarjeta: la lista se abre en la
tarjeta flotante y cada clic marca o desmarca una opción sin cerrarla. Se usa para los
complementos del plan (CIV, SZ...)."""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QListWidgetItem

from src.ui.compartido.comercial_estilo import ComboTarjeta, _PopupSelector, ubicar_popup_selector

_QSS_LISTA = (
    "QListWidget::indicator { width: 16px; height: 16px; border: 2px solid #66748D; border-radius: 5px; "
    "background: #FFFFFF; }"
    "QListWidget::indicator:checked { background-color: #1F6FEB; border-color: #1F6FEB; }"
    "QListWidget::indicator:disabled { border-color: #C5CCDA; background: #F3F5F9; }")


class _PopupMultiple(_PopupSelector):
    """La lista no se cierra al marcar: el clic alterna la opción."""

    def __init__(self, titulo, al_alternar, pie):
        super().__init__(titulo, al_alternar)
        self._texto_pie = pie
        self.lista.setStyleSheet(self.lista.styleSheet() + _QSS_LISTA)

    def preparar(self):
        super().preparar()
        self.pie.setText(self._texto_pie)

    def _clic(self, item):
        if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        marcado = self._al_elegir(item.data(Qt.ItemDataRole.UserRole))
        item.setCheckState(Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)


class ComboMultiple(ComboTarjeta):
    """`opciones` es una lista de (código, nombre) o una función que la devuelve: con función, la lista
    se vuelve a pedir cada vez que se abre, así un complemento agregado en Catálogos aparece sin reiniciar.
    El texto del combo resume lo marcado ("CIV, SZ") y `seleccion()` devuelve los códigos en el orden de `opciones`."""

    cambiado = pyqtSignal()

    def __init__(self, titulo, opciones=(), texto_vacio="Sin complementos", parent=None):
        super().__init__(titulo, parent)
        self._texto_vacio = texto_vacio
        self._proveedor = opciones if callable(opciones) else None
        self._opciones = []
        self._marcados = set()
        self._bloqueados = {}
        self.addItem(texto_vacio)
        self.set_opciones(self._proveedor() if self._proveedor else opciones)

    def set_opciones(self, opciones):
        self._opciones = [(str(c).upper(), n) for c, n in opciones]
        codigos = {c for c, _n in self._opciones}
        self._marcados &= codigos
        self._bloqueados = {c: m for c, m in self._bloqueados.items() if c in codigos}
        self._refrescar_texto()

    def seleccion(self):
        return [c for c, _n in self._opciones if c in self._marcados]

    def set_seleccion(self, codigos, emitir=True):
        nuevos = {str(c).upper() for c in codigos} & {c for c, _n in self._opciones}
        nuevos -= set(self._bloqueados)
        if nuevos == self._marcados:
            return
        self._marcados = nuevos
        self._refrescar_texto()
        if emitir:
            self.cambiado.emit()

    def bloquear(self, codigo, bloqueado, motivo=""):
        """Deshabilita una opción (y la desmarca) sin afectar a las demás."""
        codigo = str(codigo).upper()
        if bloqueado:
            self._bloqueados[codigo] = motivo
            if codigo in self._marcados:
                self._marcados.discard(codigo)
                self._refrescar_texto()
                self.cambiado.emit()
        else:
            self._bloqueados.pop(codigo, None)

    def _refrescar_texto(self):
        marcados = self.seleccion()
        self.setItemText(0, ", ".join(marcados) if marcados else self._texto_vacio)
        nombres = [n for c, n in self._opciones if c in self._marcados]
        self.setToolTip(", ".join(nombres))

    def _alternar(self, codigo):
        if codigo in self._bloqueados:
            return codigo in self._marcados
        if codigo in self._marcados:
            self._marcados.discard(codigo)
        else:
            self._marcados.add(codigo)
        self._refrescar_texto()
        self.cambiado.emit()
        return codigo in self._marcados

    def showPopup(self):
        if self._proveedor is not None:
            try:
                self.set_opciones(self._proveedor())
            except Exception:
                pass
        if not self._opciones:
            return
        popup = _PopupMultiple(self._titulo_popup, self._alternar, "Elige uno o más")
        for codigo, nombre in self._opciones:
            item = QListWidgetItem(nombre if nombre == codigo else f"{nombre} ({codigo})")
            item.setData(Qt.ItemDataRole.UserRole, codigo)
            bloqueado = codigo in self._bloqueados
            flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
            if not bloqueado:
                flags |= Qt.ItemFlag.ItemIsEnabled
            else:
                item.setToolTip(self._bloqueados[codigo])
            item.setFlags(flags)
            item.setCheckState(Qt.CheckState.Checked if codigo in self._marcados else Qt.CheckState.Unchecked)
            item.setSizeHint(QSize(0, 38))
            popup.lista.addItem(item)
        popup.lista.setFixedHeight(int(min(len(self._opciones) * 40, 360)) + 4)
        popup.setFixedWidth(max(self.width(), 230) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()
