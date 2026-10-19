"""Administración de ejecutivos: directorio nombre -> correo (Ejecutivos_VC.csv)
que usa la acción "Contactar ejecutivo" de Operaciones. Permite agregar,
editar y desactivar; al renombrar se conserva el nombre anterior como alias
para que PruebasFM no pierda la relación. No modifica PruebasFM."""
import pandas as pd
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit, QDialog,
                             QCheckBox, QFrame, QMessageBox, QScrollArea, QSizePolicy)

from src.core.data_manager import DataManager
from src.services import ejecutivos_service
from src.theme.theme_manager import ThemeManager
from src.ui import admin_estilo, admin_listas, comercial_estilo as estilo_com

SUBTABS = ("Todos", "Sin correo", "Inactivos")
COLUMNAS = ["ID", "EJECUTIVO", "CORREO", "ALIAS", "UNIDADES", "ESTADO"]
_TEXTO_SIN_CORREO = "Sin correo"


class DialogoEjecutivo(QDialog):
    """Alta y edición de un ejecutivo."""

    def __init__(self, parent=None, ejecutivo=None):
        super().__init__(parent)
        self.ejecutivo = ejecutivo
        self.setWindowTitle("Editar ejecutivo" if ejecutivo else "Agregar ejecutivo")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaDialogoEjecutivo")
        tarjeta.setStyleSheet(estilo_com.qss_tarjeta("tarjetaDialogoEjecutivo"))
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)
        titulo = QLabel("Editar ejecutivo" if ejecutivo else "Agregar ejecutivo")
        titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 16px; font-weight: 800; border: none;")
        lay.addWidget(titulo)

        self.txt_nombre = QLineEdit()
        self.txt_nombre.setPlaceholderText("Tal como aparece en PruebasFM (ej. Andres Muestra)")
        self.txt_correo = QLineEdit()
        self.txt_correo.setPlaceholderText("nombre.apellido@example.com")
        self.txt_alias = QLineEdit()
        self.txt_alias.setPlaceholderText("Otras grafías del nombre, separadas por |")
        self.chk_activo = QCheckBox("Ejecutivo activo")
        self.chk_activo.setChecked(True)
        for etiqueta, campo in (("Nombre", self.txt_nombre), ("Correo", self.txt_correo), ("Alias", self.txt_alias)):
            lbl = QLabel(etiqueta.upper())
            lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 10px; font-weight: 800; letter-spacing: 1px; border: none;")
            lay.addWidget(lbl)
            lay.addWidget(campo)
        lay.addWidget(self.chk_activo)

        self.lbl_aviso = QLabel("")
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; border: none;")
        lay.addWidget(self.lbl_aviso)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet(f"color: {estilo_com.ROJO}; font-size: 12px; font-weight: 700; border: none;")
        self.lbl_error.hide()
        lay.addWidget(self.lbl_error)

        botones = QHBoxLayout()
        botones.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        ThemeManager.apply_secondary_button(btn_cancelar)
        btn_cancelar.clicked.connect(self.reject)
        self.btn_guardar = QPushButton("Guardar")
        ThemeManager.apply_primary_button(self.btn_guardar)
        self.btn_guardar.clicked.connect(self._guardar)
        botones.addWidget(btn_cancelar)
        botones.addWidget(self.btn_guardar)
        lay.addLayout(botones)
        raiz.addWidget(tarjeta)

        if ejecutivo:
            self.txt_nombre.setText(ejecutivo['nombre'])
            self.txt_correo.setText(ejecutivo['correo'])
            self.txt_alias.setText(ejecutivo['alias'])
            self.chk_activo.setChecked(str(ejecutivo['activo']).strip().upper() != 'NO')
            self.txt_nombre.textChanged.connect(self._avisar_renombre)

    def _avisar_renombre(self, texto):
        cambio = ejecutivos_service.normalizar_nombre(texto) != ejecutivos_service.normalizar_nombre(self.ejecutivo['nombre'])
        self.lbl_aviso.setText(
            f"El nombre anterior ({self.ejecutivo['nombre']}) se guardará como alias. "
            "PruebasFM no se modifica." if cambio and texto.strip() else "")

    def _guardar(self):
        nombre, correo, alias = self.txt_nombre.text(), self.txt_correo.text(), self.txt_alias.text()
        if self.ejecutivo:
            ok, mensaje = ejecutivos_service.actualizar_ejecutivo(
                self.ejecutivo['id_ejecutivo'], nombre, correo, alias, self.chk_activo.isChecked())
        else:
            ok, mensaje = ejecutivos_service.agregar_ejecutivo(nombre, correo, alias)
            if ok and not self.chk_activo.isChecked():
                nuevo = ejecutivos_service.buscar_ejecutivo(nombre, incluir_inactivos=True)
                if nuevo:
                    ejecutivos_service.actualizar_ejecutivo(nuevo['id_ejecutivo'], nombre, correo, alias, False)
        if ok:
            self.accept()
        else:
            self.lbl_error.setText(mensaje)
            self.lbl_error.show()


