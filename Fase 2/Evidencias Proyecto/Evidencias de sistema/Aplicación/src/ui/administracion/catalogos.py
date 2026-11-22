"""Administración > Catálogos: opciones de los combos del formulario de unidad.
A la izquierda, las categorías (Ejecutivos, Modelos, Industrias, Traducciones
de industria y Tipos de servicio); al centro, la tabla de la categoría con el
alta arriba; al seleccionar una fila se abre a la derecha el panel con su
detalle, como en Clientes. Ejecutivos se guarda en Ejecutivos_VC.csv y el resto
en Catalogos_VC.csv."""
import time
import pandas as pd
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
                             QMessageBox, QComboBox, QCheckBox, QScrollArea, QStackedWidget, QSizePolicy)

from src.core.data_manager import DataManager
import config.settings
from src.core.excel_writer import ExcelWriter
from src.services import cartera_ejecutivos_service, catalogos_service, comercial_services, ejecutivos_service, provisiones_services
from src.services.catalogos_service import MODELO, INDUSTRIA, SERVICIO, COMPLEMENTO
from src.ui.administracion import cartera_ejecutivos
from src.ui.administracion.cartera_ejecutivos import _miles
from src.ui.comercial.base import SaveExcelThread
from src.theme.colors import BORDE_CAJA
from src.theme.theme_manager import ThemeManager
from src.ui.administracion import estilo as admin_estilo
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.ingresos.base import ModeloTablaIngresos

EJECUTIVO = "ejecutivo"
TRADUCCION = "traduccion"
CATEGORIAS = (
    (EJECUTIVO, "Ejecutivos", 'fa5s.user-tie'),
    (MODELO, "Modelos", 'fa5s.truck'),
    (INDUSTRIA, "Industrias", 'fa5s.industry'),
    (TRADUCCION, "Traducciones de industria", 'fa5s.language'),
    (SERVICIO, "Tipos de servicio", 'fa5s.concierge-bell'),
    (COMPLEMENTO, "Complementos del plan", 'fa5s.puzzle-piece'),
)
_TEXTOS = {
    EJECUTIVO: dict(titulo="Ejecutivos", singular="ejecutivo", columna="EJECUTIVO"),
    MODELO: dict(titulo="Modelos", singular="modelo", columna="MODELO",
                 ayuda="Aparece en el campo Modelo al crear o editar una unidad y lo reconoce la importación del Power BI."),
    INDUSTRIA: dict(titulo="Industrias", singular="industria", columna="INDUSTRIA",
                    ayuda="Aparece en el campo Industria de la ficha del cliente."),
    SERVICIO: dict(titulo="Tipos de servicio", singular="tipo de servicio", columna="TIPO DE SERVICIO",
                   ayuda="Plan base del campo Tipo de servicio; CIV y Safety Zone se eligen aparte."),
    COMPLEMENTO: dict(titulo="Complementos del plan", singular="complemento", columna="COMPLEMENTO",
                      ayuda="Se elige junto al plan en el formulario de unidad, Operaciones y Facturación Manual "
                            "(por ejemplo CIV y Safety Zone). Su valor en UF se escribe en la ventana de Costos de Provisiones."),
    TRADUCCION: dict(titulo="Traducciones de industria", singular="traducción", columna="TEXTO DEL POWER BI"),
}
_COLUMNAS = {
    EJECUTIVO: ["EJECUTIVO", "CORREO", "UNIDADES", "ESTADO"],
    MODELO: ["MODELO", "UNIDADES", "ESTADO"],
    INDUSTRIA: ["INDUSTRIA", "UNIDADES", "ESTADO"],
    SERVICIO: ["TIPO DE SERVICIO", "PRECIO", "UNIDADES", "ESTADO"],
    COMPLEMENTO: ["COMPLEMENTO", "NOMBRE", "VALOR", "UNIDADES", "ESTADO"],
    TRADUCCION: ["TEXTO DEL POWER BI", "SE TRADUCE A", "ORIGEN", "UNIDADES"],
}
_ANCHOS = {"PRECIO": 210, "NOMBRE": 220, "VALOR": 150, "CORREO": 300, "UNIDADES": 105, "ESTADO": 95, "SE TRADUCE A": 240, "ORIGEN": 120}
_ANCHO_MINIMO_TABLA = 780
_ANCHO_PANEL = 330
_AZUL_OSCURO = "#1B2B4E"
_ESTILO_BOTON_PRIM = (
    f"QPushButton {{ background: {_AZUL_OSCURO}; color: white; border: none; border-radius: 10px; "
    "padding: 0 16px; min-height: 34px; font-weight: 700; font-size: 12px; } "
    "QPushButton:hover { background: #2C4A80; } QPushButton:disabled { background: #8E9BB5; }")
_ESTILO_COMBO = f"""
    QComboBox {{ background-color: #FFFFFF; border: 1px solid #DCE3EC; border-radius: 8px; padding: 6px 10px;
        color: {estilo_com.TINTA}; font-weight: 500; font-size: 12px; combobox-popup: 0; }}
    QComboBox:hover {{ border: 1px solid #B9C6DA; }}
    QComboBox:focus, QComboBox:on {{ border: 1px solid {_AZUL_OSCURO}; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
        border-left: 1px solid #E3E8F0; border-top-right-radius: 7px; border-bottom-right-radius: 7px;
        background-color: #F7F8FC; }}
    QComboBox::down-arrow {{ image: url({_COMBO_CHEVRON_PATH}); width: 11px; height: 11px; }}
    QComboBox QLineEdit {{ border: none; background: transparent; padding: 0px; }}
"""
_ESTILO_BOTON_PELIGRO = (
    "QPushButton { background: #B3261E; color: white; border: none; border-radius: 10px; "
    "padding: 0 16px; min-height: 34px; font-weight: 700; font-size: 12px; } "
    "QPushButton:hover { background: #961F18; }")
_ESTILO_BOTON_SEC = (
    f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
    "border-radius: 10px; padding: 0 16px; min-height: 34px; font-weight: 700; font-size: 12px; } "
    "QPushButton:hover { background: #F1F4F9; }")
_FILTROS = {
    EJECUTIVO: ("Todos", "Sin correo", "Inactivos"),
    TRADUCCION: ("Todas", "Por traducir", "Del equipo", "De fábrica"),
}
_FILTROS_VALORES = ("Todos", "Activos", "Inactivos")
_TEXTO_SIN_CORREO = "Sin correo"
_ESTADO_SIN_EJECUTIVO = "Sin ejecutivo"
_TEXTO_SIN_PRECIO = "Sin precio"
_TEXTO_SIN_VALOR = "Sin valor"
_ORIGEN_PENDIENTE, _ORIGEN_EQUIPO, _ORIGEN_FABRICA = "Por traducir", "Del equipo", "De fábrica"


def _etiqueta_campo(texto):
    return admin_estilo.rotulo_campo(texto)


