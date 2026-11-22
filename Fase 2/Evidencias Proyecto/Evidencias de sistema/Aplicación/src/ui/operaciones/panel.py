"""Panel flotante, sub-pestañas y tarjetas KPI de Operaciones."""
from src.theme.colors import DANGER, PRIMARY, WARNING
import pandas as pd
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QLabel, QTabBar
from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from src.core.constants import COL_CDB_FLOTA
from src.core.hilos import iniciar_hilo_retenido
from src.services import operaciones_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.transiciones import capturar
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
from src.ui.operaciones.base import (
    IDX_ACTIVACIONES,
    IDX_BAJAS,
    IDX_CONTACTOS,
    IDX_DATOS_FLOTA,
    IDX_NO_ENTREGADOS,
    IDX_SIN_FLOTA,
    SUBTABS,
    _FILTROS_POR_TAB,
)


class _CalculoContadores(QThread):
    """Cuenta en segundo plano las unidades de cada cola de Operaciones."""
    listo = pyqtSignal(object)

    def __init__(self, df, contactos, cantidad):
        super().__init__()
        self._df, self._contactos, self._cantidad = df, contactos, cantidad

    def run(self):
        cuentas = []
        for i in range(self._cantidad):
            try:
                if i == IDX_CONTACTOS:
                    n = len(operaciones_services.filtrar_cdb_sin_contacto(self._df, self._contactos))
                else:
                    n = len(_FILTROS_POR_TAB[i](self._df))
            except Exception:
                n = 0
            cuentas.append(n)
        try:
            urgentes = len(operaciones_services.filtrar_conectados_sin_flota_vc(self._df))
        except Exception:
            urgentes = 0
        self.listo.emit((cuentas, urgentes))


