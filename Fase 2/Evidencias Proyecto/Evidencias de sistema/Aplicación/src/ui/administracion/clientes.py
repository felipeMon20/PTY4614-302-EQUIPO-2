"""Administración de clientes: un cliente por RUT (sin RUT utilizable, por razón
social). Al seleccionar un cliente se abre un panel a la derecha, como las
acciones rápidas de Comercial, donde se cambia su razón social en todas sus
unidades, el RUT de una de sus razones y su CDB comercial cuando tiene más de
uno; desde el formulario de una unidad ese nombre queda bloqueado."""
import unicodedata

import pandas as pd
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QItemSelectionModel, QEvent
from PyQt6.QtGui import QRegularExpressionValidator, QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
                             QMessageBox, QComboBox, QCheckBox, QStackedWidget, QFileDialog, QSizePolicy, QScrollArea)

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.services import comercial_services
from src.theme.colors import WARNING
from src.theme.theme_manager import ThemeManager
from src.ui.administracion import estilo as admin_estilo
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.compartido.formulario_unidad import GuardadoUnidadesMixin
from src.ui.ingresos.base import ModeloTablaIngresos

SUBTABS = ("Todos", "Varias razones", "Varios CDB", "Sin RUT", "Varios RUT")
TITULOS_FILTRO = ("Todos los clientes", "Clientes con varias razones", "Clientes con varios CDB", "Clientes sin RUT",
                   "Razones sociales con más de un RUT")
COL_CDB_COMERCIAL = "CDB COMERCIAL"
COL_CDB_FLOTA = "CDB FLOTA"
COLUMNAS = ["RUT", "RAZÓN SOCIAL", "OTRAS RAZONES", COL_CDB_COMERCIAL, COL_CDB_FLOTA, "UNIDADES"]


def mascara_varios_rut(df):
    """Clientes con RUT cuya razón social (sin distinguir mayúsculas ni espacios) aparece con otro RUT."""
    razon = df["RAZÓN SOCIAL"].astype(str).str.upper().str.split().str.join(" ")
    con_rut = ~df["CLAVE"].str.startswith("RS:")
    ruts_por_razon = df[con_rut].groupby(razon[con_rut])["CLAVE"].transform("nunique")
    return con_rut & (ruts_por_razon.reindex(df.index).fillna(0) > 1)


def armar_resumen(data_manager):
    """(clientes con sus CDB en texto, CDB comercial por cliente, CDB flota por cliente)."""
    return armar_resumen_de(data_manager.get_comercial_df(), data_manager.get_contratos_actuales_df())


def armar_resumen_de(comercial, actuales):
    """Lo mismo que `armar_resumen` a partir de los DataFrames (sin tocar el DataManager: sirve en un hilo)."""
    df = comercial_services.resumen_clientes(comercial)
    cdbs = comercial_services.cdbs_por_cliente(actuales)
    cdbs_flota = comercial_services.cdbs_por_cliente(actuales, COL_CDB_FLOTA)
    df[COL_CDB_COMERCIAL] = df["CLAVE"].map(lambda clave: ', '.join(c for c, _n in cdbs.get(clave, []) if c != '-') or '-')
    df[COL_CDB_FLOTA] = df["CLAVE"].map(lambda clave: ', '.join(c for c, _n in cdbs_flota.get(clave, []) if c != '-') or '-')
    return df, cdbs, cdbs_flota


def mascaras_casos(df):
    """Máscaras de los cuatro filtros con casos por revisar: varias razones, varios CDB, sin RUT y varios RUT."""
    if df.empty:
        vacia = pd.Series(False, index=df.index)
        return vacia, vacia, vacia, vacia
    return (df["OTRAS RAZONES"] != "-", df[COL_CDB_COMERCIAL].str.contains(',', regex=False),
            df["CLAVE"].str.startswith("RS:"), mascara_varios_rut(df))


def _sin_formato(texto):
    """Texto sin mayúsculas, tildes ni espacios repetidos, para comparar nombres."""
    normal = unicodedata.normalize('NFKD', " ".join(str(texto).split()))
    return "".join(c for c in normal if not unicodedata.combining(c)).upper()


def _unidades(n):
    return f"{n} {'unidad' if n == 1 else 'unidades'}"


_QSS_CAMPOS = (
    f"QLineEdit, QComboBox {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid #DCE3EC; "
    f"border-radius: 10px; padding: 0 12px; min-height: 34px; color: {estilo_com.TINTA}; font-size: 12px; font-weight: 600; }}"
    "QLineEdit:focus, QComboBox:focus { border: 1px solid #1B2B4E; }")


_QSS_COMBO_EDITABLE = (
    f"QComboBox {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid #DCE3EC; border-radius: 10px; "
    f"padding: 0 0 0 12px; min-height: 34px; color: {estilo_com.TINTA}; font-size: 12px; font-weight: 600; combobox-popup: 0; }}"
    "QComboBox:hover { border: 1px solid #B9C6DA; }"
    "QComboBox:focus, QComboBox:on { border: 1px solid #1B2B4E; }"
    "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; "
    "border-left: 1px solid #E3E8F0; border-top-right-radius: 9px; border-bottom-right-radius: 9px; background-color: #F7F8FC; }"
    f"QComboBox::down-arrow {{ image: url({_COMBO_CHEVRON_PATH}); width: 11px; height: 11px; }}"
    "QComboBox QLineEdit { border: none; background: transparent; padding: 0; min-height: 0; "
    "font-size: 12px; font-weight: 600; }")