class PanelCatalogo(QWidget):
    """Detalle y acciones de la fila seleccionada; vive siempre en la caja de la derecha."""

    agregar = pyqtSignal(str, str)
    cancelar_alta = pyqtSignal()
    guardar_ejecutivo = pyqtSignal(str, str, str, str, bool)
    alternar_activo = pyqtSignal(str, bool)
    eliminar = pyqtSignal(str)
    guardar_traduccion = pyqtSignal(str, str)
    quitar_traduccion = pyqtSignal(str)
    guardar_precio = pyqtSignal(str, str)
    guardar_nombre = pyqtSignal(str, str)
    editar_precios = pyqtSignal()
    abrir_cartera = pyqtSignal(str, str)
    aplicar_reasignar = pyqtSignal(str, list, str)
    aplicar_asignar = pyqtSignal(str, str, bool)
    aplicar_eliminar = pyqtSignal(str)
    volver_detalle = pyqtSignal()
    cerrar_listo = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titulo = ("Detalle", "")
        marco = QVBoxLayout(self)
        marco.setContentsMargins(0, 0, 0, 0)
        marco.setSpacing(0)
        self._pila = QStackedWidget()
        marco.addWidget(self._pila, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        contenido = QWidget()
        contenido.setObjectName("cuerpoPanelCatalogo")
        contenido.setStyleSheet("QWidget#cuerpoPanelCatalogo { background: transparent; }" + admin_estilo.QSS_CAMPOS_DETALLE)
        scroll.setWidget(contenido)
        self._pila.addWidget(scroll)
        self._pila.addWidget(self._crear_estado_vacio())
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self._cuerpo = QVBoxLayout()
        self._cuerpo.setSpacing(8)
        lay.addLayout(self._cuerpo)
        lay.addStretch(1)

        self._pie, self._pie_lay = admin_estilo.crear_pie()
        marco.addWidget(self._pie)
        self._pie.hide()

    def _crear_estado_vacio(self):
        pagina, self._mostrar_cartel = admin_estilo.estado_vacio()
        return pagina

    def mostrar_vacio(self, icono, titulo, detalle, tipo=""):
        self._vaciar()
        self._pila.setCurrentIndex(1)
        self.titulo = ("Detalle", tipo)
        self._mostrar_cartel(icono, titulo, detalle)

    def _nombre(self, texto):
        self._cuerpo.addWidget(admin_estilo.nombre_detalle(texto))

    def mostrar_alta(self, cat):
        self._vaciar()
        if cat == EJECUTIVO:
            self.titulo = ("Detalle", "Nuevo ejecutivo")
            campos = (("Nombre", "Nombre del ejecutivo"), ("Correo", "nombre.apellido@volvo.com"))
            self._nota("Tal como aparece en el Registro Maestro.")
        elif cat == TRADUCCION:
            self.titulo = ("Detalle", "Nueva traducción")
            campos = (("Texto en inglés", "Tal como llega del Power BI"), ("Se traduce a", "Nombre en español"))
            self._nota("Industria del Power BI.")
        elif cat == COMPLEMENTO:
            self.titulo = ("Detalle", "Nuevo complemento")
            campos = (("Código", "Ej: SZ"), ("Nombre", "Ej: Safety Zone"))
            self._nota("El código es lo que se escribe en el tipo de servicio (por ejemplo «Medio + SZ»): solo letras y "
                       "números. Su valor en UF queda en 0 hasta que se escriba en Costos de Provisiones.")
        else:
            singular = _TEXTOS[cat]['singular']
            self.titulo = ("Detalle", f"{'Nueva' if cat == INDUSTRIA else 'Nuevo'} {singular}")
            campos = ((singular.capitalize(), f"{'Nueva' if cat == INDUSTRIA else 'Nuevo'} {singular}"),)
        editores = []
        for etiqueta, ayuda in campos:
            self._cuerpo.addWidget(_etiqueta_campo(etiqueta))
            editor = QLineEdit()
            editor.setPlaceholderText(ayuda)
            self._cuerpo.addWidget(editor)
            editores.append(editor)

        def enviar():
            self.agregar.emit(editores[0].text(), editores[1].text() if len(editores) > 1 else "")
        for editor in editores:
            editor.returnPressed.connect(enviar)
        self._boton("Agregar", True, enviar)
        self._boton("Cancelar", False, self.cancelar_alta.emit)
        editores[0].setFocus()

    # ------------------------------------------------------------ armado
    def _vaciar(self):
        self._pila.setCurrentIndex(0)
        def limpiar(layout):
            while layout.count():
                item = layout.takeAt(0)
                widget, sub = item.widget(), item.layout()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
                elif sub is not None:
                    limpiar(sub)
        limpiar(self._cuerpo)
        limpiar(self._pie_lay)
        self._pie.hide()

    def _chips(self, *chips):
        fila = QHBoxLayout()
        fila.setSpacing(6)
        for texto, fondo, color in chips:
            chip = QLabel(texto)
            chip.setStyleSheet(estilo_com.qss_chip(fondo, color))
            fila.addWidget(chip)
        fila.addStretch()
        self._cuerpo.addLayout(fila)

    def _nota(self, texto, color=None):
        lbl = QLabel(texto)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color or estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        self._cuerpo.addWidget(lbl)
        return lbl

    def _boton(self, texto, primario, accion):
        """Botón del pie fijo del panel; `primario` puede ser True, False o "peligro"."""
        variante = "peligro" if primario == "peligro" else ("primario" if primario else "secundario")
        icono = 'fa5s.save' if texto.startswith("Guardar") else ('fa5s.trash-alt' if variante == "peligro" else None)
        boton = admin_estilo.boton_pie(texto, variante, icono)
        boton.clicked.connect(accion)
        self._pie_lay.addWidget(boton)
        self._pie.show()
        return boton

    def _tarjeta_precios(self, lineas):
        """Recuadro con los precios del plan (base, con CIV, Safety Zone)."""
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaPrecios")
        tarjeta.setStyleSheet(f"QFrame#tarjetaPrecios {{ background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(_etiqueta_campo("Precio del plan"))
        for etiqueta, texto, color in lineas:
            fila = QHBoxLayout()
            izq = QLabel(etiqueta)
            izq.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
            der = QLabel(texto)
            der.setStyleSheet(f"color: {color or estilo_com.TINTA}; font-size: 12px; font-weight: 700; background: transparent; border: none;")
            fila.addWidget(izq)
            fila.addStretch()
            fila.addWidget(der)
            lay.addLayout(fila)
        self._cuerpo.addWidget(tarjeta)

    def _filas_precio(self, lineas):
        for etiqueta, texto, color in lineas:
            fila = QHBoxLayout()
            izq = QLabel(etiqueta)
            izq.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
            der = QLabel(texto)
            der.setStyleSheet(f"color: {color or estilo_com.TINTA}; font-size: 12px; font-weight: 700; background: transparent; border: none;")
            fila.addWidget(izq)
            fila.addStretch()
            fila.addWidget(der)
            self._cuerpo.addLayout(fila)

    def mostrar_ejecutivo(self, fila, unidades):
        self._vaciar()
        self.titulo = ("Detalle", "Ejecutivo")
        activo = str(fila['activo']).strip().upper() != 'NO'
        self._nombre(fila['nombre'])
        self._chips((f"{unidades} {'unidad' if unidades == 1 else 'unidades'}", "#E0F2FE", "#0369A1"),
                    ("Activo" if activo else "Inactivo", "#DCFCE7" if activo else estilo_com.PIZARRA_SUAVE,
                     "#15803D" if activo else estilo_com.APAGADO))
        txt_nombre, txt_correo, txt_alias = QLineEdit(fila['nombre']), QLineEdit(fila['correo']), QLineEdit(fila['alias'])
        txt_correo.setPlaceholderText("nombre.apellido@volvo.com")
        txt_alias.setPlaceholderText("Otras grafías del nombre, separadas por |")
        for etiqueta, campo in (("Nombre", txt_nombre), ("Correo", txt_correo), ("Alias", txt_alias)):
            self._cuerpo.addWidget(_etiqueta_campo(etiqueta))
            self._cuerpo.addWidget(campo)
        chk = QCheckBox("Ejecutivo activo")
        chk.setChecked(activo)
        self._cuerpo.addWidget(chk)
        aviso = self._nota("")

        def al_cambiar_nombre(texto):
            cambio = ejecutivos_service.normalizar_nombre(texto) != ejecutivos_service.normalizar_nombre(fila['nombre'])
            aviso.setText(f"El nombre anterior ({fila['nombre']}) se guardará como alias. PruebasFM no se modifica."
                          if cambio and texto.strip() else "")
        txt_nombre.textChanged.connect(al_cambiar_nombre)
        id_ejecutivo = fila['id_ejecutivo']
        if not activo and unidades:
            self._cuerpo.addWidget(cartera_ejecutivos._caja_aviso(
                f"Sin ejecutivo activo para {_miles(unidades)} contratos",
                "Siguen a nombre de un ejecutivo inactivo. Pásalos a otra persona."))
        elif unidades == 0:
            self._nota("No tiene contratos asignados.", color="#15803D")
        sin_responsable = not activo and unidades > 0
        self._boton("Guardar cambios", not sin_responsable, lambda: self.guardar_ejecutivo.emit(
            id_ejecutivo, txt_nombre.text(), txt_correo.text(), txt_alias.text(), chk.isChecked()))
        if unidades:
            self._boton("Reasignar cartera…", sin_responsable, lambda: self.abrir_cartera.emit('reasignar', id_ejecutivo))
        if activo:
            self._boton(f"Asignar un cliente a {fila['nombre'].split()[0]}…", False,
                        lambda: self.abrir_cartera.emit('asignar', id_ejecutivo))
        if not activo or unidades == 0:
            self._boton("Eliminar ejecutivo", "peligro", lambda: self.abrir_cartera.emit('eliminar', id_ejecutivo))

    def mostrar_valor(self, catalogo, valor, activo, unidades, precios=()):
        self._vaciar()
        datos = _TEXTOS[catalogo]
        self.titulo = ("Detalle", datos['singular'].capitalize())
        self._nombre(valor)
        self._chips((f"{unidades} {'unidad' if unidades == 1 else 'unidades'}", "#E0F2FE", "#0369A1"),
                    ("Activo" if activo else "Inactivo", "#DCFCE7" if activo else estilo_com.PIZARRA_SUAVE,
                     "#15803D" if activo else estilo_com.APAGADO))
        if precios:
            self._tarjeta_precios(precios['lineas'])
            if precios['editable']:
                self._cuerpo.addWidget(_etiqueta_campo("Multiplicador de UF"))
                txt_mult = QLineEdit(precios['mult'])
                txt_mult.setPlaceholderText("Ej: 0,28")
                self._cuerpo.addWidget(txt_mult)
                vista = self._nota("")

                def al_cambiar(texto):
                    try:
                        clp = float(texto.replace(',', '.')) * precios['uf']
                        vista.setText(f"Equivale a ${round(clp):,} al mes con la UF actual.".replace(",", "."))
                    except ValueError:
                        vista.setText("")
                txt_mult.textChanged.connect(al_cambiar)
                al_cambiar(txt_mult.text())
                self._nota("Se escribe en la hoja Planes de provisionFelipe y en el catálogo. La variante con CIV "
                           "se calcula sola sumando el valor del CIV.")
                self._boton("Guardar precio", True, lambda: self.guardar_precio.emit(valor, txt_mult.text()))
            else:
                self._nota("Es un plan de fábrica: su precio se cambia en la misma ventana de Costos de Provisiones.")
            self._boton("Editar precios (UF, CIV y planes)", False, self.editar_precios.emit)
        self._nota(datos['ayuda'])
        self._boton("Desactivar" if activo else "Reactivar", True, lambda: self.alternar_activo.emit(valor, not activo))
        if unidades:
            self._nota(f"Lo usan {unidades} unidades, así que no se puede eliminar: desactívalo para que deje de "
                       "aparecer en el combo sin tocar esas unidades.")
        else:
            self._boton("Eliminar", "peligro", lambda: self.eliminar.emit(valor))

    def mostrar_complemento(self, codigo, nombre, activo, unidades, valor, de_fabrica):
        """`valor` es el texto del valor en UF ('0,05 UF' o 'Sin valor')."""
        self._vaciar()
        self.titulo = ("Detalle", "Complemento")
        self._nombre(codigo)
        self._chips((f"{unidades} {'unidad' if unidades == 1 else 'unidades'}", "#E0F2FE", "#0369A1"),
                    ("Activo" if activo else "Inactivo", "#DCFCE7" if activo else estilo_com.PIZARRA_SUAVE,
                     "#15803D" if activo else estilo_com.APAGADO))
        self._cuerpo.addWidget(_etiqueta_campo("Nombre"))
        txt_nombre = QLineEdit(nombre)
        self._cuerpo.addWidget(txt_nombre)
        self._filas_precio([("Valor", valor, "#D98404" if valor == _TEXTO_SIN_VALOR else None)])
        self._nota("El valor se escribe en la ventana de Costos de Provisiones. Mientras sea 0, un plan cuesta lo mismo "
                   "con y sin este complemento.")
        self._nota(_TEXTOS[COMPLEMENTO]['ayuda'])
        self._boton("Guardar nombre", True, lambda: self.guardar_nombre.emit(codigo, txt_nombre.text()))
        self._boton("Editar precios (UF, complementos y planes)", False, self.editar_precios.emit)
        self._boton("Desactivar" if activo else "Reactivar", False, lambda: self.alternar_activo.emit(codigo, not activo))
        if de_fabrica:
            self._nota("Es un complemento de fábrica: se puede desactivar, pero no eliminar.")
        elif unidades:
            self._nota(f"Lo usan {unidades} unidades, así que no se puede eliminar: desactívalo para que deje de "
                       "aparecer en el combo sin tocar esas unidades.")
        else:
            self._boton("Eliminar", "peligro", lambda: self.eliminar.emit(codigo))

    def mostrar_traduccion(self, texto, destino, origen, unidades, destinos):
        self._vaciar()
        self.titulo = ("Detalle", "Traducción de industria")
        self._nombre(texto)
        colores = {_ORIGEN_PENDIENTE: ("#FEF3C7", "#92400E"), _ORIGEN_EQUIPO: ("#DCFCE7", "#15803D"),
                   _ORIGEN_FABRICA: (estilo_com.PIZARRA_SUAVE, estilo_com.APAGADO)}
        chips = [(origen, *colores[origen])]
        if origen == _ORIGEN_PENDIENTE:
            chips.append((f"{unidades} {'unidad' if unidades == 1 else 'unidades'}", "#E0F2FE", "#0369A1"))
        self._chips(*chips)
        self._cuerpo.addWidget(_etiqueta_campo("Se traduce a"))
        combo = ComboTarjeta("Se traduce a")
        combo.setEditable(True)
        combo.addItems(destinos)
        combo.setCurrentText(destino if destino != "-" else "")
        combo.lineEdit().setPlaceholderText("Nombre en español")
        combo.setStyleSheet(_ESTILO_COMBO)
        self._cuerpo.addWidget(combo)
        self._nota("Se usa en las próximas importaciones del Power BI. Las unidades ya importadas no cambian.")
        self._boton("Guardar traducción", True, lambda: self.guardar_traduccion.emit(texto, combo.currentText()))
        if origen == _ORIGEN_EQUIPO:
            self._boton("Quitar traducción del equipo", False, lambda: self.quitar_traduccion.emit(texto))


class CatalogosModule(QWidget):
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self._cat = EJECUTIVO
        self._df_unidades = pd.DataFrame()
        self._directorio = pd.DataFrame()
        self._unidades = {}
        self._filas = {}
        self._pendientes = []
        self.df_tabla = pd.DataFrame()
        self._clave_panel = None
        self._reseleccionar = None
        self._modo_alta = False
        self._precios_locales = {}
        self._provisiones_pedidas = False
        self._data_dirty = False
        self._botones_nav = {}
        self._sin_ejecutivo = 0
        self._id_en_cartera = None
        self._nombre_tras_listo = None
        self._hilo_cartera = None

        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()
        self._configurar_categoria()
        self.data_manager.data_ready.connect(self._on_data_ready)
        if hasattr(self.data_manager, 'provisiones_ready'):
            self.data_manager.provisiones_ready.connect(self._on_provisiones)
        self.load_data()

    # ------------------------------------------------------------ interfaz
    def _setup_ui(self):
        raiz = admin_estilo.raiz_pantalla(self)
        cuerpo = QWidget()
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(12)
        fila.addWidget(self._crear_caja_categorias())
        fila.addWidget(self._crear_caja_tabla(), 1)
        fila.addWidget(self._crear_caja_detalle())
        raiz.addWidget(cuerpo, 1)

    def _crear_caja_categorias(self):
        caja = admin_estilo.caja_con_encabezado("cajaCategoriasCatalogos", "Catálogos", "Opciones de los combos")
        caja.marco.setFixedWidth(250)
        lay = caja.cuerpo

        lista = QWidget()
        lay_lista = QVBoxLayout(lista)
        lay_lista.setContentsMargins(8, 8, 8, 8)
        lay_lista.setSpacing(4)
        for clave, nombre, icono in CATEGORIAS:
            boton, badge = admin_estilo.boton_seccion(nombre, icono)
            badge.hide()
            boton.clicked.connect(lambda _c, k=clave: self._elegir_categoria(k))
            lay_lista.addWidget(boton)
            self._botones_nav[clave] = boton
        lay.addWidget(lista)

        bloque_filtros = admin_estilo.bloque_caja("Filtros")
        bloque_filtros.layout().addWidget(admin_estilo.etiqueta_caja("Mostrar"))
        self.combo_filtro = ComboTarjeta("Mostrar")
        self.combo_filtro.setStyleSheet(_ESTILO_COMBO)
        self.combo_filtro.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_filtro.currentIndexChanged.connect(lambda _i: self._pintar_tabla())
        bloque_filtros.layout().addWidget(self.combo_filtro)
        lay.addWidget(bloque_filtros)

        bloque_acciones = admin_estilo.bloque_caja("Acciones")
        self.btn_exportar = admin_estilo.boton_accion("Exportar a Excel", 'fa5s.file-excel')
        self.btn_exportar.clicked.connect(lambda: self.table.export_to_excel(_TEXTOS[self._cat]['titulo']))
        self.btn_recargar = admin_estilo.boton_accion("Actualizar", 'fa5s.sync-alt')
        self.btn_recargar.clicked.connect(self.load_data)
        bloque_acciones.layout().addWidget(self.btn_exportar)
        bloque_acciones.layout().addWidget(self.btn_recargar)
        lay.addWidget(bloque_acciones)
        lay.addStretch(1)
        nota = QLabel("Forma de contrato, estados y tipo de facturación no se editan aquí: las reglas del negocio dependen de sus valores exactos.")
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 10px; background: transparent; border: none; padding: 8px 12px;")
        lay.addWidget(nota)
        self._botones_nav[self._cat].setChecked(True)
        return caja.marco

    def _crear_caja_tabla(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaTablaCatalogos", "Ejecutivos", "")
        self.table = VolvoTableWidget()
        self.table.menu_type = "solo_lectura"
        admin_estilo.estilar_tabla(self.table)
        self.model = ModeloTablaIngresos(
            resolver=self._color_celda, columnas_negrita=("EJECUTIVO",),
            alineacion=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.set_model_and_delegate(self.model)
        self.table.sort_changed.connect(self._pintar_tabla)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._actualizar_panel())
        self._caja.cuerpo.addWidget(self.table, 1)
        return self._caja.marco

    def _crear_caja_detalle(self):
        self._det = admin_estilo.caja_con_encabezado("cajaDetalleCatalogos", "Detalle", "")
        self._det.marco.setFixedWidth(340)
        self.btn_agregar_cab = QPushButton("  Agregar")
        self.btn_agregar_cab.setIcon(ThemeManager.icon('fa5s.plus', color="white"))
        self.btn_agregar_cab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_agregar_cab.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.45); "
            "border-radius: 10px; padding: 6px 14px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: rgba(255,255,255,0.25); }")
        self.btn_agregar_cab.clicked.connect(self._abrir_alta)
        self._det.fila_cab.addWidget(self.btn_agregar_cab)
        self.panel = PanelCatalogo()
        self.panel.agregar.connect(self._on_agregar)
        self.panel.cancelar_alta.connect(self._cerrar_alta)
        self.panel.guardar_ejecutivo.connect(self._on_guardar_ejecutivo)
        self.panel.alternar_activo.connect(self._on_alternar_activo)
        self.panel.eliminar.connect(self._on_eliminar)
        self.panel.guardar_traduccion.connect(self._on_guardar_traduccion)
        self.panel.guardar_precio.connect(self._on_guardar_precio)
        self.panel.guardar_nombre.connect(self._on_guardar_nombre_complemento)
        self.panel.editar_precios.connect(self._on_editar_precios)
        self.panel.quitar_traduccion.connect(self._on_quitar_traduccion)
        self.panel.abrir_cartera.connect(self._on_abrir_cartera)
        self.panel.aplicar_reasignar.connect(self._on_aplicar_reasignar)
        self.panel.aplicar_asignar.connect(self._on_aplicar_asignar)
        self.panel.aplicar_eliminar.connect(self._on_aplicar_eliminar)
        self.panel.volver_detalle.connect(self._volver_al_detalle)
        self.panel.cerrar_listo.connect(lambda: self._volver_al_detalle(self._nombre_tras_listo))
        self._det.cuerpo.addWidget(self.panel, 1)
        return self._det.marco

    def _color_celda(self, columna, valor, es_fondo):
        if es_fondo:
            return None
        if columna == "EJECUTIVO" and self.model.valor_fila_resuelta("ESTADO") == "Inactivo":
            return estilo_com.ROJO
        if columna == "ESTADO" and valor == "Inactivo":
            return estilo_com.APAGADO
        if columna == "ESTADO" and valor == _ESTADO_SIN_EJECUTIVO:
            return "#D98404"
        if (columna == "CORREO" and valor == _TEXTO_SIN_CORREO) or (columna == "ORIGEN" and valor == _ORIGEN_PENDIENTE) \
                or (columna == "PRECIO" and valor == _TEXTO_SIN_PRECIO) or (columna == "VALOR" and valor == _TEXTO_SIN_VALOR):
            return "#D98404"
        return None

    # ----------------------------------------------------- categoría actual
    def _elegir_categoria(self, clave):
        if clave == self._cat:
            self._botones_nav[clave].setChecked(True)
            return
        self._cat = clave
        for k, boton in self._botones_nav.items():
            boton.setChecked(k == clave)
        self._configurar_categoria()
        self._clave_panel = None
        self.table.clearSelection()
        self._pintar_tabla()

    def _configurar_categoria(self):
        cat = self._cat
        self._caja.lbl_titulo.setText(_TEXTOS[cat]['titulo'])
        self.btn_agregar_cab.setToolTip(f"Agregar {_TEXTOS[cat]['singular']}")
        self._modo_alta = False
        self.combo_filtro.blockSignals(True)
        self.combo_filtro.clear()
        self.combo_filtro.addItems(_FILTROS.get(cat, _FILTROS_VALORES))
        self.combo_filtro.blockSignals(False)
        self._mostrar_vacio()

    def _mostrar_vacio(self):
        articulo = "una" if self._cat in (INDUSTRIA, TRADUCCION) else "un"
        icono = next(i for c, _n, i in CATEGORIAS if c == self._cat)
        self._clave_panel = None
        self.panel.mostrar_vacio(icono, f"Selecciona {articulo} {_TEXTOS[self._cat]['singular']}",
                                 "Elige una fila de la tabla para ver su detalle y editarlo, o pulsa Agregar para crear "
                                 f"{'una nueva' if articulo == 'una' else 'uno nuevo'}.",
                                 _TEXTOS[self._cat]['singular'].capitalize())
        self._aplicar_titulo_panel()

    def _aplicar_titulo_panel(self):
        self.btn_agregar_cab.setVisible(not self._modo_alta)
        self._det.lbl_titulo.setText(self.panel.titulo[0])
        self._det.lbl_subtitulo.setText(self.panel.titulo[1])

    def _abrir_alta(self):
        self._modo_alta = True
        self._clave_panel = None
        self.table.clearSelection()
        self.panel.mostrar_alta(self._cat)
        self._aplicar_titulo_panel()

    def _cerrar_alta(self):
        self._modo_alta = False
        self._mostrar_vacio()

    # --------------------------------------------------------------- datos
    def load_data(self):
        self._data_dirty = False
        self._df_unidades = self.data_manager.get_comercial_df()
        self._pedir_provisiones()
        nombres = []
        if self._df_unidades is not None and not self._df_unidades.empty and 'EJECUTIVO' in self._df_unidades.columns:
            nombres = self._df_unidades['EJECUTIVO'].dropna().astype(str).tolist()
        try:
            ejecutivos_service.registrar_ejecutivos_nuevos(set(nombres))
        except Exception:
            pass
        self._directorio = ejecutivos_service.leer_ejecutivos()
        conteo, self._sin_ejecutivo = cartera_ejecutivos_service.conteo_por_ejecutivo(self._df_unidades, self._directorio)
        self._unidades = {EJECUTIVO: conteo}
        for cat in (MODELO, INDUSTRIA, SERVICIO, COMPLEMENTO):
            self._unidades[cat] = catalogos_service.unidades_por_valor(cat, self._df_unidades)
            self._filas[cat] = catalogos_service.filas_catalogo(cat)
        self._pendientes = catalogos_service.pendientes()
        self._clave_panel = None
        self._pintar_tabla()

    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def _on_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def _tabla_ejecutivos(self):
        d = self._directorio
        if d.empty:
            return pd.DataFrame(columns=_COLUMNAS[EJECUTIVO])
        activo = d['activo'].str.strip().str.upper() != 'NO'
        tabla = pd.DataFrame({
            "EJECUTIVO": d['nombre'],
            "CORREO": d['correo'].where(d['correo'].str.strip() != '', _TEXTO_SIN_CORREO),
            "UNIDADES": d['id_ejecutivo'].map(lambda i: self._unidades[EJECUTIVO].get(i, 0)),
            "ESTADO": activo.map({True: "Activo", False: "Inactivo"}),
        })
        if self._sin_ejecutivo:
            tabla.loc[len(tabla)] = [ejecutivos_service.NOMBRE_DESCONOCIDO, "-", self._sin_ejecutivo, _ESTADO_SIN_EJECUTIVO]
        orden_estado = {"Activo": 0, "Inactivo": 1, _ESTADO_SIN_EJECUTIVO: 2}
        clave = pd.DataFrame({"e": tabla["ESTADO"].map(orden_estado),
                              "n": tabla["EJECUTIVO"].map(ejecutivos_service.normalizar_nombre)})
        return tabla.loc[clave.sort_values(["e", "n"], kind="stable").index].reset_index(drop=True)

    def _pedir_provisiones(self):
        """Los precios salen de provisionFelipe: si aún no se cargó (no se ha abierto Provisiones), se pide en segundo plano."""
        try:
            if not self.data_manager.get_costos() and not self._provisiones_pedidas:
                self._provisiones_pedidas = True
                self.data_manager.load_provisiones_async()
        except Exception:
            pass

    def _on_provisiones(self):
        if self._cat not in (SERVICIO, COMPLEMENTO):
            return
        fila = self._fila_seleccionada()
        self._reseleccionar = str(fila.iloc[0]) if fila is not None else None
        self._clave_panel = None
        self._pintar_tabla()

    def _on_editar_precios(self):
        """Abre la misma ventana de costos de Provisiones (UF, CIV y multiplicador de cada plan)."""
        from PyQt6.QtWidgets import QDialog
        from src.ui.provisiones import CostosDialog
        if CostosDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._provisiones_pedidas = False
            self._pedir_provisiones()
            self._on_provisiones()

    def _precios_planes(self):
        """Planes de la hoja Planes de las provisiones (nombre en mayúsculas -> {uf_mult, clp})."""
        try:
            planes = {str(p['nombre']).strip().upper(): p for p in self.data_manager.get_costos()}
        except Exception:
            planes = {}
        for nombre, plan in self._precios_locales.items():
            if not (planes.get(nombre) or {}).get('uf_mult'):
                planes[nombre] = plan
        return planes

    @staticmethod
    def _texto_precio(plan):
        if not plan or not plan.get('uf_mult'):
            return _TEXTO_SIN_PRECIO
        return f"{plan['uf_mult']:g} UF · ${int(plan['clp']):,}".replace(",", ".")

    def _lineas_precio(self, valor):
        """Precio del plan base, con CIV y con Safety Zone (si algún día la hoja Planes lo trae)."""
        planes = self._precios_planes()
        if not planes:
            return [("Precios", "Provisiones sin cargar", None)]
        clave = valor.upper()
        lineas = []
        for etiqueta, plan in (("Plan base", planes.get(clave)), ("Con CIV", planes.get(clave + " + CIV"))):
            texto = self._texto_precio(plan)
            lineas.append((etiqueta, texto, "#D98404" if texto == _TEXTO_SIN_PRECIO else None))
        sz = [p for k, p in planes.items() if k.startswith(clave) and ("SAFETY" in k or " SZ" in k)]
        if sz:
            lineas += [(p['nombre'], self._texto_precio(p), None) for p in sz]
        else:
            lineas.append(("Safety Zone", "Sin valor definido", estilo_com.APAGADO))
        try:
            civ = self.data_manager.get_variables()[1]
        except Exception:
            civ = 0
        if civ:
            lineas.append(("Suma del CIV", f"+{float(civ):g} UF", None))
        return lineas

    def _datos_precio(self, valor):
        planes = self._precios_planes()
        try:
            uf = float(self.data_manager.get_variables()[0])
        except Exception:
            uf = 0.0
        base = planes.get(valor.upper())
        fila = next((f for f in self._filas[SERVICIO] if f['valor'] == valor), {})
        mult = f"{base['uf_mult']:g}" if base and base.get('uf_mult') else (fila.get('extra') or "")
        return dict(lineas=self._lineas_precio(valor), editable=not catalogos_service.es_de_fabrica(SERVICIO, valor),
                    mult=mult.replace('.', ','), uf=uf)

    def _texto_valor_complemento(self, codigo):
        """Valor en UF del complemento según la hoja Variables de provisionFelipe ('-' si aún no se cargó)."""
        try:
            if not self.data_manager.get_costos():
                return "-"
            valor = float(self.data_manager.get_valores_complemento().get(codigo.upper(), 0.0))
        except Exception:
            return "-"
        return f"{valor:g} UF".replace('.', ',') if valor > 0 else _TEXTO_SIN_VALOR

    def _tabla_valores(self, cat):
        columna = _TEXTOS[cat]['columna']
        planes = self._precios_planes() if cat == SERVICIO else {}
        filas = []
        for f in self._filas[cat]:
            fila = {columna: f['valor'], "UNIDADES": self._unidades[cat].get(catalogos_service._clave(f['valor']), 0),
                    "ESTADO": "Activo" if f['activo'] else "Inactivo"}
            if cat == SERVICIO:
                fila["PRECIO"] = self._texto_precio(planes.get(f['valor'].upper())) if planes else "-"
            if cat == COMPLEMENTO:
                fila["NOMBRE"] = f['extra'] or f['valor']
                fila["VALOR"] = self._texto_valor_complemento(f['valor'])
            filas.append(fila)
        return pd.DataFrame(filas, columns=_COLUMNAS[cat])

    def _tabla_traducciones(self):
        filas = [{"TEXTO DEL POWER BI": p['texto'], "SE TRADUCE A": "-", "ORIGEN": _ORIGEN_PENDIENTE, "UNIDADES": str(p['unidades'])}
                 for p in self._pendientes]
        usadas = self._unidades.get(INDUSTRIA, {})
        filas += [{"TEXTO DEL POWER BI": t['texto'], "SE TRADUCE A": t['destino'],
                   "ORIGEN": _ORIGEN_EQUIPO if t['propia'] else _ORIGEN_FABRICA,
                   "UNIDADES": str(usadas.get(catalogos_service._clave(t['destino']), 0))}
                  for t in catalogos_service.traducciones()]
        return pd.DataFrame(filas, columns=_COLUMNAS[TRADUCCION])

    def _tabla_completa(self):
        if self._cat == EJECUTIVO:
            return self._tabla_ejecutivos()
        if self._cat == TRADUCCION:
            return self._tabla_traducciones()
        return self._tabla_valores(self._cat)

    def _aplicar_filtro(self, df):
        if df.empty:
            return df
        opcion = self.combo_filtro.currentText()
        if self._cat == EJECUTIVO:
            if opcion == "Sin correo":
                return df[(df["CORREO"] == _TEXTO_SIN_CORREO) & (df["ESTADO"] == "Activo")]
            if opcion == "Inactivos":
                return df[df["ESTADO"] == "Inactivo"]
        elif self._cat == TRADUCCION:
            if opcion in (_ORIGEN_PENDIENTE, _ORIGEN_EQUIPO, _ORIGEN_FABRICA):
                return df[df["ORIGEN"] == opcion]
        else:
            if opcion == "Activos":
                return df[df["ESTADO"] == "Activo"]
            if opcion == "Inactivos":
                return df[df["ESTADO"] == "Inactivo"]
        return df

    def _actualizar_subtitulo(self, completa):
        n = len(completa)
        if self._cat == EJECUTIVO:
            n -= int((completa["ESTADO"] == _ESTADO_SIN_EJECUTIVO).sum()) if n else 0
            sin_correo = int(((completa["CORREO"] == _TEXTO_SIN_CORREO) & (completa["ESTADO"] == "Activo")).sum()) if n else 0
            texto = f"{n} ejecutivos · {sin_correo} sin correo"
        elif self._cat == TRADUCCION:
            texto = f"{n} traducciones · {len(self._pendientes)} por traducir"
        else:
            activos = int((completa["ESTADO"] == "Activo").sum()) if n else 0
            texto = f"{n} valores · {activos} activos"
        self._caja.lbl_subtitulo.setText(texto)

    def _pintar_tabla(self):
        completa = self._tabla_completa()
        self._actualizar_subtitulo(completa)
        df = self._aplicar_filtro(completa)
        texto = self.search_input.text().strip().lower()
        if texto and not df.empty:
            mascara = df.astype(str).apply(lambda col: col.str.lower().str.contains(texto, regex=False)).any(axis=1)
            df = df[mascara]
        self.df_tabla = self.table.apply_sort(df).reset_index(drop=True)
        self.model.set_data(self.df_tabla)
        columnas = list(self.df_tabla.columns)
        admin_estilo.fijar_columnas(self.table, {n: _ANCHOS[n] for n in columnas[1:]}, columnas[0])
        if self._reseleccionar is not None:
            clave, self._reseleccionar = self._reseleccionar, None
            primera = self.df_tabla.columns[0]
            coincide = self.df_tabla.index[self.df_tabla[primera].astype(str) == str(clave)]
            if len(coincide):
                self.table.selectRow(int(coincide[0]))
        self._actualizar_panel()

    def filter_table(self):
        self._pintar_tabla()

    # ------------------------------------------------------------ panel
    def _fila_seleccionada(self):
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if len(filas) != 1 or not (0 <= filas[0] < len(self.df_tabla)):
            return None
        return self.df_tabla.iloc[filas[0]]

    def _actualizar_panel(self):
        self.btn_exportar.setEnabled(not self.df_tabla.empty)
        fila = self._fila_seleccionada()
        if fila is None:
            if not self._modo_alta and self._clave_panel is not None:
                self._mostrar_vacio()
            return
        clave = (self._cat, str(fila.iloc[0]))
        if clave != self._clave_panel:
            self._clave_panel = clave
            self._modo_alta = False
            self._cargar_panel(fila)
            self._aplicar_titulo_panel()

    def _cargar_panel(self, fila):
        cat = self._cat
        if cat == EJECUTIVO:
            if fila["ESTADO"] == _ESTADO_SIN_EJECUTIVO:
                cartera_ejecutivos.mostrar_desconocido(self.panel, int(fila["UNIDADES"]))
                return
            coincide = self._directorio[self._directorio['nombre'] == fila["EJECUTIVO"]]
            if coincide.empty:
                return
            self.panel.mostrar_ejecutivo(coincide.iloc[0].to_dict(), int(fila["UNIDADES"]))
        elif cat == TRADUCCION:
            unidades = int(fila["UNIDADES"]) if str(fila["UNIDADES"]).isdigit() else 0
            self.panel.mostrar_traduccion(fila["TEXTO DEL POWER BI"], fila["SE TRADUCE A"], fila["ORIGEN"], unidades,
                                          catalogos_service.valores(INDUSTRIA))
        elif cat == COMPLEMENTO:
            codigo = fila.iloc[0]
            self.panel.mostrar_complemento(codigo, fila["NOMBRE"], fila["ESTADO"] == "Activo", int(fila["UNIDADES"]),
                                           fila["VALOR"], catalogos_service.es_de_fabrica(COMPLEMENTO, codigo))
        else:
            valor = fila.iloc[0]
            precios = self._datos_precio(valor) if cat == SERVICIO else None
            self.panel.mostrar_valor(cat, valor, fila["ESTADO"] == "Activo", int(fila["UNIDADES"]), precios)

    # ----------------------------------------------------------- acciones
    def _aviso_error(self, mensaje):
        QMessageBox.warning(self, "No se pudo guardar", mensaje)

    def _tras_guardar(self, reseleccionar=None):
        self._reseleccionar = reseleccionar
        self.load_data()

    def _on_agregar(self, a, b):
        cat = self._cat
        if cat == EJECUTIVO:
            ok, mensaje = ejecutivos_service.agregar_ejecutivo(a, b)
        elif cat == TRADUCCION:
            ok, mensaje = catalogos_service.guardar_traduccion(a, b)
        elif cat == COMPLEMENTO:
            ok, mensaje = catalogos_service.agregar_complemento(a, b)
        else:
            ok, mensaje = catalogos_service.agregar_valor(cat, a)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._modo_alta = False
        nuevo = ' '.join(a.split())
        if cat in (TRADUCCION, COMPLEMENTO):
            nuevo = nuevo.upper()
        self._tras_guardar(nuevo)

    def _on_guardar_nombre_complemento(self, codigo, nombre):
        ok, mensaje = catalogos_service.guardar_nombre_complemento(codigo, nombre)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar(codigo)

    def _on_guardar_ejecutivo(self, id_ejecutivo, nombre, correo, alias, activo):
        ok, mensaje = ejecutivos_service.actualizar_ejecutivo(id_ejecutivo, nombre, correo, alias, activo)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar(' '.join(nombre.split()))

    def _on_alternar_activo(self, valor, activar):
        ok, mensaje = catalogos_service.cambiar_activo(self._cat, valor, activar)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar(valor)

    def _on_eliminar(self, valor):
        respuesta = QMessageBox.question(
            self, "Eliminar valor", f"¿Eliminar «{valor}» del catálogo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        ok, mensaje = catalogos_service.eliminar_valor(self._cat, valor)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar()

    def _on_guardar_precio(self, valor, texto):
        try:
            mult = provisiones_services.parsear_numero_uf(texto)
        except ValueError:
            self._aviso_error("Escribe solo números (ej: 0,28).")
            return
        if mult <= 0:
            self._aviso_error("El multiplicador debe ser mayor que cero.")
            return
        ruta = config.settings.PROVISION_EXCEL_PATH
        if not ruta or not __import__('os').path.exists(ruta):
            self._aviso_error("No se encontró el Excel de provisiones configurado.")
            return
        escritor = ExcelWriter()
        escritor._crear_backup(ruta)
        if not escritor.last_backup_ok:
            self._aviso_error("No se pudo crear la copia de seguridad de provisionFelipe.xlsx. No se hizo ningún cambio.")
            return
        dm = self.data_manager
        try:
            dm.is_app_saving = True
            dm.save_timestamp = time.time()
            ok = provisiones_services.escribir_plan_en_planes(ruta, valor, mult)
        except PermissionError:
            self._aviso_error("El archivo de provisiones está abierto en Excel. Ciérralo y vuelve a intentar.")
            return
        except Exception as e:
            self._aviso_error(f"No se pudo escribir la hoja Planes: {e}")
            return
        if not ok:
            self._aviso_error("El Excel de provisiones no tiene la hoja Planes.")
            return
        ok, mensaje = catalogos_service.guardar_precio_servicio(valor, mult)
        if not ok:
            self._aviso_error(mensaje)
            return
        try:
            uf = float(dm.get_variables()[0])
            civ = float(dm.get_variables()[1])
        except Exception:
            uf, civ = 0.0, 0.0
        self._precios_locales[valor.upper()] = {'nombre': valor, 'uf_mult': mult, 'clp': round(mult * uf)}
        self._precios_locales[f"{valor} + CIV".upper()] = {'nombre': f"{valor} + CIV", 'uf_mult': mult + civ,
                                                           'clp': round((mult + civ) * uf)}
        try:
            dm.load_provisiones_async()
        except Exception:
            pass
        self._tras_guardar(valor)

    def _on_guardar_traduccion(self, texto, destino):
        ok, mensaje = catalogos_service.guardar_traduccion(texto, destino)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar(texto.upper())

    def _on_quitar_traduccion(self, texto):
        ok, mensaje = catalogos_service.quitar_traduccion(texto)
        if not ok:
            self._aviso_error(mensaje)
            return
        self._tras_guardar()

    # ------------------------------------------------ cartera de ejecutivos
    def _ejecutivo_por_id(self, id_ejecutivo):
        if id_ejecutivo == '':
            return {'id_ejecutivo': '', 'nombre': ejecutivos_service.NOMBRE_DESCONOCIDO, 'correo': '', 'alias': '', 'activo': 'SI'}
        coincide = self._directorio[self._directorio['id_ejecutivo'] == id_ejecutivo]
        return coincide.iloc[0].to_dict() if not coincide.empty else None

    def _nombre_de(self, id_ejecutivo):
        ejecutivo = self._ejecutivo_por_id(id_ejecutivo)
        return ejecutivo['nombre'] if ejecutivo else None

    def _on_abrir_cartera(self, vista, id_ejecutivo):
        ejecutivo = self._ejecutivo_por_id(id_ejecutivo)
        if ejecutivo is None:
            return
        self._id_en_cartera = id_ejecutivo
        df, directorio = self._df_unidades, self._directorio
        if vista == 'reasignar':
            cartera = cartera_ejecutivos_service.cartera(df, id_ejecutivo, directorio)
            activos = directorio[(directorio['activo'].str.strip().str.upper() != 'NO') & (directorio['id_ejecutivo'] != id_ejecutivo)]
            destinos = [(fila['nombre'], self._unidades[EJECUTIVO].get(fila['id_ejecutivo'], 0)) for _i, fila in activos.iterrows()]
            cartera_ejecutivos.mostrar_reasignar(self.panel, ejecutivo, cartera, destinos, _ESTILO_COMBO)
        elif vista == 'asignar':
            clientes = cartera_ejecutivos_service.clientes_para_asignar(df, directorio)
            cartera_ejecutivos.mostrar_asignar(
                self.panel, ejecutivo, clientes,
                lambda cliente, solo: len(cartera_ejecutivos_service.contratos_a_asignar(df, cliente, solo, directorio)))
        else:
            cartera_ejecutivos.mostrar_eliminar(self.panel, ejecutivo, self._unidades[EJECUTIVO].get(id_ejecutivo, 0))
        self._aplicar_titulo_panel()

    def _volver_al_detalle(self, nombre=None):
        """Vuelve a la ficha del ejecutivo (o la cierra si ya no existe) releyendo la tabla."""
        nombre = nombre or self._nombre_de(self._id_en_cartera)
        self._reseleccionar = nombre
        self._clave_panel = None
        self._pintar_tabla()
        if self._fila_seleccionada() is None:
            self._mostrar_vacio()

    def _guardar_cartera(self, cambios, modulo, al_terminar):
        """Guarda los cambios de ejecutivo en el registro maestro (un solo guardado, con respaldo e historial)."""
        if not cambios:
            self._aviso_error("No hay contratos para cambiar.")
            self._volver_al_detalle()
            return
        self._hilo_cartera = SaveExcelThread(ExcelWriter(), cambios, module_name=modulo)
        self._hilo_cartera.finished_signal.connect(lambda ok: self._tras_guardar_cartera(ok, cambios, al_terminar))
        self._hilo_cartera.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._hilo_cartera.start()

    def _tras_guardar_cartera(self, ok, cambios, al_terminar):
        if not ok:
            QMessageBox.critical(self, "Error", "No se pudo guardar el cambio de ejecutivo en el Registro Maestro. "
                                 "No se modificó ningún contrato.")
            self._volver_al_detalle()
            return
        dm = self.data_manager
        if not dm.df_master.empty:
            pendientes = {(clave if data.get('ID') else str(data['VIN']).strip().upper()):
                          {'cambios': data['cambios'], 'ID': data.get('ID')} for clave, data in cambios.items()}
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, pendientes)
            self._data_dirty = True
            dm.data_ready.emit()
        self.refresh_if_dirty()
        al_terminar()

    def _mostrar_listo(self, mensaje, nombre):
        self._nombre_tras_listo = nombre
        cartera_ejecutivos.mostrar_listo(self.panel, mensaje)
        self._aplicar_titulo_panel()

    def _on_aplicar_reasignar(self, id_origen, clientes, destino):
        origen = self._nombre_de(id_origen)
        cambios = cartera_ejecutivos_service.plan_reasignar(
            self._df_unidades, id_origen, clientes, destino, self._directorio)
        n = len(cambios)

        def listo():
            resto = self._sin_ejecutivo if id_origen == '' else self._unidades[EJECUTIVO].get(id_origen, 0)
            self._mostrar_listo(f"<b>{_miles(n)} contratos</b> pasaron de {origen} a {destino}. {origen} queda con "
                                f"<b>{_miles(resto)}</b>.", origen)
        self._guardar_cartera(cambios, "Catálogos (reasignar cartera)", listo)

    def _on_aplicar_asignar(self, destino, cliente, solo_sin_activo):
        cambios = cartera_ejecutivos_service.plan_asignar_cliente(
            self._df_unidades, cliente, destino, solo_sin_activo, self._directorio)
        n = len(cambios)

        def listo():
            self._mostrar_listo(f"<b>{_miles(n)} {'contrato' if n == 1 else 'contratos'}</b> de «{cliente}» ahora son de "
                                f"{destino}.", destino)
        self._guardar_cartera(cambios, "Catálogos (asignar cliente)", listo)

    def _on_aplicar_eliminar(self, id_ejecutivo):
        ejecutivo = self._ejecutivo_por_id(id_ejecutivo)
        if ejecutivo is None:
            return
        cambios = cartera_ejecutivos_service.plan_eliminar(self._df_unidades, id_ejecutivo, self._directorio)
        n = len(cambios)

        def quitar():
            ok, mensaje = ejecutivos_service.eliminar_ejecutivo(id_ejecutivo)
            if not ok:
                self._aviso_error(mensaje)
                self._volver_al_detalle()
                return
            self.load_data()
            texto = f"«{ejecutivo['nombre']}» se eliminó del catálogo."
            if n:
                texto += f" Sus <b>{_miles(n)} contratos</b> quedaron con el ejecutivo <b>Desconocido</b>."
            self._mostrar_listo(texto, None)
        if n:
            self._guardar_cartera(cambios, "Catálogos (eliminar ejecutivo)", quitar)
        else:
            quitar()