class TarjetaEjecutivo(QFrame):
    """Un ejecutivo: iniciales, nombre, correo, alias y unidades a su cargo.
    Un clic la selecciona y un doble clic la abre para editar."""
    seleccionada = pyqtSignal(str)
    editar_pedido = pyqtSignal(str)

    def __init__(self, fila, parent=None):
        super().__init__(parent)
        self._id = str(fila["ID"])
        self._advertir = fila["CORREO"] == _TEXTO_SIN_CORREO and fila["ESTADO"] == "Activo"
        self._inactivo = fila["ESTADO"] == "Inactivo"
        self.setObjectName("tarjetaEjecutivo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(66)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(12)
        tono = "gris" if self._inactivo else ("ambar" if self._advertir else "azul")
        lay.addWidget(admin_listas.avatar(estilo_com.iniciales(fila["EJECUTIVO"]), tono))
        textos = QVBoxLayout()
        textos.setSpacing(1)
        nombre = admin_listas.texto(fila["EJECUTIVO"], tam=13, negrita=True)
        nombre.setToolTip(str(fila["EJECUTIVO"]))
        textos.addWidget(nombre)
        correo = admin_listas.texto("Falta el correo" if self._advertir else fila["CORREO"],
                                    color=estilo_com.AMBAR if self._advertir else estilo_com.APAGADO, tam=12)
        textos.addWidget(correo)
        alias = None
        if fila["ALIAS"] != "-":
            alias = admin_listas.texto(f"Alias: {fila['ALIAS']}", color=estilo_com.APAGADO, tam=11)
            textos.addWidget(alias)
        for lbl in (nombre, correo, alias):
            if lbl is not None:
                lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        correo.setToolTip(str(fila["CORREO"]))
        lay.addLayout(textos, 1)
        derecha = QVBoxLayout()
        derecha.setSpacing(0)
        derecha.addWidget(admin_listas.texto(fila["UNIDADES"], tam=14, negrita=True), alignment=Qt.AlignmentFlag.AlignRight)
        derecha.addWidget(admin_listas.texto("unidades", color=estilo_com.APAGADO, tam=10), alignment=Qt.AlignmentFlag.AlignRight)
        if self._inactivo:
            derecha.addWidget(admin_listas.pildora("Inactivo", "gris"), alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(derecha)
        self.marcar(False)

    def marcar(self, activa):
        borde = estilo_com.AZUL if activa else (
            "#E9C46A" if self._advertir else estilo_com.LINEA)
        fondo = "#FFF8E8" if self._advertir and not activa else (estilo_com.PRIMARIO_SUAVE if activa else estilo_com.SUPERFICIE)
        self.setStyleSheet(
            f"QFrame#tarjetaEjecutivo {{ background: {fondo}; border: {2 if activa else 1}px solid {borde}; border-radius: 12px; }}")

    def mousePressEvent(self, event):
        self.seleccionada.emit(self._id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.editar_pedido.emit(self._id)


class EjecutivosModule(QWidget):
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.df_directorio = pd.DataFrame()
        self.df_tabla = pd.DataFrame()
        self._tarjetas = {}
        self._id_seleccionado = None
        self._unidades = {}
        self._data_dirty = False

        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()
        self.data_manager.data_ready.connect(self._on_data_ready)
        self.load_data()

    # ------------------------------------------------------------ interfaz
    def _setup_ui(self):
        layout = admin_estilo.raiz_pantalla(self)

        contenedor_tabs, self.subtabs, self._badges = admin_estilo.subpestanas(SUBTABS)
        self.subtabs.currentChanged.connect(lambda _i: self._pintar_tabla())
        layout.addWidget(contenedor_tabs)
        admin_estilo.animar_subpestanas(self, self.subtabs)

        self._barra = admin_estilo.barra_opciones('fa5s.user-tie', "Ejecutivos", "")
        layout.addWidget(self._barra.marco)

        self.btn_agregar = admin_estilo.boton_capsula(self._barra, 'fa5s.plus', "Agregar ejecutivo")
        self.btn_agregar.clicked.connect(self._on_agregar)
        self.btn_editar = admin_estilo.boton_capsula(self._barra, 'fa5s.edit', "Editar ejecutivo seleccionado")
        self.btn_editar.clicked.connect(self._on_editar)
        self.btn_activo = admin_estilo.boton_capsula(self._barra, 'fa5s.user-slash', "Desactivar ejecutivo seleccionado")
        self.btn_activo.clicked.connect(self._on_alternar_activo)
        self.btn_exportar = admin_estilo.boton_capsula(self._barra, 'fa5s.file-excel', "Exportar a Excel")
        self.btn_exportar.clicked.connect(lambda: admin_estilo.exportar_excel(self, self.df_tabla, "Ejecutivos"))
        self.btn_recargar = admin_estilo.boton_capsula(self._barra, 'fa5s.sync-alt', "Recargar")
        self.btn_recargar.clicked.connect(self.load_data)

        marco, capas = admin_estilo.tarjeta_contenido("tarjetaEjecutivos")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        self.scroll.viewport().setAutoFillBackground(False)
        self._contenido = QWidget()
        self._contenido.setObjectName("gridEjecutivos")
        self._contenido.setStyleSheet("QWidget#gridEjecutivos { background: transparent; }")
        self._grid = QGridLayout(self._contenido)
        self._grid.setContentsMargins(14, 14, 14, 14)
        self._grid.setSpacing(10)
        self.scroll.setWidget(self._contenido)
        self.scroll.viewport().installEventFilter(self)
        capas.addWidget(self.scroll, 1)
        layout.addWidget(marco, 1)
        self._actualizar_botones()

    # --------------------------------------------------------------- datos
    def load_data(self):
        self._data_dirty = False
        df_unidades = self.data_manager.get_comercial_df()
        nombres = []
        if df_unidades is not None and not df_unidades.empty and 'EJECUTIVO' in df_unidades.columns:
            nombres = df_unidades['EJECUTIVO'].dropna().astype(str).tolist()
        try:
            ejecutivos_service.registrar_ejecutivos_nuevos(set(nombres))
        except Exception:
            pass
        self.df_directorio = ejecutivos_service.leer_ejecutivos()
        self._unidades = ejecutivos_service.unidades_por_ejecutivo(nombres, self.df_directorio)
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

    def _tabla_completa(self):
        d = self.df_directorio
        if d.empty:
            return pd.DataFrame(columns=COLUMNAS)
        activo = d['activo'].str.strip().str.upper() != 'NO'
        return pd.DataFrame({
            "ID": d['id_ejecutivo'],
            "EJECUTIVO": d['nombre'],
            "CORREO": d['correo'].where(d['correo'].str.strip() != '', _TEXTO_SIN_CORREO),
            "ALIAS": d['alias'].str.replace('|', ', ', regex=False).where(d['alias'].str.strip() != '', '-'),
            "UNIDADES": d['id_ejecutivo'].map(lambda i: self._unidades.get(i, 0)),
            "ESTADO": activo.map({True: "Activo", False: "Inactivo"}),
        })

    def _filtrar_subtab(self, df, idx):
        if df.empty:
            return df
        if idx == 1:
            return df[(df["CORREO"] == _TEXTO_SIN_CORREO) & (df["ESTADO"] == "Activo")]
        if idx == 2:
            return df[df["ESTADO"] == "Inactivo"]
        return df

    def _actualizar_kpis_y_contadores(self):
        df = self._tabla_completa()
        activos = df[df["ESTADO"] == "Activo"] if not df.empty else df
        sin_correo = int((activos["CORREO"] == _TEXTO_SIN_CORREO).sum()) if not activos.empty else 0
        for i in range(len(SUBTABS)):
            admin_estilo.actualizar_contador(self.subtabs, self._badges, i, len(self._filtrar_subtab(df, i)))
        self._barra.lbl_subtitulo.setText(f"{len(df)} ejecutivos · {sin_correo} sin correo")

    def _pintar_tabla(self):
        df = self._filtrar_subtab(self._tabla_completa(), self.subtabs.currentIndex())
        texto = self.search_input.text().strip().lower()
        if texto and not df.empty:
            mascara = df.astype(str).apply(lambda col: col.str.lower().str.contains(texto, regex=False)).any(axis=1)
            df = df[mascara]
        self.df_tabla = df.reset_index(drop=True)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._tarjetas = {}
        for _, fila in self.df_tabla.iterrows():
            tarjeta = TarjetaEjecutivo(fila)
            tarjeta.seleccionada.connect(self._seleccionar)
            tarjeta.editar_pedido.connect(self._on_editar_tarjeta)
            self._tarjetas[str(fila["ID"])] = tarjeta
        if self._id_seleccionado not in self._tarjetas:
            self._id_seleccionado = None
        if self._id_seleccionado:
            self._tarjetas[self._id_seleccionado].marcar(True)
        self._vacio = None
        if not self._tarjetas:
            self._vacio = admin_listas.texto("No hay ejecutivos en esta lista.", color=estilo_com.APAGADO, tam=13, negrita=True)
        self._reflujo()
        self._actualizar_botones()

    def _reflujo(self):
        """Acomoda las tarjetas en tantas columnas como quepan."""
        while self._grid.count():
            self._grid.takeAt(0)
        if not self._tarjetas:
            if getattr(self, '_vacio', None) is not None:
                self._grid.addWidget(self._vacio, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
            return
        ancho = max(self.scroll.viewport().width() - 28, 300)
        columnas = max(1, ancho // 340)
        for i, tarjeta in enumerate(self._tarjetas.values()):
            self._grid.addWidget(tarjeta, i // columnas, i % columnas)
        for c in range(columnas):
            self._grid.setColumnStretch(c, 1)
        self._grid.setRowStretch(len(self._tarjetas) // columnas + 1, 1)

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize and self._tarjetas:
            self._reflujo()
        return super().eventFilter(obj, event)

    def filter_table(self):
        self._pintar_tabla()

    # ----------------------------------------------------------- acciones
    def _seleccionar(self, id_ejecutivo):
        if self._id_seleccionado in self._tarjetas:
            self._tarjetas[self._id_seleccionado].marcar(False)
        self._id_seleccionado = id_ejecutivo
        if id_ejecutivo in self._tarjetas:
            self._tarjetas[id_ejecutivo].marcar(True)
        self._actualizar_botones()

    def _on_editar_tarjeta(self, id_ejecutivo):
        self._seleccionar(id_ejecutivo)
        self._on_editar()

    def _ejecutivo_seleccionado(self):
        if not self._id_seleccionado:
            return None
        coincide = self.df_directorio[self.df_directorio['id_ejecutivo'] == self._id_seleccionado]
        return coincide.iloc[0].to_dict() if not coincide.empty else None

    def _actualizar_botones(self):
        ejecutivo = self._ejecutivo_seleccionado()
        self.btn_editar.setEnabled(ejecutivo is not None)
        self.btn_activo.setEnabled(ejecutivo is not None)
        activo = ejecutivo is None or str(ejecutivo['activo']).strip().upper() != 'NO'
        self.btn_activo.setIcon(ThemeManager.icon('fa5s.user-slash' if activo else 'fa5s.user-check', color='white'))
        self.btn_activo.setToolTip("Desactivar ejecutivo seleccionado" if activo else "Reactivar ejecutivo seleccionado")
        self.btn_exportar.setEnabled(not self.df_tabla.empty)

    def _on_agregar(self):
        if DialogoEjecutivo(self).exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def _on_editar(self):
        ejecutivo = self._ejecutivo_seleccionado()
        if ejecutivo and DialogoEjecutivo(self, ejecutivo).exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def _on_alternar_activo(self):
        ejecutivo = self._ejecutivo_seleccionado()
        if not ejecutivo:
            return
        activo = str(ejecutivo['activo']).strip().upper() != 'NO'
        ok, mensaje = ejecutivos_service.actualizar_ejecutivo(
            ejecutivo['id_ejecutivo'], ejecutivo['nombre'], ejecutivo['correo'], ejecutivo['alias'], not activo)
        if not ok:
            QMessageBox.warning(self, "No se pudo guardar", mensaje)
            return
        self.load_data()