class _PanelOperacionesMixin:
    # ---------------------------------------------------------------
    # Panel flotante (mismo comportamiento que las acciones rápidas de Comercial)
    # ---------------------------------------------------------------
    def _geometria_panel(self, abierto):
        return estilo_com.geometria_panel_flotante(self, abierto)

    def _mostrar_panel(self, mostrar):
        panel = getattr(self, '_panel_detalle', None)
        if panel is None or mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, panel, lambda: self._panel_abierto)
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel(False))
                panel.show()
            panel.raise_()
            estilo_com.fijar_sombra_panel(panel, True)
        self._anim_panel.setStartValue(panel.pos())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim_panel.start()

    def _on_anim_panel_terminada(self):
        if not self._panel_abierto:
            self._panel_detalle.hide()
            estilo_com.fijar_sombra_panel(self._panel_detalle, False)
        self._ajustar_barra_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra de la bandeja hacia la izquierda
        para que el panel flotante no los tape."""
        barra, panel = self._barra_bandeja, self._panel_detalle
        solape = 0
        if panel.isVisible():
            borde_derecho = barra.mapTo(panel.parentWidget(), QPoint(barra.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        barra.layout().setContentsMargins(15, 12, 15 + solape, 12)
        # En Fechas de baja la tabla se angosta para quedar a la izquierda del panel y no taparle columnas
        tapa_tabla = solape if (getattr(self, '_modo_fechas_baja', False) and self.subtabs.currentIndex() == IDX_BAJAS) else 0
        self._layout_tarjeta_tabla.setContentsMargins(1, 1, 1 + tapa_tabla, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = getattr(self, '_panel_detalle', None)
        if panel is not None and panel.isVisible():
            self._anim_panel.stop()
            QTimer.singleShot(0, self._reubicar_panel)

    def _reubicar_panel(self):
        panel = self._panel_detalle
        if not panel.isVisible():
            return
        panel.setGeometry(self._geometria_panel(self._panel_abierto))
        if not self._panel_abierto:
            panel.hide()
        self._ajustar_barra_bajo_panel()

    # ---------------------------------------------------------------
    # Sub-pestañas
    # ---------------------------------------------------------------
    def _build_subtabs(self):
        # Mismas sub-pestañas que Comercial: solo texto y contador de unidades
        self.subtabs = QTabBar()
        self._badges_subtabs = []
        for i, (nombre, _icono) in enumerate(SUBTABS):
            self.subtabs.addTab(nombre)
            badge = QLabel("0")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(34, 20)
            if i == IDX_DATOS_FLOTA:
                # Conectados lleva además un contador rojo con las filas urgentes
                contenedor_badges = QWidget()
                fila_badges = QHBoxLayout(contenedor_badges)
                fila_badges.setContentsMargins(0, 0, 0, 0)
                fila_badges.setSpacing(4)
                self._badge_urgentes = QLabel("0")
                self._badge_urgentes.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._badge_urgentes.setFixedHeight(20)
                self._badge_urgentes.setStyleSheet(
                    f"background-color: {DANGER}; color: white; border-radius: 10px; "
                    "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;")
                self._badge_urgentes.hide()
                fila_badges.addWidget(badge)
                fila_badges.addWidget(self._badge_urgentes)
                self.subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, contenedor_badges)
            else:
                self.subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, badge)
            self._badges_subtabs.append(badge)
        self.subtabs.currentChanged.connect(self._estilizar_badges_subtabs)
        self._estilizar_badges_subtabs()
        self.subtabs.setExpanding(False)
        self.subtabs.setDrawBase(False)
        # Sin flechas de desplazamiento: al ocultar y volver a mostrar pestañas (búsqueda por VIN) quedaban a la vista
        self.subtabs.setUsesScrollButtons(False)
        self.subtabs.setStyleSheet(estilo_com.QSS_SUBPESTANAS + "QTabBar::tab { padding-right: 6px; } "
            "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
        self.subtabs.currentChanged.connect(self._on_subtab_cambiada)

        contenedor = QFrame()
        contenedor.setObjectName("contenedorSubpestanasComercial")
        contenedor.setStyleSheet(estilo_com.QSS_CONTENEDOR_SUBPESTANAS)
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.subtabs)
        fila.addStretch()
        return contenedor

    def _estilizar_badges_subtabs(self, *_):
        actual = self.subtabs.currentIndex()
        for i, badge in enumerate(self._badges_subtabs):
            fondo, texto = ("#E3E8F0", "#1B2B4E") if i == actual else ("#EEF2F6", estilo_com.APAGADO)
            badge.setStyleSheet(
                f"background-color: {fondo}; color: {texto}; border-radius: 10px; "
                "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;"
            )

    def _actualizar_contadores_subtabs(self):
        """Unidades de cada cola junto al nombre de su sub-pestaña (sin búsqueda ni filtro de cliente).
        Las cuentas se calculan en un hilo; si llega otra carga mientras tanto, se repite al terminar."""
        df = self.df_master
        if df is None or df.empty:
            self._aplicar_contadores(([0] * len(self._badges_subtabs), 0))
            return
        previo = self.__dict__.get('_hilo_contadores')
        if previo is not None and previo.isRunning():
            self._contadores_pendientes = True
            return
        hilo = _CalculoContadores(df, self.data_manager.get_contactos_df(), len(self._badges_subtabs))
        hilo.listo.connect(self._contadores_listos)
        self._hilo_contadores = hilo
        iniciar_hilo_retenido(hilo)

    def _contadores_listos(self, resultado):
        self._aplicar_contadores(resultado)
        if self.__dict__.get('_contadores_pendientes'):
            self._contadores_pendientes = False
            QTimer.singleShot(100, self._actualizar_contadores_subtabs)

    def _aplicar_contadores(self, resultado):
        cuentas, urgentes = resultado
        for i, badge in enumerate(self._badges_subtabs):
            n = cuentas[i] if i < len(cuentas) else 0
            if i == IDX_DATOS_FLOTA:
                self._badge_urgentes.setText(str(urgentes))
                self._badge_urgentes.setVisible(urgentes > 0)
                self._badge_urgentes.setToolTip(
                    f"{urgentes} sin Flota VC o CDB Flota: revisar primero" if urgentes else "")
                self.subtabs.setTabText(i, SUBTABS[i][0])
            if badge.text() != str(n):
                badge.setText(str(n))
                # El ancho crece con la cifra (miles de unidades) y se avisa a la barra para recolocar
                badge.setFixedWidth(max(34, badge.fontMetrics().horizontalAdvance(str(n)) + 24))
                self.subtabs.setTabText(i, SUBTABS[i][0])
        # El contenedor de Conectados cambia de ancho al aparecer o crecer el contador rojo
        contenedor_badges = self._badge_urgentes.parentWidget()
        contenedor_badges.adjustSize()
        self.subtabs.setTabText(IDX_DATOS_FLOTA, SUBTABS[IDX_DATOS_FLOTA][0])

    def _on_subtab_cambiada(self, _idx):
        # Los KPI cambian con un fundido; la tabla, con un esqueleto corto
        fotos = []
        if self._kpi_contenedor.isVisible():
            self._transicion_kpis.terminar()
            fotos.append((self._transicion_kpis, capturar(self._kpi_contenedor)))
        self._refrescar_tabla_actual()
        for transicion, foto in fotos:
            transicion.iniciar(foto)
        animar_sobre_tabla(self.table, 300)

    # ---------------------------------------------------------------
    # KPIs por sub-pestaña (06-10-2026): mismas tarjetas que el HTML v2 de
    # Operaciones y mismo diseño que las de Comercial (TarjetaKpiResumen).
    # Son informativas: no filtran la cola. Activaciones, Sin Flota y No
    # entregados comparten las 4 tarjetas, calculadas sobre las tres colas juntas.
    # ---------------------------------------------------------------
    _KPIS_PENDIENTES_ACTIVACION = [
        ("pendientes", "Pendientes de activación", PRIMARY,
         "Unidades en las colas de Activaciones, Sin Flota y No entregados.", "activaciones + sin flota + no entregados"),
        ("activando", "En proceso de activación", WARNING,
         "ESTADO DE ACTIVACIÓN ACTUAL = Activando.", "unidades en gestión"),
        ("no_entregado", "Pendientes por no entrega", WARNING,
         "Unidades en la cola de No entregados (ESTADO DE ACTIVACIÓN ACTUAL = No entregado).", "falta la entrega"),
        ("sin_flota", "Pendientes por asignación de flota", DANGER,
         "Unidades en la cola de Sin Flota (todavía no aparecen en Volvo Connect).", "sin flota en VC"),
    ]

    _KPI_SPECS = {
        IDX_ACTIVACIONES: _KPIS_PENDIENTES_ACTIVACION,
        IDX_SIN_FLOTA: _KPIS_PENDIENTES_ACTIVACION,
        IDX_NO_ENTREGADOS: _KPIS_PENDIENTES_ACTIVACION,
        IDX_BAJAS: [("bajas", "Bajas pendientes", DANGER,
             "Unidades de la cola de Bajas: siguen Conectadas a la espera de la desconexión física.",
             "bajas por cerrar")],
        IDX_CONTACTOS: [("cdb_sin_contacto", "CDB sin contacto", DANGER,
             "CDB de RM_JAVI que no tienen ningún contacto en contactos.xlsx.",
             "sin contacto registrado")],
        IDX_DATOS_FLOTA: [("conectados_vigentes", "Conectados", PRIMARY,
                           "Contratos Vigentes, en Revisar o Vencidos cuya unidad está Conectada. FLOTA VC y CDB FLOTA se editan en el panel.",
                           "contratos"),
                          ("sin_flota_vc", "Sin flota o CDB", DANGER,
                           "Contratos Vigentes, en Revisar o Vencidos, Conectados, que no tienen FLOTA VC o CDB FLOTA.",
                           "por completar"),
                          ("cdb_varias_flotas", "CDB con varias flotas", WARNING,
                           "CDB FLOTA que aparece con más de una FLOTA VC distinta.", "CDB repetidos"),
                          ("flota_varios_cdb", "Flotas con varios CDB", WARNING,
                           "FLOTA VC con el mismo nombre que aparece con más de un CDB FLOTA distinto.", "flotas repetidas")],
    }

    def _build_kpi_row(self):
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._kpi_cards = []
        for _ in range(4):
            card = estilo_com.TarjetaKpiResumen()
            card.setCheckable(False)
            card.setCursor(Qt.CursorShape.ArrowCursor)
            # Las pestañas con menos de 4 tarjetas dejan el hueco, como el HTML
            politica = card.sizePolicy()
            politica.setRetainSizeWhenHidden(True)
            card.setSizePolicy(politica)
            self._kpi_cards.append(card)
            kpi_row.addWidget(card, stretch=1)
        return kpi_row

    def _calcular_kpis(self, idx, cola):
        """clave -> (valor, fracción 0-1 sobre la base de esa tarjeta).
        `cola` es la cola de `idx` sin filtro de cliente ni búsqueda."""
        df = self.df_master
        if idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS):
            def cola_de(i):
                if i == idx:
                    return cola
                return _FILTROS_POR_TAB[i](df) if df is not None else pd.DataFrame()
            activaciones, sin_flota, no_entregados = cola_de(IDX_ACTIVACIONES), cola_de(IDX_SIN_FLOTA), cola_de(IDX_NO_ENTREGADOS)
            parcial = operaciones_services.calcular_kpis_activaciones(activaciones)
            pendientes = len(activaciones) + len(sin_flota) + len(no_entregados)
            valores = {
                "pendientes": pendientes, "activando": parcial["activando"],
                "no_entregado": len(no_entregados), "sin_flota": len(sin_flota),
            }
            return {k: (v, (v / pendientes) if pendientes else 0.0) for k, v in valores.items()}
        if idx == IDX_BAJAS:
            return {"bajas": (len(cola), 1.0 if len(cola) else 0.0)}
        if idx == IDX_DATOS_FLOTA:
            por_completar = len(operaciones_services.filtrar_conectados_sin_flota_vc(cola))
            cdb_varias, total_cdb, flota_varios, total_flotas = operaciones_services.contar_cdb_flota_cruzados(cola)
            return {"conectados_vigentes": (len(cola), 1.0 if len(cola) else 0.0),
                    "sin_flota_vc": (por_completar, (por_completar / len(cola)) if len(cola) else 0.0),
                    "cdb_varias_flotas": (cdb_varias, (cdb_varias / total_cdb) if total_cdb else 0.0),
                    "flota_varios_cdb": (flota_varios, (flota_varios / total_flotas) if total_flotas else 0.0)}
        total_cdb = 0
        if df is not None and not df.empty and COL_CDB_FLOTA in df.columns:
            cdb = df[COL_CDB_FLOTA].astype(str).str.strip()
            total_cdb = cdb[~cdb.str.upper().isin(['', 'NAN', 'NONE', '-', 'NAT'])].nunique()
        return {"cdb_sin_contacto": (len(cola), (len(cola) / total_cdb) if total_cdb else 0.0)}

    def _actualizar_kpis(self, idx, cola):
        specs = self._KPI_SPECS.get(idx, self._KPI_SPECS[0])
        valores = self._calcular_kpis(idx, cola)
        for i, card in enumerate(self._kpi_cards):
            if i >= len(specs):
                card.hide()
                continue
            clave, titulo, color, tooltip, pie = specs[i]
            card.definir(titulo, color, tooltip)
            card.configurar(False, color)
            card.setCursor(Qt.CursorShape.ArrowCursor)
            valor, fraccion = valores[clave]
            card.actualizar(valor, fraccion, pie)
            card.show()