def _sin_ensanchar(combo):
    """El ancho del combo no depende de su opción más larga: así un nombre largo no estira la caja."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(1)
    combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(0)


def _combo_editable(placeholder, titulo):
    """Lista desplegable en que también se puede escribir un valor nuevo (sin agregarlo a la lista)."""
    combo = estilo_com.ComboTarjeta(titulo)
    _sin_ensanchar(combo)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setStyleSheet(_QSS_COMBO_EDITABLE)
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.setCurrentIndex(-1)
    return combo


def _combo_selector(titulo):
    """Lista desplegable sin escritura, con el mismo diseño que los combos editables."""
    combo = estilo_com.ComboTarjeta(titulo)
    _sin_ensanchar(combo)
    combo.setStyleSheet(_QSS_COMBO_EDITABLE)
    return combo


def _chip(fondo, texto):
    lbl = QLabel("")
    lbl.setStyleSheet(f"background: {fondo}; color: {texto}; border: none; border-radius: 11px; "
                      "padding: 3px 11px; min-height: 18px; font-size: 11px; font-weight: 700;")
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


class PanelCliente(QWidget):
    """Caja derecha permanente con la edición del cliente seleccionado."""

    guardar_cliente = pyqtSignal(str, str, str, object, str)
    guardar_grupo = pyqtSignal(list, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_QSS_CAMPOS)
        self.cliente = None
        self._solo_cdb = False
        self._razones = []
        self._otros = {}
        self._cdbs = []
        self._cdbs_flota = set()
        self._sugerido = None
        self._cdb_ajenos = {}
        marco = QVBoxLayout(self)
        marco.setContentsMargins(0, 0, 0, 0)
        marco.setSpacing(0)
        self.pagina = QStackedWidget()
        marco.addWidget(self.pagina, 1)
        self.pagina.addWidget(self._pagina_vacia())
        contenido = QWidget()
        contenido.setObjectName("contenidoCliente")
        contenido.setStyleSheet("QWidget#contenidoCliente { background: transparent; }")
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.Shape.NoFrame)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        desplazable.setWidget(contenido)
        self.pagina.addWidget(desplazable)
        self.pagina.addWidget(self._pagina_grupo())
        self._habilitado = {"rut": False, "cdb": False}
        self._cdb_por_razon = {}
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.lbl_nombre = admin_estilo.nombre_detalle()
        lay.addWidget(self.lbl_nombre)
        self.fila_chips = QHBoxLayout()
        self.fila_chips.setSpacing(6)
        self.chip_rut = QLabel("")
        self.chip_unidades = QLabel("")
        self.chip_razones = QLabel("")
        self.chip_cdb = QLabel("")
        self.chip_rut.setStyleSheet(_chip("#E3E8F0", "#1B2B4E").styleSheet())
        self.chip_unidades.setStyleSheet(_chip("#E0F2FE", "#0369A1").styleSheet())
        self.chip_razones.setStyleSheet(_chip("#FEE2E2", "#B91C1C").styleSheet())
        self.chip_cdb.setStyleSheet(_chip("#FEE2E2", "#B91C1C").styleSheet())
        fila_rut = QHBoxLayout()
        fila_rut.addWidget(self.chip_rut)
        fila_rut.addStretch()
        lay.addLayout(fila_rut)
        for chip in (self.chip_unidades, self.chip_razones, self.chip_cdb):
            self.fila_chips.addWidget(chip)
        self.fila_chips.addStretch()
        lay.addLayout(self.fila_chips)

        pag_razon = QWidget()
        lr = QVBoxLayout(pag_razon)
        lr.setContentsMargins(0, 4, 0, 0)
        lr.setSpacing(6)
        lr.addWidget(self._titulo_seccion("Razón social"))
        self.cmb_razon = _combo_selector("Razones sociales del cliente")
        self.cmb_razon.currentIndexChanged.connect(self._al_elegir_razon)
        lr.addWidget(self.cmb_razon)
        self.lbl_aviso_razon = self._aviso(estilo_com.APAGADO)
        lr.addWidget(self.lbl_aviso_razon)
        lay.addWidget(pag_razon)
        self._pag_razon = pag_razon

        pag_rut = QWidget()
        lt = QVBoxLayout(pag_rut)
        lt.setContentsMargins(0, 4, 0, 0)
        lt.setSpacing(6)
        lt.addWidget(self._titulo_seccion("RUT"))
        self.txt_rut = QLineEdit()
        self.txt_rut.setPlaceholderText("Sin puntos ni guion. Ej: 763764309")
        self.txt_rut.textChanged.connect(self._actualizar_rut)
        lt.addWidget(self.txt_rut)
        self.chk_nombre = QCheckBox("")
        self.chk_nombre.setStyleSheet("background: transparent;")
        self.chk_nombre.hide()
        lt.addWidget(self.chk_nombre)
        self.lbl_aviso_rut = self._aviso(estilo_com.APAGADO)
        lt.addWidget(self.lbl_aviso_rut)
        lay.addWidget(pag_rut)
        self._pag_rut = pag_rut

        pag_cdb = QWidget()
        lc = QVBoxLayout(pag_cdb)
        lc.setContentsMargins(0, 4, 0, 0)
        lc.setSpacing(6)
        lc.addWidget(self._titulo_seccion("CDB comercial"))
        self._txt_cdb_simple = QLineEdit()
        self._txt_cdb_simple.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,10}")))
        self._txt_cdb_simple.setPlaceholderText("Hasta 10 dígitos")
        self._txt_cdb_simple.textChanged.connect(self._actualizar_cdb)
        lc.addWidget(self._txt_cdb_simple)
        # En el filtro Varios CDB: lista con los CDB del cliente, editable; el elegido queda en todas sus unidades
        self.cmb_cdb_modo = _combo_editable("Elige uno de los CDB del cliente o escribe otro", "CDB del cliente")
        self.cmb_cdb_modo.lineEdit().setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,10}")))
        self.cmb_cdb_modo.lineEdit().textChanged.connect(self._actualizar_cdb)
        self.cmb_cdb_modo.currentIndexChanged.connect(self._al_elegir_cdb_de_lista)
        self.cmb_cdb_modo.hide()
        lc.addWidget(self.cmb_cdb_modo)
        self.lbl_aviso_cdb = self._aviso(estilo_com.APAGADO)
        self.lbl_ajeno_cdb = self._aviso(WARNING, negrita=True)
        lc.addWidget(self.lbl_aviso_cdb)
        lc.addWidget(self.lbl_ajeno_cdb)
        lay.addWidget(pag_cdb)

        lay.addStretch()

        self._pie, lay_pie = admin_estilo.crear_pie()
        self.btn_cliente = self._boton_guardar("Guardar cambios")
        self.btn_cliente.setEnabled(False)
        self.btn_cliente.clicked.connect(self._on_guardar_cliente)
        lay_pie.addWidget(self.btn_cliente)
        marco.addWidget(self._pie)
        self.limpiar()

    def _pagina_vacia(self):
        pagina, mostrar = admin_estilo.estado_vacio()
        mostrar('fa5s.user-edit', "Selecciona un cliente",
                "Haz clic en una fila para corregir su razón social, su RUT o su CDB comercial.")
        return pagina

    def _pagina_grupo(self):
        """Edición de varios clientes a la vez (misma razón social con distinto RUT o CDB)."""
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.lbl_g_nombre = QLabel("")
        self.lbl_g_nombre.setWordWrap(True)
        self.lbl_g_nombre.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: 800; background: transparent;")
        lay.addWidget(self.lbl_g_nombre)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        self.chip_g_clientes = QLabel("")
        self.chip_g_unidades = QLabel("")
        self.chip_g_clientes.setStyleSheet(_chip("#FEE2E2", "#B91C1C").styleSheet())
        self.chip_g_unidades.setStyleSheet(_chip("#E0F2FE", "#0369A1").styleSheet())
        fila.addWidget(self.chip_g_clientes)
        fila.addWidget(self.chip_g_unidades)
        fila.addStretch()
        lay.addLayout(fila)
        self.lbl_g_lista = self._aviso(estilo_com.APAGADO)
        lay.addWidget(self.lbl_g_lista)
        lay.addWidget(self._titulo_seccion("Razón social"))
        self.txt_g_razon = QLineEdit()
        self.txt_g_razon.textChanged.connect(self._actualizar_grupo)
        lay.addWidget(self.txt_g_razon)
        lay.addWidget(self._titulo_seccion("RUT nuevo (opcional)"))
        self.cmb_g_rut = _combo_editable("Elige uno o escribe uno nuevo. Vacío = no cambiar", "RUT de estos clientes")
        self.txt_g_rut = self.cmb_g_rut.lineEdit()
        self.txt_g_rut.textChanged.connect(self._actualizar_grupo)
        lay.addWidget(self.cmb_g_rut)
        lay.addWidget(self._titulo_seccion("CDB comercial nuevo (opcional)"))
        self.cmb_g_cdb = _combo_editable("Elige uno o escribe uno nuevo (hasta 10 dígitos)", "CDB de estos clientes")
        self.txt_g_cdb = self.cmb_g_cdb.lineEdit()
        self.txt_g_cdb.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,10}")))
        self.txt_g_cdb.textChanged.connect(self._actualizar_grupo)
        lay.addWidget(self.cmb_g_cdb)
        self.lbl_g_aviso = self._aviso(estilo_com.APAGADO)
        self.lbl_g_alerta = self._aviso(WARNING, negrita=True)
        lay.addWidget(self.lbl_g_aviso)
        lay.addWidget(self.lbl_g_alerta)
        lay.addStretch()
        self.btn_grupo = self._boton_guardar("Guardar cambios del grupo")
        self.btn_grupo.clicked.connect(self._on_guardar_grupo)
        lay.addWidget(self.btn_grupo)
        self._grupo, self._grupo_otros, self._grupo_cdb_ajenos = [], {}, {}
        return pagina

    def set_grupo(self, clientes, otros_clientes, cdb_ajenos):
        """Carga varios clientes seleccionados para editarlos juntos."""
        self.cliente = None
        self._grupo = list(clientes)
        self._grupo_otros = {c["CLAVE"]: c for c in otros_clientes}
        self._grupo_cdb_ajenos = cdb_ajenos or {}
        total = sum(int(c["UNIDADES"]) for c in clientes)
        por_razon = {}
        for c in clientes:
            por_razon[c["RAZÓN SOCIAL"]] = por_razon.get(c["RAZÓN SOCIAL"], 0) + int(c["UNIDADES"])
        comun = max(por_razon, key=por_razon.get)
        iguales = len({_sin_formato(r) for r in por_razon}) == 1
        self.lbl_g_nombre.setText(comun if iguales else f"{len(clientes)} clientes seleccionados")
        self.chip_g_clientes.setText(f"{len(clientes)} clientes")
        self.chip_g_unidades.setText(_unidades(total))
        self.lbl_g_lista.setText("\n".join(
            f"RUT {c['RUT']} · {_unidades(int(c['UNIDADES']))} · CDB {c[COL_CDB_COMERCIAL]}" for c in clientes))
        ruts = list(dict.fromkeys(str(c["RUT"]) for c in clientes if str(c["RUT"]) != "Sin RUT"))
        cdbs = list(dict.fromkeys(x.strip() for c in clientes for x in str(c[COL_CDB_COMERCIAL]).split(",") if x.strip() not in ("", "-")))
        self._llenar_combo(self.cmb_g_rut, ruts)
        self._llenar_combo(self.cmb_g_cdb, cdbs)
        self.txt_g_razon.blockSignals(True)
        self.txt_g_razon.setText(comun)
        self.txt_g_razon.blockSignals(False)
        self._actualizar_grupo()
        self.pagina.setCurrentIndex(2)
        self._pie.hide()

    def _cambios_grupo(self):
        razon, rut, cdb = self.txt_g_razon.text().strip(), self.txt_g_rut.text().strip(), self.txt_g_cdb.text().strip()
        cambia_razon = bool(razon) and any(c["RAZÓN SOCIAL"] != razon or c["OTRAS RAZONES"] != "-" for c in self._grupo)
        llave = comercial_services.rut_llave(rut) if rut else None
        return (razon if cambia_razon else ""), (rut if llave else ""), cdb, bool(rut) and not llave

    def _actualizar_grupo(self):
        if not self._grupo:
            return
        razon, rut, cdb, rut_invalido = self._cambios_grupo()
        total = sum(int(c["UNIDADES"]) for c in self._grupo)
        partes = ([f"razón social «{razon}»"] if razon else []) + ([f"RUT {rut}"] if rut else []) + ([f"CDB {cdb}"] if cdb else [])
        if rut_invalido:
            self.lbl_g_aviso.setText("El RUT escrito no es válido.")
        elif partes:
            self.lbl_g_aviso.setText(f"Se asignará {', '.join(partes)} en {_unidades(total)} de {len(self._grupo)} clientes.")
        else:
            self.lbl_g_aviso.setText("Cambia la razón social, el RUT o el CDB para aplicarlo a todos los clientes elegidos.")
        alertas = []
        llave = comercial_services.rut_llave(rut) if rut else None
        destino = self._grupo_otros.get(f"RUT:{llave}") if llave else None
        if destino is not None:
            alertas.append(f"Ese RUT ya pertenece a {destino['RAZÓN SOCIAL']}; las unidades se unirán a ese cliente.")
        ajeno = self._grupo_cdb_ajenos.get(cdb) if cdb else None
        if ajeno:
            alertas.append(f"Ese CDB ya lo usa {ajeno}. Confirma que sea el correcto.")
        self.lbl_g_alerta.setText("\n".join(alertas))
        self.lbl_g_alerta.setVisible(bool(alertas))
        self.btn_grupo.setEnabled(bool(partes) and not rut_invalido)

    def _on_guardar_grupo(self):
        razon, rut, cdb, rut_invalido = self._cambios_grupo()
        if self._grupo and not rut_invalido and (razon or rut or cdb):
            self.guardar_grupo.emit([c["CLAVE"] for c in self._grupo], razon, rut, cdb)

    def limpiar(self):
        self.cliente = None
        self._grupo = []
        self.pagina.setCurrentIndex(0)
        self._pie.hide()

    def _refrescar_boton(self):
        self.btn_cliente.setEnabled(any(self._habilitado.values()))

    @staticmethod
    def _titulo_seccion(texto):
        return admin_estilo.rotulo_campo(texto)

    @staticmethod
    def _aviso(color, negrita=False):
        lbl = QLabel("")
        lbl.setWordWrap(True)
        peso = "700" if negrita else "400"
        lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: {peso}; background: transparent; border: none;")
        return lbl

    @staticmethod
    def _llenar_combo(combo, opciones):
        """Carga la lista de un combo editable y deja su campo de texto vacío, sin disparar señales."""
        linea = combo.lineEdit()
        combo.blockSignals(True)
        linea.blockSignals(True)
        combo.clear()
        combo.addItems(opciones)
        combo.setCurrentIndex(-1)
        linea.clear()
        linea.blockSignals(False)
        combo.blockSignals(False)

    @staticmethod
    def _boton_guardar(texto):
        return admin_estilo.boton_pie(texto, "primario", 'fa5s.save')

    @property
    def txt_cdb(self):
        return self.cmb_cdb_modo.lineEdit() if self._solo_cdb else self._txt_cdb_simple

    def _al_elegir_cdb_de_lista(self, indice):
        """Las opciones de la lista llevan sus unidades; en el campo queda solo el CDB."""
        if indice >= 0:
            self._poner_texto(self.cmb_cdb_modo.lineEdit(), str(self.cmb_cdb_modo.itemData(indice) or ""))
            self._actualizar_cdb()

    @staticmethod
    def _poner_texto(linea, texto):
        linea.blockSignals(True)
        linea.setText(texto)
        linea.setCursorPosition(0)
        linea.blockSignals(False)

    def _cdb_de_razon(self, razon):
        """CDB comercial que se propone para la razón: el de sus unidades si es uno solo (o el más frecuente si el cliente tiene varias razones)."""
        reales = [c for c, _n in self._cdb_por_razon.get(razon, []) if c != '-']
        if len(self._razones) > 1:
            return reales[0] if reales else ""
        return reales[0] if len(reales) == 1 else ""

    def _al_elegir_razon(self, _i=None):
        """Al elegir la razón social, el RUT del cliente y el CDB de esa razón ya vienen completos."""
        if self.cliente is None:
            return
        razon = self.cmb_razon.currentData()
        n = next((n for r, n in self._razones if r == razon), 0)
        self.cmb_razon.setToolTip(razon or "")
        self.lbl_aviso_razon.setText(f"{_unidades(n)} con esta razón social.")
        rut = str(self.cliente["RUT"])
        self._poner_texto(self.txt_rut, "" if rut == "Sin RUT" else rut)
        if not self._solo_cdb and (len(self._razones) > 1 or self._sugerido is None):
            self._poner_texto(self.txt_cdb, self._cdb_de_razon(razon))
        self._actualizar_rut()
        self._actualizar_cdb()

    def set_cliente(self, cliente, razones, otros_clientes, cdbs=(), cdb_ajenos=None, cdbs_flota=(), cdb_por_razon=None,
                    solo_cdb=False):
        """Carga el cliente (dict de resumen_clientes), sus razones [(nombre, unidades)], los demás
        clientes, sus CDB [(cdb, unidades)], los CDB que usan otros clientes {cdb: razón social}, los
        CDB flota del cliente (con ellos se propone la corrección) y los CDB de cada razón
        {razón: [(cdb, unidades)]}. Con `solo_cdb` (filtro Varios CDB) solo se edita el CDB, para todo el cliente."""
        self.cliente = cliente
        self._solo_cdb = solo_cdb
        self._pag_razon.setVisible(not solo_cdb)
        self._pag_rut.setVisible(not solo_cdb)
        self._txt_cdb_simple.setVisible(not solo_cdb)
        self.cmb_cdb_modo.setVisible(solo_cdb)
        self._cdbs_flota = set(cdbs_flota)
        self._sugerido = None
        self._razones = razones
        self._otros = {c["CLAVE"]: c for c in otros_clientes}
        self._cdbs = list(cdbs)
        self._cdb_ajenos = cdb_ajenos or {}
        self._cdb_por_razon = cdb_por_razon or {}
        self.lbl_nombre.setText(str(cliente["RAZÓN SOCIAL"]))
        self.chip_rut.setText(f"RUT {cliente['RUT']}")
        self.chip_unidades.setText(_unidades(int(cliente["UNIDADES"])))
        self.chip_razones.setText(f"{len(razones)} razones")
        self.chip_razones.setVisible(len(razones) > 1)
        self.cmb_razon.blockSignals(True)
        self.cmb_razon.clear()
        for razon, n in razones:
            self.cmb_razon.addItem(f"{razon}  ·  {_unidades(n)}", razon)
        self.cmb_razon.setCurrentIndex(0)
        self.cmb_razon.blockSignals(False)
        reales = [c for c, _n in self._cdbs if c != '-']
        self.chip_cdb.setText(f"{len(reales)} CDB")
        self.chip_cdb.setVisible(len(reales) > 1)
        if solo_cdb:
            combo = self.cmb_cdb_modo
            combo.blockSignals(True)
            combo.clear()
            for cdb, n in self._cdbs:
                if cdb != '-':
                    combo.addItem(f"{cdb}  ·  {_unidades(n)}", cdb)
            combo.setCurrentIndex(-1)
            combo.blockSignals(False)
        self._poner_texto(self.txt_cdb, "")
        if len(razones) == 1 or solo_cdb:
            self._proponer_cdb()
        self._al_elegir_razon()
        self.pagina.setCurrentIndex(1)
        self._pie.show()

    # ------------------------------------------------------------------- RUT
    def _destino(self):
        llave = comercial_services.rut_llave(self.txt_rut.text())
        return self._otros.get(f"RUT:{llave}") if llave else None

    def _actualizar_rut(self):
        if self.cliente is None:
            return
        if self._solo_cdb:
            self._habilitado["rut"] = False
            self._refrescar_boton()
            return
        razon = self.cmb_razon.currentData()
        n = next((n for r, n in self._razones if r == razon), 0)
        llave = comercial_services.rut_llave(self.txt_rut.text())
        destino = self._destino()
        misma = bool(llave) and f"RUT:{llave}" == self.cliente["CLAVE"]
        self.chk_nombre.hide()
        if not llave:
            texto = "Escribe el RUT nuevo para la razón social elegida."
        elif misma:
            texto = "Ese ya es el RUT actual de este cliente."
        elif destino is not None:
            texto = (f"Este RUT ya pertenece a {destino['RAZÓN SOCIAL']} ({_unidades(int(destino['UNIDADES']))}). "
                     f"Las {_unidades(n)} de esta razón se unirán a ese cliente.")
            if _sin_formato(destino["RAZÓN SOCIAL"]) != _sin_formato(razon or ""):
                self.chk_nombre.setText(f"Usar también el nombre «{destino['RAZÓN SOCIAL']}»")
                self.chk_nombre.show()
        else:
            texto = f"Se asignará ese RUT en {_unidades(n)}; el CDB no se modifica."
        self.lbl_aviso_rut.setText(texto)
        self._habilitado["rut"] = bool(llave) and not misma and bool(razon)
        self._refrescar_boton()

    # ------------------------------------------------------------------- CDB
    def _proponer_cdb(self):
        """Si un CDB comercial del cliente coincide con su CDB flota, se da por equivocado: si el cliente
        tiene un solo CDB comercial distinto del flota, se propone ese como el nuevo."""
        reales = [c for c, _n in self._cdbs if c != '-']
        de_flota = [c for c in reales if c in self._cdbs_flota]
        correctos = [c for c in reales if c not in self._cdbs_flota]
        if not de_flota or len(correctos) != 1:
            return
        self._sugerido = correctos[0]
        self._poner_texto(self.txt_cdb, self._sugerido)

    def _unidades_a_cambiar_cdb(self, nuevo):
        if self._solo_cdb:
            return sum(n for cdb, n in self._cdbs if cdb != nuevo)
        razon = self.cmb_razon.currentData()
        return sum(n for cdb, n in self._cdb_por_razon.get(razon, []) if cdb != nuevo)

    def _actualizar_cdb(self):
        if self.cliente is None:
            return
        nuevo = self.txt_cdb.text().strip()
        n = self._unidades_a_cambiar_cdb(nuevo) if nuevo else 0
        if not nuevo:
            texto = "Escribe el CDB comercial nuevo (hasta 10 dígitos)."
        elif n == 0:
            texto = "Esas unidades ya tienen ese CDB."
        else:
            texto = f"Se asignará el CDB {nuevo} en {_unidades(n)}; el CDB flota no se modifica."
            if nuevo == self._sugerido:
                texto = "Sugerido: el CDB a corregir coincide con el CDB flota del cliente. " + texto
        self.lbl_aviso_cdb.setText(texto)
        ajeno = self._cdb_ajenos.get(nuevo) if nuevo else None
        if ajeno:
            self.lbl_ajeno_cdb.setText(f"Ese CDB ya lo usa {ajeno}. Confirma que sea el correcto.")
            self.lbl_ajeno_cdb.show()
        else:
            self.lbl_ajeno_cdb.hide()
        self._habilitado["cdb"] = n > 0
        self._refrescar_boton()

    # --------------------------------------------------------------- guardar
    def _on_guardar_cliente(self):
        """Envía de una vez lo que haya cambiado en el RUT y el CDB de la razón social elegida."""
        if self.cliente is None or not any(self._habilitado.values()):
            return
        rut, nombre_destino = "", None
        if self._habilitado["rut"]:
            destino = self._destino()
            usar_nombre = destino is not None and not self.chk_nombre.isHidden() and self.chk_nombre.isChecked()
            rut = self.txt_rut.text().strip()
            nombre_destino = destino["RAZÓN SOCIAL"] if usar_nombre else None
        cdb = self.txt_cdb.text().strip() if self._habilitado["cdb"] else ""
        razon = "" if self._solo_cdb else self.cmb_razon.currentData() or ""
        self.guardar_cliente.emit(self.cliente["CLAVE"], razon, rut, nombre_destino, cdb)


class ClientesAdminModule(GuardadoUnidadesMixin, QWidget):
    MODULO_LOG = "Administración (Clientes)"

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.df_clientes = pd.DataFrame(columns=comercial_services.COLUMNAS_RESUMEN_CLIENTES)
        self.df_tabla = pd.DataFrame(columns=COLUMNAS)
        self._cdbs = {}
        self._cdbs_flota = {}
        self._data_dirty = False
        self._clave_panel = None
        self._filtro = 0
        self._expandiendo = False
        self._badges_sec = []

        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()
        self.data_manager.data_ready.connect(self._on_data_ready)
        self.load_data()

    # ------------------------------------------------------------ interfaz
    def _setup_ui(self):
        layout = admin_estilo.raiz_pantalla(self)
        cuerpo = QWidget()
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(12)
        fila.addWidget(self._crear_caja_filtros())
        fila.addWidget(self._crear_caja_tabla(), 1)
        fila.addWidget(self._crear_caja_detalle())
        layout.addWidget(cuerpo, 1)
        self._botones_sec[0].setChecked(True)
        self._actualizar_panel()

    def _crear_caja_filtros(self):
        caja = admin_estilo.caja_con_encabezado("cajaFiltrosClientes", "Clientes", "Filtros y acciones")
        caja.marco.setFixedWidth(250)
        lista = QWidget()
        lay_lista = QVBoxLayout(lista)
        lay_lista.setContentsMargins(8, 8, 8, 8)
        lay_lista.setSpacing(4)
        self._botones_sec = []
        for i, (nombre, icono) in enumerate(zip(SUBTABS, ('fa5s.users', 'fa5s.clone', 'fa5s.code-branch', 'fa5s.id-card', 'fa5s.random'))):
            boton, badge = admin_estilo.boton_seccion(nombre, icono)
            self._badges_sec.append(badge)
            boton.clicked.connect(lambda _c, k=i: self._elegir_filtro(k))
            lay_lista.addWidget(boton)
            self._botones_sec.append(boton)
        caja.cuerpo.addWidget(lista)

        bloque = admin_estilo.bloque_caja("Acciones")
        self.btn_exportar = admin_estilo.boton_accion("Exportar a Excel", 'fa5s.file-excel')
        self.btn_exportar.clicked.connect(self._exportar_excel)
        bloque.layout().addWidget(self.btn_exportar)
        caja.cuerpo.addWidget(bloque)
        caja.cuerpo.addStretch(1)
        return caja.marco

    def _crear_caja_tabla(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaTablaClientes", "Todos los clientes", "")
        self.table = VolvoTableWidget()
        self.table.menu_type = "solo_lectura"
        admin_estilo.estilar_tabla(self.table)
        self.model = ModeloTablaIngresos(
            resolver=self._color_celda, alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table.set_model_and_delegate(self.model)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.viewport().installEventFilter(self)
        self.table.sort_changed.connect(self._pintar_tabla)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._al_cambiar_seleccion())
        self._caja.cuerpo.addWidget(self.table, 1)
        return self._caja.marco

    def _crear_caja_detalle(self):
        self._det = admin_estilo.caja_con_encabezado("cajaDetalleClientes", "Detalle", "Cliente")
        self._det.marco.setFixedWidth(340)
        self.panel = PanelCliente()
        self.panel.guardar_cliente.connect(self._on_guardar_cliente)
        self.panel.guardar_grupo.connect(self._on_guardar_grupo)
        self._det.cuerpo.addWidget(self.panel, 1)
        return self._det.marco

    def _elegir_filtro(self, indice):
        self._filtro = indice
        self._clave_panel = None
        for i, boton in enumerate(self._botones_sec):
            boton.setChecked(i == indice)
        self._pintar_tabla()

    def _exportar_excel(self):
        if self.df_tabla.empty:
            return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar Excel", "Clientes.xlsx", "Archivos Excel (*.xlsx)")
        if ruta:
            from src.ui.compartido.exportacion import iniciar_exportacion
            iniciar_exportacion(self, self.df_tabla, ruta, titulo="Clientes")

    @staticmethod
    def _color_celda(columna, valor, es_fondo):
        if columna == "OTRAS RAZONES" and valor != "-" and not es_fondo:
            return "#E04848"
        if columna == COL_CDB_COMERCIAL and ',' in str(valor) and not es_fondo:
            return "#E04848"
        if columna == "RUT" and valor == "Sin RUT" and not es_fondo:
            return "#D98404"
        return None

    def eventFilter(self, obj, event):
        """El clic derecho no cambia la selección (así no se recarga la caja derecha); el menú de copiar sigue funcionando."""
        if (obj is self.table.viewport() and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton):
            return True
        return super().eventFilter(obj, event)

    def _al_cambiar_seleccion(self):
        """En Varios RUT, elegir una fila elige también las de la misma razón social para editarlas juntas."""
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if self._filtro == 4 and not self._expandiendo and len(filas) == 1 and 0 <= filas[0] < len(self.df_tabla):
            razon = _sin_formato(self.df_tabla.iloc[filas[0]]["RAZÓN SOCIAL"])
            hermanas = [i for i, r in enumerate(self.df_tabla["RAZÓN SOCIAL"]) if _sin_formato(r) == razon]
            if len(hermanas) > 1:
                self._expandiendo = True
                try:
                    for i in hermanas:
                        self.table.selectionModel().select(
                            self.table.model().index(i, 0),
                            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                finally:
                    self._expandiendo = False
        self._actualizar_panel()

    def _actualizar_panel(self):
        self.btn_exportar.setEnabled(not self.df_tabla.empty)
        seleccionados = self._clientes_seleccionados()
        if len(seleccionados) > 1:
            claves = tuple(sorted(c["CLAVE"] for c in seleccionados))
            if claves != self._clave_panel:
                self._clave_panel = claves
                otros = [c for c in self.df_clientes.to_dict('records') if c["CLAVE"] not in claves]
                self.panel.set_grupo(seleccionados, otros, self._cdb_ajenos(claves, None))
                self._det.lbl_subtitulo.setText("Varios clientes")
            return
        cliente = seleccionados[0] if seleccionados else None
        if cliente is None:
            self._clave_panel = None
            self.panel.limpiar()
            self._det.lbl_subtitulo.setText("Cliente")
            return
        if cliente["CLAVE"] != self._clave_panel:
            self._clave_panel = cliente["CLAVE"]
            otros = [c for c in self.df_clientes.to_dict('records') if c["CLAVE"] != cliente["CLAVE"]]
            razones = comercial_services.razones_de_cliente(self.data_manager.get_comercial_df(), cliente["CLAVE"])
            cdbs = self._cdbs.get(cliente["CLAVE"], [])
            flota = [c for c, _n in self._cdbs_flota.get(cliente["CLAVE"], []) if c != '-']
            self.panel.set_cliente(cliente, razones, otros, cdbs, self._cdb_ajenos(cliente["CLAVE"], cdbs), flota,
                                   self._cdb_por_razon(cliente["CLAVE"]), solo_cdb=self._filtro == 2)
            self._det.lbl_subtitulo.setText("Cliente")

    def _cdb_por_razon(self, clave):
        """{razón social: [(CDB, unidades)]} de un cliente, de mayor a menor y con '-' (sin CDB) al final."""
        actuales = self.data_manager.get_contratos_actuales_df()
        if actuales is None or actuales.empty or not all(c in actuales.columns for c in ("RUT", "RAZÓN SOCIAL", "CDB")):
            return {}
        razon = actuales["RAZÓN SOCIAL"].astype(str).str.strip()
        propias = actuales[comercial_services.clave_cliente_serie(actuales["RUT"], razon) == clave]
        resultado = {}
        for nombre, grupo in propias.groupby(propias["RAZÓN SOCIAL"].astype(str).str.strip()):
            conteo = comercial_services._cdb_serie(grupo).value_counts()
            resultado[nombre] = sorted(conteo.items(), key=lambda kv: (kv[0] == '-', -kv[1]))
        return resultado

    def _cdb_ajenos(self, clave, cdbs):
        """{CDB: razón social} de los CDB que ya usa otro cliente (o ninguno de los claves dadas), para avisar al escribirlos."""
        excluidas = {clave} if isinstance(clave, str) else set(clave)
        razon_de = dict(zip(self.df_clientes["CLAVE"], self.df_clientes["RAZÓN SOCIAL"]))
        ajenos = {}
        for otra, lista in self._cdbs.items():
            if otra in excluidas:
                continue
            for cdb, _n in lista:
                if cdb != '-' and cdb not in ajenos:
                    ajenos[cdb] = razon_de.get(otra, "otro cliente")
        return ajenos

    # --------------------------------------------------------------- datos
    def load_data(self):
        self._data_dirty = False
        self.df_clientes, self._cdbs, self._cdbs_flota = armar_resumen(self.data_manager)
        self._clave_panel = None
        self._actualizar_kpis_y_contadores()
        self._pintar_tabla()

    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def _on_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def _filtrar_subtab(self, df, idx):
        if df.empty:
            return df
        if 1 <= idx <= 4:
            filtrado = df[mascaras_casos(df)[idx - 1]]
            if idx == 4:
                filtrado = filtrado.sort_values(["RAZÓN SOCIAL", "RUT"], key=lambda s: s.astype(str).str.upper(), kind="stable")
            return filtrado
        return df

    def _actualizar_kpis_y_contadores(self):
        df = self.df_clientes
        total = len(df)
        masc_razones, masc_cdb, masc_sin_rut, masc_varios_rut = mascaras_casos(df)
        varias, varios_cdb = int(masc_razones.sum()), int(masc_cdb.sum())
        unidades = int(df["UNIDADES"].sum()) if total else 0
        conteos = (total, varias, varios_cdb, int(masc_sin_rut.sum()), int(masc_varios_rut.sum()))
        for i, (badge, n) in enumerate(zip(self._badges_sec, conteos)):
            admin_estilo.fijar_badge(badge, n)
            alerta = i > 0 and n > 0
            # El texto oscuro va por la paleta: en modo oscuro las hojas de estilo aclaran los colores de texto
            paleta = badge.palette()
            paleta.setColor(badge.foregroundRole(), QColor("#1B2B4E" if alerta else "white"))
            badge.setPalette(paleta)
            badge.setStyleSheet(
                f"background-color: {'#F59E0B' if alerta else 'rgba(255,255,255,0.18)'}; "
                "border-radius: 10px; font-size: 11px; font-weight: bold;")
        self._caja.lbl_subtitulo.setText(
            f"{total} clientes · {varias} con varias razones · {varios_cdb} con varios CDB · {unidades} unidades")

    def _pintar_tabla(self):
        df = self._filtrar_subtab(self.df_clientes, self._filtro)
        df = df[COLUMNAS] if not df.empty else pd.DataFrame(columns=COLUMNAS)
        texto = self.search_input.text().strip().lower()
        if texto and not df.empty:
            mascara = df.astype(str).apply(lambda col: col.str.lower().str.contains(texto, regex=False)).any(axis=1)
            df = df[mascara]
        self.df_tabla = self.table.apply_sort(df).reset_index(drop=True)
        self._caja.lbl_titulo.setText(TITULOS_FILTRO[self._filtro])
        self.model.set_data(self.df_tabla)
        admin_estilo.fijar_columnas(self.table, {"RUT": 110, "OTRAS RAZONES": 170, COL_CDB_COMERCIAL: 170, "UNIDADES": 100},
                                    "RAZÓN SOCIAL")
        if COL_CDB_FLOTA in self.df_tabla.columns:
            self.table.setColumnHidden(self.df_tabla.columns.get_loc(COL_CDB_FLOTA), True)
        self._actualizar_panel()

    def filter_table(self):
        self._pintar_tabla()

    # ----------------------------------------------------------- acciones
    def _clientes_seleccionados(self):
        """Los clientes (dict de resumen_clientes) de las filas elegidas en la tabla."""
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        clientes = []
        for r in filas:
            if not (0 <= r < len(self.df_tabla)):
                continue
            fila = self.df_tabla.iloc[r]
            coincide = self.df_clientes[(self.df_clientes["RUT"] == fila["RUT"])
                                        & (self.df_clientes["RAZÓN SOCIAL"] == fila["RAZÓN SOCIAL"])]
            if not coincide.empty:
                clientes.append(coincide.iloc[0].to_dict())
        return clientes

    def _on_guardar_grupo(self, claves, razon, rut, cdb):
        lote = comercial_services.cambios_grupo_clientes(
            self.data_manager.get_comercial_df(), self.data_manager.get_contratos_actuales_df(), claves,
            razon or None, rut or None, cdb or None)
        if not lote:
            QMessageBox.information(self, "Sin cambios", "Las unidades de estos clientes ya tienen esos datos.")
            return
        self.guardar_lote_unidades(lote, f"Guardando {len(claves)} clientes…")

    def _on_guardar_cliente(self, clave, razon, rut, nombre_destino, cdb):
        comercial, actuales = self.data_manager.get_comercial_df(), self.data_manager.get_contratos_actuales_df()
        lotes = []
        if rut:
            lotes.append(comercial_services.cambios_rut_razon_cliente(comercial, clave, razon, rut, nombre_destino))
        if cdb and razon:
            lotes.append(comercial_services.cambios_cdb_razon_cliente(actuales, clave, razon, cdb))
        elif cdb:
            lotes.append(comercial_services.cambios_cdb_cliente(actuales, clave, None, cdb))
        lote = comercial_services.combinar_lotes(*lotes)
        if not lote:
            QMessageBox.information(self, "Sin cambios", "Las unidades de esta razón social ya tienen esos datos.")
            return
        self.guardar_lote_unidades(lote, "Guardando los datos del cliente…")
