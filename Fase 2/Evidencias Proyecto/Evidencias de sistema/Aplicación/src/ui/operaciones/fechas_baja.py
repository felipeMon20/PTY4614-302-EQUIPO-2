"""Operaciones > Bajas > Fechas de baja: corrige la FECHA DE BAJA de contratos ya dados de baja (actuales o de historial), primero por flota y luego por contrato."""
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QPushButton, QApplication, QHeaderView
from PyQt6.QtCore import Qt, QDate, QTimer, QObject, QEvent
from src.core.constants import COL_FLOTA_VC, COL_FECHA_BAJA, COL_ID, COL_VIN, COL_RAZON_SOCIAL, COL_ESTADO_COMERCIAL
from src.services import comercial_services, operaciones_services
from src.theme.colors import TEXT_SECONDARY
from src.theme.theme_manager import ThemeManager
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.selector_fecha import CalendarioEmbebido
from src.ui.operaciones.base import (
    BotonAccionOperaciones,
    COLUMNAS_BUSQUEDA_EXACTAS_OPERACIONES,
    COLUMNAS_BUSQUEDA_OPERACIONES,
    IDX_BAJAS,
    MENSAJE_ERROR_GUARDADO,
    SaveExcelThread,
)

_ANCHOS_FECHAS_BAJA = {'FLOTA VC': 420, 'RAZÓN SOCIAL': 340, 'UNIDADES': 110, 'ID': 90, 'VIN': 175,
                       'ESTADO COMERCIAL': 150, 'INICIO CONTRATO': 130, 'TÉRMINO CONTRATO': 130, 'FECHA DE BAJA': 130}


class _FiltroClicFuera(QObject):
    """Filtro de la aplicación mientras el panel de la fecha está abierto: un clic fuera del
    panel y de la tabla lo cierra (los clics dentro del panel y de sus calendarios no)."""

    def __init__(self, modulo):
        super().__init__(modulo)
        self._modulo = modulo

    def eventFilter(self, objeto, evento):
        # El clic llega primero a la ventana (QWindow) y después al widget: solo cuenta el del widget
        if evento.type() == QEvent.Type.MouseButtonPress and isinstance(objeto, QWidget):
            self._modulo._clic_fuera_fechas_baja(objeto)
        return False


