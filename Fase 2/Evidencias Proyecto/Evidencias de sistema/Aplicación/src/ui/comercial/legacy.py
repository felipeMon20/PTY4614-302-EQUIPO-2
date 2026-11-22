"""Pantalla de Comercial anterior, que sigue siendo el motor de datos de la nueva."""
from src.theme.colors import TEXT_SECONDARY
import pandas as pd
import qtawesome as qta
from PyQt6.QtWidgets import QWidget, QPushButton, QMessageBox, QApplication
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.services import comercial_services
from src.services import catalogos_service
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.theme.theme_manager import ThemeManager
from config.settings import REPORTE_NOTAS_VENTAS_URL
from src.ui.compartido import aviso_enlace
from src.core.constants import DROPDOWN_OPTIONS_UNIDAD
from src.ui.comercial.base import (
    SaveExcelThread,
    logger,
)


# =========================================================
# MÓDULO COMERCIAL PRINCIPAL (implementación actual, preservada intacta)
# =========================================================
class _ComercialModuleLegacy(QWidget):
    """Motor de datos de Comercial, oculto dentro de ComercialModule: carga y prepara
    df_base, guarda las ediciones de unidad y es dueño de los botones de la barra de
    la bandeja y de los filtros de aviso."""
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()

        self._skip_self_triggered_reload = False
        # data_ready con el módulo oculto solo marca dirty, no reprocesa (ver general.py)
        self._data_dirty = False

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self.data_manager.load_error.connect(self._on_load_error)

        # Catálogo compartido con las demás pantallas que abren el formulario de unidad
        self.dropdown_options = catalogos_service.opciones_formulario(DROPDOWN_OPTIONS_UNIDAD)

        self._setup_ui()
        self.load_data()

    def _setup_ui(self):
        # ComercialModule ubica estos botones en la barra de la bandeja
        self.btn_notas_venta_bi = QPushButton("BI")
        self.btn_notas_venta_bi.setFixedSize(32, 32)
        self.btn_notas_venta_bi.setStyleSheet("background-color: #F5C518; color: #1F2937; border-radius: 16px; font-weight: bold;")
        self.btn_notas_venta_bi.setToolTip("Abrir Notas de Venta en Power BI")
        self.btn_notas_venta_bi.clicked.connect(self._open_notas_venta_bi)

        self.btn_export_excel = QPushButton(" Excel")
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        ThemeManager.apply_success_button(self.btn_export_excel)

        self.btn_revisar_inconsistencias_forma_contrato = QPushButton(" Revisar inconsistencias")
        self.btn_revisar_inconsistencias_forma_contrato.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_revisar_inconsistencias_forma_contrato.setCheckable(True)
        ThemeManager.apply_secondary_button(self.btn_revisar_inconsistencias_forma_contrato)
        self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=TEXT_SECONDARY))
        self.btn_revisar_inconsistencias_forma_contrato.setToolTip(
            "Filtra la tabla a las unidades cuya combinación de FORMA DE CONTRATO / TIPO DE FACTURACION "
            "no cumple la matriz de negocio. No corrige nada automáticamente.\n\n"
            "Nota: TIPO DE FACTURACION proviene de RM_JAVI.xlsx y se sobrescribe en cada sincronización -- "
            "una corrección hecha solo aquí puede volver a quedar inconsistente si el RM no se actualiza también."
        )
        self.btn_revisar_inconsistencias_forma_contrato.toggled.connect(self._toggle_filtro_inconsistencias_forma_contrato)
        self._df_inconsistencias_forma_contrato = pd.DataFrame()
        self._filtro_inconsistencias_forma_contrato_activo = False

        # Contratos cuyo término en el archivo no coincide con inicio + duración
        # (la app lo recalcula al cargar, así que solo se ve contra el original).
        self.btn_revisar_fechas_contrato = QPushButton(" Revisar fechas")
        self.btn_revisar_fechas_contrato.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_revisar_fechas_contrato.setCheckable(True)
        ThemeManager.apply_secondary_button(self.btn_revisar_fechas_contrato)
        self.btn_revisar_fechas_contrato.setIcon(ThemeManager.icon('fa5s.not-equal', color=TEXT_SECONDARY))
        self.btn_revisar_fechas_contrato.toggled.connect(self._toggle_filtro_fechas_contrato)
        self._df_fechas_contrato = pd.DataFrame()
        self._filtro_fechas_contrato_activo = False
        self._actualizar_tooltip_fechas_contrato()

        self.btn_reload = QPushButton(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_reload)
        self.btn_reload.clicked.connect(self._trigger_reload)

    def _open_notas_venta_bi(self):
        """Abre el reporte de Notas de Venta en Power BI para consulta manual
        (el usuario filtra por los últimos 7 dígitos del CHASIS/VIN). No lee
        ni parsea ningún Excel: solo abre el link en el navegador."""
        if REPORTE_NOTAS_VENTAS_URL:
            QDesktopServices.openUrl(QUrl(REPORTE_NOTAS_VENTAS_URL))
        else:
            aviso_enlace.avisar_enlace_faltante(self, "Notas de Venta (Power BI)")

    def _trigger_reload(self):
        self.btn_reload.setText(" Cargando...")
        self.btn_reload.setIcon(qta.icon('fa5s.sync', color=TEXT_SECONDARY, animation=qta.Spin(self.btn_reload)))
        self.btn_reload.setEnabled(False)
        
        self.data_manager.load_data_async()
        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setText(" Recargar")
            self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
            self.btn_reload.setEnabled(True)

    def _on_global_data_ready(self):
        try:
            if self._skip_self_triggered_reload:
                self._skip_self_triggered_reload = False
            elif getattr(self, 'es_visible', self.isVisible)():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception:
            logger.exception("Falló la recarga de Comercial tras actualizarse los datos")
        finally:
            self.btn_reload.setText(" Recargar")
            self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
            self.btn_reload.setEnabled(True)

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este modulo."""
        if self._data_dirty:
            self.load_data()

    def _on_load_error(self, error_msg):
        self.btn_reload.setText(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        self.btn_reload.setEnabled(True)
        QMessageBox.critical(self, "Error al Cargar", f"Ocurrió un problema al leer los datos:\n{error_msg}")

    def _toggle_filtro_inconsistencias_forma_contrato(self, checked):
        """Filtro del aviso "Revisar inconsistencias": la bandeja de ComercialModule lo lee
        (ver ComercialModule._on_aviso_bandeja_toggled). Solo detecta, no corrige."""
        if checked and (self._df_inconsistencias_forma_contrato is None or self._df_inconsistencias_forma_contrato.empty):
            self.btn_revisar_inconsistencias_forma_contrato.blockSignals(True)
            self.btn_revisar_inconsistencias_forma_contrato.setChecked(False)
            self.btn_revisar_inconsistencias_forma_contrato.blockSignals(False)
            QMessageBox.information(
                self, "Revisar inconsistencias",
                "No se encontraron combinaciones de FORMA DE CONTRATO / TIPO DE FACTURACION "
                "que contradigan la matriz de negocio."
            )
            return

        if checked and getattr(self, '_filtro_fechas_contrato_activo', False):
            self.btn_revisar_fechas_contrato.setChecked(False)
        self._filtro_inconsistencias_forma_contrato_activo = checked
        if checked:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_inconsistencias_forma_contrato, 'activo')
            self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=estilo_com.PRIMARIO))
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_inconsistencias_forma_contrato, 'neutro')
            self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=TEXT_SECONDARY))

    def _actualizar_tooltip_fechas_contrato(self):
        n = len(self._df_fechas_contrato) if self._df_fechas_contrato is not None else 0
        self.btn_revisar_fechas_contrato.setToolTip(
            "Muestra los contratos cuyo término en el archivo no coincide con INICIO CONTRATO + DURACIÓN "
            "(las Bajas no se revisan). No corrige nada: la app ya usa el término calculado; esto sirve para "
            "corregir el RM.\n\n" + (f"{n} contrato(s) con diferencia." if n else "Sin diferencias detectadas."))

    def _toggle_filtro_fechas_contrato(self, checked):
        if checked and (self._df_fechas_contrato is None or self._df_fechas_contrato.empty):
            self.btn_revisar_fechas_contrato.blockSignals(True)
            self.btn_revisar_fechas_contrato.setChecked(False)
            self.btn_revisar_fechas_contrato.blockSignals(False)
            QMessageBox.information(
                self, "Revisar fechas",
                "Todos los contratos tienen un término que coincide con INICIO CONTRATO + DURACIÓN.")
            return

        if checked and self._filtro_inconsistencias_forma_contrato_activo:
            self.btn_revisar_inconsistencias_forma_contrato.setChecked(False)
        self._filtro_fechas_contrato_activo = checked
        if checked:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_fechas_contrato, 'activo')
            self.btn_revisar_fechas_contrato.setIcon(ThemeManager.icon('fa5s.not-equal', color=estilo_com.PRIMARIO))
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_fechas_contrato, 'neutro')
            self.btn_revisar_fechas_contrato.setIcon(ThemeManager.icon('fa5s.not-equal', color=TEXT_SECONDARY))

    # Callback fijado por ComercialModule.__init__ (self.legacy.on_editar_unidad_solicitado
    # = self._iniciar_edicion_unidad) -- ver _handle_editar_unidad. _ComercialModuleLegacy
    # nunca se instancia por fuera de ComercialModule (único punto de construcción en todo
    # el proyecto, ver ComercialModule.__init__), así que en la práctica siempre queda
    # asignado; el default None es solo una red de seguridad defensiva.
    on_editar_unidad_solicitado = None
    # Ídem, invocado por _on_editar_unidad_finished tras un guardado exitoso
    # (ver ComercialModule._on_edicion_unidad_guardada): devuelve la pestaña
    # "Unidad nueva" a modo crear en vez de dejarla mostrando la edición ya
    # guardada.
    on_edicion_unidad_guardada = None

    def _handle_editar_unidad(self, row, vin, desde_por_gestionar=False, forzar_activacion_pendiente=False,
                               desde_vigentes=False, vin_editable=False):
        """Localiza los datos actuales de esta unidad y delega la edición a
        ComercialModule (self.on_editar_unidad_solicitado), que la muestra en
        la pestaña "Unidad nueva" en modo edición (25-09-2026, refactor: antes
        abría ComercialAgregarDialog como ventana modal aquí mismo -- ver
        ComercialModule._iniciar_edicion_unidad/_on_unidad_nueva_confirmada,
        que ahora hacen ese trabajo con ComercialUnidadFormWidget embebido).

        `desde_por_gestionar` (22-09-2026, ampliado a "Gestionar Bajas" a
        pedido explícito; ajustado 25-09-2026): True cuando se edita desde
        "Por gestionar" o desde "Gestionar Bajas" (caso "cliente interesado
        en volver") del nuevo UI de Comercial (ver
        _on_accion_editar_unidad_clicked) -- activa `restringir_activacion`
        en el formulario (pestaña Operaciones SIEMPRE de solo lectura, sin
        importar el tipo de unidad) y bloquea ETAPA GESTIÓN.

        `forzar_activacion_pendiente` (25-09-2026, a pedido explícito):
        ya calculado por el llamador (ver
        ComercialModule._es_unidad_sin_contrato_sin_registro) -- True solo
        si la unidad es realmente "Sin Contrato"/"Sin Registro". Fuerza y
        restringe ESTADO COMERCIAL="Activación Pendiente" y ESTADO DE
        ACTIVACIÓN ACTUAL="Activando" -- el resto de las unidades de "Por
        gestionar" solo ven Operaciones bloqueada, sin ningún valor
        forzado. El "Editar" de Vista Completa (legacy,
        action_editar_unidad) y las demás sub-pestañas siguen sin esta
        restricción.

        `desde_vigentes` (25-09-2026, a pedido explícito): True cuando se
        edita desde "Vigentes" -- activa el modo restringido propio de esa
        sub-pestaña (ver `restringir_vigentes` en ComercialAgregarDialog):
        quita "Vencido"/"Activación Pendiente" del combo ESTADO COMERCIAL y
        deja de solo lectura toda la pestaña Operaciones, sin forzar ningún
        valor (a diferencia de `desde_por_gestionar`)."""
        if self.df_base.empty or 'VIN' not in self.df_base.columns:
            return
        coincidencias = self.df_base[self.df_base['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
        if coincidencias.empty:
            QMessageBox.warning(self, "Unidad no encontrada", f"No se encontró la unidad con VIN {vin} en los datos actuales.")
            return
        fila = coincidencias.iloc[0]
        datos_actuales = {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}

        if self.on_editar_unidad_solicitado is None:
            return
        self.on_editar_unidad_solicitado(
            datos_actuales,
            restringir_activacion=desde_por_gestionar,
            forzar_activacion_pendiente=forzar_activacion_pendiente,
            restringir_vigentes=desde_vigentes,
            vin_editable=vin_editable,
        )

    def guardar_edicion_unidad(self, vin, cambios):
        """Guarda `cambios` (dict campo->valor nuevo, ya diffeados contra los
        datos originales) sobre la unidad `vin`: mismo SaveExcelThread/
        ExcelWriter.update_cells de siempre. Extraído de _handle_editar_unidad
        (25-09-2026) para que ComercialModule._on_unidad_nueva_confirmada
        pueda invocarlo directamente tras confirmar el formulario embebido en
        "Unidad nueva", sin pasar por un diálogo modal."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando cambios de la unidad…")
        self._editar_unidad_thread = SaveExcelThread(
            self.writer, comercial_services.agregar_id_a_cambios({vin: {'VIN': vin, 'cambios': cambios}}, self.df_base),
            module_name="Comercial"
        )
        self._editar_unidad_thread.finished_signal.connect(
            lambda success: self._on_editar_unidad_finished(success, vin, cambios)
        )
        self._editar_unidad_thread.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._editar_unidad_thread.start()

    def _on_editar_unidad_finished(self, success, vin, cambios):
        QApplication.restoreOverrideCursor()
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", "No se pudieron guardar los cambios de la unidad.")
            return
        guardado_listo(self)
        dm = self.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(
                dm.df_master, comercial_services.agregar_id_a_cambios({vin: {'cambios': cambios}}, self.df_base)
            )
            dm.data_ready.emit()
        vin_final = cambios.get('VIN', vin)
        terminar_guardando(self)
        if self.on_edicion_unidad_guardada is not None:
            self.on_edicion_unidad_guardada(vin_final, cambios)

    def load_data(self):
        self._data_dirty = False
        self.df_base = comercial_services.preparar_df_base_comercial(self.data_manager.get_comercial_df())
        self._df_inconsistencias_forma_contrato = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(self.df_base)
        self._df_fechas_contrato = comercial_services.filtrar_termino_distinto_de_duracion(
            self.df_base, getattr(self.data_manager, 'termino_distinto_de_duracion', {}))
        self._actualizar_tooltip_fechas_contrato()
