"""Formulario de unidad compartido (comercial_agregar.py) para las pantallas
de Ingresos y Conciliación: JustTime, Contratos (CM) y Facturación Manual.
Siempre en modo edición y con la pestaña Operaciones de solo lectura."""
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout

from src.core.constants import COL_VIN, COL_FLOTA_VC, DROPDOWN_OPTIONS_UNIDAD
from src.services import comercial_services
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando

PESTANA_JUSTTIME_CM = "JustTime"
PESTANA_COMERCIAL = "Comercial"


def datos_unidad(df_master, vin):
    """Fila completa de `vin` en df_master como dict de textos, o None."""
    if df_master is None or df_master.empty or COL_VIN not in df_master.columns:
        return None
    coincidencias = df_master[df_master[COL_VIN].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
    if coincidencias.empty:
        return None
    return {col: ('' if pd.isna(val) else str(val)) for col, val in coincidencias.iloc[0].items()}


def editar_unidad(parent, df_master, vin, pestana=PESTANA_JUSTTIME_CM):
    """Abre el formulario de Comercial para `vin` (VIN bloqueado, sin la pestaña
    Operaciones, sin forzar valores) en la pestaña cuyo nombre contiene
    `pestana`. Devuelve el dict de campos modificados ({} si no cambió nada)
    o None si se canceló o la unidad no existe."""
    from src.ui.comercial_agregar import ComercialUnidadFormWidget
    datos = datos_unidad(df_master, vin)
    if datos is None:
        QMessageBox.warning(parent, "Unidad no encontrada", f"No se encontró la unidad con VIN {vin}.")
        return None
    flotas = sorted({v for v in df_master.get(COL_FLOTA_VC, pd.Series(dtype=str)).astype(str).str.strip()
                     if v and v != 'nan'})
    resultado = {}
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        # Mismo formulario y mismas reglas que la edición en Comercial (sin
        # el paso Operaciones), dentro de una ventana propia
        ventana = QDialog(parent)
        ventana.setWindowTitle("Editar unidad")
        lay = QVBoxLayout(ventana)
        lay.setContentsMargins(0, 0, 0, 0)
        formulario = ComercialUnidadFormWidget(
            flotas, {k: list(v) for k, v in DROPDOWN_OPTIONS_UNIDAD.items()}, df_master, ventana,
            datos_iniciales=datos, modo_edicion=True,
        )
        formulario.cargar_para_editar(datos)
        formulario.inputs['VIN'].setEnabled(False)
        lay.addWidget(formulario)
        formulario.formulario_confirmado.connect(lambda d: (resultado.update(d), ventana.accept()))
        formulario.formulario_cancelado.connect(ventana.reject)
        for i in range(formulario.tabs.count()):
            if pestana in formulario.tabs.tabText(i):
                formulario.tabs.setCurrentIndex(i)
                break
        pantalla = QApplication.primaryScreen().availableGeometry()
        ventana.resize(min(1180, pantalla.width() - 80), min(780, pantalla.height() - 80))
    finally:
        QApplication.restoreOverrideCursor()
    if ventana.exec() != QDialog.DialogCode.Accepted:
        return None
    return diferencias(datos, resultado)


def _es_vacio(valor):
    return str(valor).strip().upper() in ('', '-', 'NAN', 'NONE')


def diferencias(originales, nuevos):
    """Campos realmente modificados: ignora columnas que la unidad no tiene
    y el paso de vacío a "-" (el formulario completa vacíos con "-")."""
    return {
        campo: valor for campo, valor in nuevos.items()
        if campo in originales
        and not (_es_vacio(originales[campo]) and _es_vacio(valor))
        and str(originales[campo]).strip() != str(valor).strip()
    }


class GuardadoUnidadesMixin:
    """Guarda un lote {vin: {'VIN', 'cambios'}} con SaveExcelThread (mismo
    ExcelWriter.update_cells, backup y LogApp que Comercial) y actualiza
    df_master en memoria. Requiere self.writer y self.data_manager."""

    MODULO_LOG = "Sistema"

    def guardar_lote_unidades(self, lote, texto):
        from src.ui.comercial import SaveExcelThread
        comercial_services.agregar_id_a_cambios(lote, self.data_manager.get_contratos_actuales_df())
        self.setEnabled(False)
        mostrar_guardando(self, texto)
        self._hilo_guardado_unidades = SaveExcelThread(self.writer, lote, module_name=self.MODULO_LOG)
        self._hilo_guardado_unidades.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._hilo_guardado_unidades.finished_signal.connect(lambda ok: self._on_lote_unidades_guardado(ok, lote))
        self._hilo_guardado_unidades.start()

    def _on_lote_unidades_guardado(self, ok, lote):
        self.setEnabled(True)
        if not ok:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", "No se pudieron guardar los cambios. Verifica que PruebasFM no esté abierto.")
            return
        guardado_listo(self)
        dm = self.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, lote)
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito="Cambios guardados")

    def editar_y_guardar_unidad(self, vin, pestana=PESTANA_JUSTTIME_CM):
        actuales = self.data_manager.get_contratos_actuales_df()
        datos = datos_unidad(actuales, vin)
        if datos is not None and comercial_services.es_contrato_cerrado(datos.get('ESTADO COMERCIAL', '')):
            QMessageBox.information(
                self, "Contrato finalizado",
                "Este contrato está en Baja y es de solo lectura. El estado JustTime se puede cambiar desde el menú de estados.")
            return
        cambios = editar_unidad(self, actuales, vin, pestana)
        if cambios is None:
            return
        if not cambios:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        vin_limpio = str(vin).strip().upper()
        self.guardar_lote_unidades({vin_limpio: {'VIN': vin_limpio, 'cambios': cambios}},
                                   "Guardando cambios de la unidad…")