class _FechasBajaOperacionesMixin:
    def _crear_controles_fechas_baja(self):
        """Botón de la barra (filtros) que activa el modo y botón para volver a la lista de flotas."""
        self._filtro_clic_fuera = _FiltroClicFuera(self)
        self._filtro_clic_fuera_activo = False
        self._modo_fechas_baja = False
        self._flota_fechas_baja = None
        self._fb_seleccion = []

        self.btn_fechas_baja = QPushButton()
        self.btn_fechas_baja.setCheckable(True)
        self.btn_fechas_baja.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fechas_baja.setIcon(ThemeManager.icon('fa5s.calendar-alt', color=TEXT_SECONDARY))
        self.btn_fechas_baja.setToolTip("Fechas de baja: muestra todos los contratos dados de baja, por flota, para corregir su fecha.")
        estilo_com.aplicar_estilo_boton_barra(self.btn_fechas_baja, 'neutro')
        self.btn_fechas_baja.toggled.connect(self._on_fechas_baja_toggled)
        self.btn_fechas_baja.hide()

        self.btn_volver_flotas = QPushButton(" Flotas")
        self.btn_volver_flotas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver_flotas.setIcon(ThemeManager.icon('fa5s.arrow-left', color=TEXT_SECONDARY))
        self.btn_volver_flotas.setToolTip("Volver a la lista de flotas")
        estilo_com.aplicar_estilo_boton_barra(self.btn_volver_flotas, 'neutro')
        self.btn_volver_flotas.clicked.connect(self._volver_a_flotas_fechas_baja)
        self.btn_volver_flotas.hide()

    def _build_bloque_fecha_baja(self):
        """Bloque del panel derecho: contrato(s) elegido(s), fecha actual y calendario."""
        bloque = QWidget()
        lay = QVBoxLayout(bloque)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Encabezado: iniciales (o cantidad), nombre del cliente y VIN o flota
        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        lay_hero = QHBoxLayout(hero)
        lay_hero.setContentsMargins(12, 12, 12, 12)
        lay_hero.setSpacing(12)
        self._fb_avatar = QLabel("--")
        self._fb_avatar.setFixedSize(46, 46)
        self._fb_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fb_avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self._fb_nombre = QLabel("—")
        self._fb_nombre.setWordWrap(True)
        self._fb_nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)
        self._fb_sub = QLabel("")
        self._fb_sub.setWordWrap(True)
        self._fb_sub.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        textos.addWidget(self._fb_nombre)
        textos.addWidget(self._fb_sub)
        lay_hero.addWidget(self._fb_avatar)
        lay_hero.addLayout(textos, stretch=1)
        lay.addWidget(hero)

        # Celdas: estado y contrato arriba; fecha actual y nueva (con el calendario) abajo
        grilla = QGridLayout()
        grilla.setSpacing(6)
        celda_estado, self._fb_estado = estilo_com.crear_celda_ficha("Estado comercial")
        celda_contrato, self._fb_contrato = estilo_com.crear_celda_ficha("N° contrato")
        celda_actual, self._fb_actual = estilo_com.crear_celda_ficha("Fecha actual")
        celda_nueva, self._fb_nueva = estilo_com.crear_celda_ficha("Nueva fecha")
        self._fb_nueva.setStyleSheet(estilo_com.QSS_FICHA_META_VALOR + " color: #1F6FEB;")
        for i, celda in enumerate((celda_estado, celda_contrato, celda_actual, celda_nueva)):
            grilla.addWidget(celda, i // 2, i % 2)
        lay.addLayout(grilla)

        # Calendario dentro de la misma caja: se elige el día aquí y se guarda abajo
        self.calendario_fecha_baja = CalendarioEmbebido(QDate.currentDate())
        self.calendario_fecha_baja.fecha_elegida.connect(self._on_fecha_baja_elegida)
        lay.addWidget(self.calendario_fecha_baja, alignment=Qt.AlignmentFlag.AlignHCenter)

        aviso = QLabel("Solo cambia la fecha de baja: el estado y los demás datos del contrato no se tocan.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #8A97AB; font-size: 11px; background: transparent; border: none; padding: 0 2px;")
        lay.addWidget(aviso)

        self.btn_guardar_fecha_baja = BotonAccionOperaciones(
            'fa5s.save', 'Guardar fecha',
            "Cambia solo la fecha de baja del contrato; no toca su estado ni sus otros datos.", estilo_com.AZUL, bloque)
        self.btn_guardar_fecha_baja.clicked.connect(self._on_guardar_fecha_baja_clicked)
        lay.addWidget(self.btn_guardar_fecha_baja)
        return bloque

    # ---------------------------------------------------------------
    # Modo y navegación (flotas -> contratos)
    # ---------------------------------------------------------------
    def _on_fechas_baja_toggled(self, activo):
        self._modo_fechas_baja = activo
        self._flota_fechas_baja = None
        estilo_com.aplicar_estilo_boton_barra(self.btn_fechas_baja, 'activo' if activo else 'neutro')
        self.btn_fechas_baja.setIcon(ThemeManager.icon('fa5s.calendar-alt', color=estilo_com.PRIMARIO if activo else TEXT_SECONDARY))
        self._refrescar_tabla_actual()

    def _abrir_flota_fechas_baja(self, flota):
        self._flota_fechas_baja = flota
        self._refrescar_tabla_actual()

    def _volver_a_flotas_fechas_baja(self):
        self._flota_fechas_baja = None
        self._refrescar_tabla_actual()

    def _vigilar_clic_fuera_fechas_baja(self, activo):
        """El filtro de la aplicación solo está puesto mientras el panel de la fecha está abierto."""
        if activo == self._filtro_clic_fuera_activo:
            return
        self._filtro_clic_fuera_activo = activo
        if activo:
            QApplication.instance().installEventFilter(self._filtro_clic_fuera)
        else:
            QApplication.instance().removeEventFilter(self._filtro_clic_fuera)

    def _clic_fuera_fechas_baja(self, objeto):
        if not (self._modo_fechas_baja and self._panel_abierto):
            return
        tablas = (self.table.viewport(), self.table.frozen_view.viewport())
        actual = objeto
        while actual is not None:
            if actual is self._panel_detalle or any(actual is t for t in tablas):
                return
            actual = actual.parent()
        QTimer.singleShot(0, self.table.clearSelection)

    def _actualizar_visibilidad_fechas_baja(self, idx):
        """Botones y bloques que dependen del modo; se llama al final de _refrescar_tabla_actual."""
        en_modo = idx == IDX_BAJAS and self._modo_fechas_baja
        self.btn_fechas_baja.setVisible(idx == IDX_BAJAS)
        self.btn_volver_flotas.setVisible(en_modo and self._flota_fechas_baja is not None)
        self._bloque_fecha_baja.setVisible(en_modo)
        if not en_modo:
            self._vigilar_clic_fuera_fechas_baja(False)
        if en_modo:
            self._bloque_unidad.hide()
            self.btn_exportar_vin_cdb.hide()
            self.btn_marcar_desconectado.setEnabled(False)

    # ---------------------------------------------------------------
    # Tabla
    # ---------------------------------------------------------------
    def _refrescar_fechas_baja(self):
        """Reemplaza la cola de Bajas por todos los contratos dados de baja (incluye historial):
        agrupados por flota y, con una flota elegida, uno por fila."""
        base = operaciones_services.contratos_dados_de_baja(self.data_manager.get_comercial_df())
        base = self._aplicar_filtros_columna(IDX_BAJAS, base)
        texto = self.search_input.text().strip().lower()
        if texto and not base.empty:
            base = base[comercial_services.construir_mascara_busqueda(
                base, texto, COLUMNAS_BUSQUEDA_OPERACIONES, COLUMNAS_BUSQUEDA_EXACTAS_OPERACIONES)]
        self._fb_base = base

        flota = self._flota_fechas_baja
        contratos = operaciones_services.contratos_de_flota_en_baja(base, flota) if flota is not None else None
        if contratos is not None and contratos.empty:
            self._flota_fechas_baja = flota = None
            contratos = None

        if contratos is None:
            tabla = operaciones_services.agrupar_bajas_por_flota(base)
            self.lbl_titulo_bandeja.setText("Bajas · Fechas de baja")
            self.lbl_resumen_bandeja.setText(f"{len(tabla)} {'flota' if len(tabla) == 1 else 'flotas'} · "
                                             f"{len(base)} {'contrato' if len(base) == 1 else 'contratos'}")
        else:
            cols = [c for c in operaciones_services.COLUMNAS_FECHAS_BAJA_CONTRATOS if c in contratos.columns]
            tabla = contratos[cols].copy()
            self.lbl_titulo_bandeja.setText(f"Bajas · {flota}")
            self.lbl_resumen_bandeja.setText(f"{len(tabla)} {'contrato' if len(tabla) == 1 else 'contratos'} · clic en uno para editar la fecha")

        self._actualizar_kpis(IDX_BAJAS, operaciones_services.filtrar_bajas(self.df_master))
        tabla = self.table.apply_sort(tabla)
        self.table.setWordWrap(True)
        self.model.set_data(tabla)
        for i, col in enumerate(tabla.columns):
            self.table.setColumnWidth(i, _ANCHOS_FECHAS_BAJA.get(col, 140))
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._ajustar_alto_filas()
        self._limpiar_panel_detalle()
        self._quitar_formulario_contacto()
        self._vigilar_clic_fuera_fechas_baja(False)
        self._mostrar_panel(False)

    def _on_seleccion_fechas_baja(self):
        df = self.model.get_df()
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows() if 0 <= i.row() < len(df)})
        if not filas:
            self._vigilar_clic_fuera_fechas_baja(False)
            self._mostrar_panel(False)
            return
        if self._flota_fechas_baja is None:
            flota = str(df.iat[filas[0], df.columns.get_loc(COL_FLOTA_VC)])
            QTimer.singleShot(0, lambda: self._abrir_flota_fechas_baja(flota))
            return
        self._pintar_bloque_fecha_baja(df.iloc[filas])
        self._lbl_titulo_panel.setText("Corregir fecha de baja")
        self._mostrar_panel(True)
        self._vigilar_clic_fuera_fechas_baja(True)

    def _pintar_bloque_fecha_baja(self, filas):
        def texto(valor):
            return '' if pd.isna(valor) else str(valor).strip()

        ids = [comercial_services._normalizar_id_contrato(texto(v)) for v in filas[COL_ID]] if COL_ID in filas.columns else [''] * len(filas)
        self._fb_seleccion = [{'id': i, 'vin': texto(v)} for i, v in zip(ids, filas[COL_VIN])]
        fechas = [texto(v) for v in filas[COL_FECHA_BAJA]]
        distintas = sorted({f for f in fechas if f and f != '-'})

        estados = sorted({texto(v) for v in filas[COL_ESTADO_COMERCIAL]}) if COL_ESTADO_COMERCIAL in filas.columns else []
        if len(filas) == 1:
            fila = filas.iloc[0]
            razon = ''
            base = getattr(self, '_fb_base', None)
            if base is not None and not base.empty and COL_ID in base.columns and ids[0]:
                coincide = base[base[COL_ID].map(lambda v: comercial_services._normalizar_id_contrato(texto(v))) == ids[0]]
                razon = texto(coincide.iloc[0][COL_RAZON_SOCIAL]) if not coincide.empty else ''
            self._fb_avatar.setText(estilo_com.iniciales(razon) if razon else "--")
            self._fb_nombre.setText(razon or texto(fila[COL_VIN]))
            self._fb_sub.setText(f"VIN {texto(fila[COL_VIN])}")
            self._fb_contrato.setText(ids[0] or "-")
        else:
            self._fb_avatar.setText(str(len(filas)))
            self._fb_nombre.setText(f"{len(filas)} contratos")
            self._fb_sub.setText(f"Flota {self._flota_fechas_baja}")
            self._fb_contrato.setText(f"{len(filas)} elegidos")
        self._fb_contrato.setStyleSheet(estilo_com.QSS_FICHA_META_VALOR)
        if len(estados) == 1:
            estilo_com.pintar_chip_ficha(self._fb_estado, estados[0])
        else:
            self._fb_estado.setText("Varios")
            self._fb_estado.setStyleSheet(estilo_com.QSS_FICHA_META_VALOR)

        if not distintas:
            self._fb_actual.setText("Sin fecha")
        elif len(distintas) == 1:
            self._fb_actual.setText(distintas[0])
        else:
            self._fb_actual.setText(f"{len(distintas)} fechas distintas")
        self._fb_actual.setToolTip("Se reemplazan todas por la nueva fecha." if len(distintas) > 1 else "")
        self._fb_actual.setStyleSheet(estilo_com.QSS_FICHA_META_VALOR)

        fecha = QDate.fromString(distintas[0], "dd-MM-yyyy") if len(distintas) == 1 else QDate()
        fecha = fecha if fecha.isValid() else QDate.currentDate()
        self.calendario_fecha_baja.poner_fecha(fecha)
        self._fb_nueva.setText(fecha.toString("dd-MM-yyyy"))

    def _on_fecha_baja_elegida(self, fecha):
        self._fb_nueva.setText(fecha.toString("dd-MM-yyyy"))

    # ---------------------------------------------------------------
    # Guardado: solo FECHA DE BAJA, por ID de contrato (sirve también para el historial)
    # ---------------------------------------------------------------
    def _on_guardar_fecha_baja_clicked(self):
        seleccion = list(self._fb_seleccion)
        if not seleccion:
            return
        fecha = self.calendario_fecha_baja.fecha().toString("dd-MM-yyyy")
        cambios = operaciones_services.calcular_cambios_fecha_baja(fecha)
        changes = {}
        for s in seleccion:
            datos = {'VIN': s['vin'], 'cambios': dict(cambios)}
            if s['id']:
                datos['ID'] = s['id']
            changes[s['id'] or s['vin'].upper()] = datos
        self._cambios_en_guardado_fecha_baja = changes

        self.btn_guardar_fecha_baja.setEnabled(False)
        self.btn_guardar_fecha_baja.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando la fecha de baja…")
        self.save_thread_fecha_baja = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_fecha_baja.finished_signal.connect(self._on_guardar_fecha_baja_finished)
        self.save_thread_fecha_baja.start()

    def _on_guardar_fecha_baja_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_guardar_fecha_baja.setText('Guardar fecha')
        self.btn_guardar_fecha_baja.setEnabled(True)
        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, self._cambios_en_guardado_fecha_baja)
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()
