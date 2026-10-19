"""Importa las unidades nuevas desde el Excel de Notas de Venta de Power BI.

El Excel trae el VIN, así que ya no se completa unidad por unidad en el
formulario: se leen las filas, se descartan los VIN que ya existen en
PruebasFM y las unidades nuevas se escriben de una vez (un solo backup, una
sola auditoría) con los valores por defecto de "Unidad nueva". Quedan con
ESTADO DE ACTIVACIÓN ACTUAL "No aplica", por lo que aparecen en la
sub-pestaña "Nuevas oportunidades" de Comercial.
"""
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.core.constants import (
    COL_ESTADO_COMERCIAL, COL_TIPO_FACTURACION, COL_ETAPA_GESTION, COL_ESTADO_ACTIVACION,
)
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.perf_log import medir
from src.services import ejecutivos_service, powerbi_import_service
from src.ui.comercial_agregar import (
    _DEFAULTS_INICIALES, _MESES, COLUMNAS_EXTRA_DEFAULT_GUION, _tipo_facturacion_default_para_forma_contrato,
)

_CAMPOS_FECHA_GUION = (
    'INICIO CONTRATO', 'TÉRMINO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
    'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM',
    'CONTRATO CREADO EN JUSTTIME', 'N CONTRATO 3PC', 'PAGO CM',
)


class ImportarPowerBIWriteWorker(QThread):
    """Única escritura a PruebasFM para todo el lote -- mismo patrón de hilo
    que el resto de las escrituras de Comercial, para no bloquear la UI con
    el backup + copia del Excel."""
    finished_signal = pyqtSignal(bool)

    def __init__(self, writer, lote, module_name="Comercial (Importación Power BI)"):
        super().__init__()
        self.writer = writer
        self.lote = lote
        self.module_name = module_name

    def run(self):
        success = self.writer.add_new_rows_batch(self.lote, module_name=self.module_name)
        self.finished_signal.emit(success)


def _plantilla_unidad_nueva():
    """Registro base de una unidad nueva: mismos valores por defecto que el
    formulario "Unidad nueva" (get_data), con ETAPA GESTIÓN según la regla
    central de negocio."""
    plantilla = dict(_DEFAULTS_INICIALES)
    tipo_facturacion = _tipo_facturacion_default_para_forma_contrato(plantilla['FORMA DE CONTRATO'])
    plantilla['TIPO DE FACTURACION'] = tipo_facturacion
    for campo in _CAMPOS_FECHA_GUION:
        plantilla.setdefault(campo, '-')
    for campo in COLUMNAS_EXTRA_DEFAULT_GUION:
        plantilla[campo] = '-'
    plantilla['ETAPA GESTIÓN'] = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: plantilla['ESTADO COMERCIAL'],
        COL_ESTADO_ACTIVACION: plantilla['ESTADO DE ACTIVACIÓN ACTUAL'],
        COL_TIPO_FACTURACION: tipo_facturacion,
        COL_ETAPA_GESTION: '',
    })
    return plantilla


def _periodo_interno(mes_sugerido, anio_sugerido):
    hoy = datetime.now()
    mes = mes_sugerido or _MESES[hoy.month - 1]
    # PruebasFM guarda el periodo en minúsculas ("septiembre - 2026")
    return f"{mes} - {anio_sugerido or hoy.year}".lower()


def _resumen_omitidos(resultado):
    lineas = []
    if resultado['existentes']:
        lineas.append(f"{len(resultado['existentes'])} ya existían en PruebasFM (se ignoran)")
    if resultado['repetidos']:
        lineas.append(f"{len(resultado['repetidos'])} repetidas dentro del Excel")
    if resultado['incompletos']:
        lineas.append(f"{len(resultado['incompletos'])} sin VIN (no se importan)")
    return lineas


def _avisar_reactivables(parent, vins):
    """Unidades en baja y desconectadas: no se importan; los VIN quedan en el
    detalle (seleccionable) para que el usuario los copie y decida."""
    if not vins:
        return
    aviso = QMessageBox(parent)
    aviso.setIcon(QMessageBox.Icon.Information)
    aviso.setWindowTitle("Unidades en baja")
    aviso.setText(
        f"{len(vins)} VIN ya existen con el contrato en baja y la unidad desconectada, así que no se importan.\n\n"
        "Si el cliente volvió, copia el VIN desde el detalle, búscalo en \"Recuperar clientes\" y crea un "
        "contrato nuevo con Editar Unidad > Crear nuevo contrato."
    )
    aviso.setDetailedText("\n".join(vins))
    aviso.exec()


def _directorio_ejecutivos():
    try:
        return ejecutivos_service.leer_ejecutivos()
    except Exception:
        return None


def iniciar_importacion_power_bi(parent, form_widget, boton_importar, flotas_unicas,
                                  dropdown_options, df_comercial, writer, on_finished, on_lote_terminado,
                                  on_lote_iniciado=None):
    """Punto de entrada único. `on_finished(exito)` se llama solo si se lanzó
    la escritura; `on_lote_terminado()` si la importación termina sin
    escribir nada (sin unidades nuevas o el usuario no confirma). Los
    parámetros `form_widget`, `flotas_unicas`, `dropdown_options` y
    `on_lote_iniciado` se conservan por compatibilidad con el llamador: el
    flujo ya no usa el formulario."""
    filepath, _ = QFileDialog.getOpenFileName(
        parent, "Seleccionar Excel de Power BI (Notas de Venta)", "", "Excel (*.xlsx)"
    )
    if not filepath:
        return

    try:
        with medir("B-8 leer_hoja_export (Main Thread)"):
            filas, texto_filtros = powerbi_import_service.leer_hoja_export(filepath)
    except Exception as e:
        QMessageBox.critical(parent, "Error al leer el Excel", str(e))
        return

    if not filas:
        QMessageBox.information(parent, "Sin registros", "El Excel seleccionado no tiene filas para importar.")
        return

    mes, anio = powerbi_import_service.detectar_periodo_desde_filtros(texto_filtros)
    resultado = powerbi_import_service.construir_altas_nuevas(
        filas, df_comercial, _plantilla_unidad_nueva(), _periodo_interno(mes, anio),
        directorio_ejecutivos=_directorio_ejecutivos(),
    )
    registros = resultado['registros']
    _avisar_reactivables(parent, resultado['reactivables'])
    omitidos = _resumen_omitidos(resultado)
    detalle_omitidos = ("\n\nNo se importan:\n- " + "\n- ".join(omitidos)) if omitidos else ""
    sin_coincidencia = resultado['ejecutivos_sin_coincidencia']
    aviso_ejecutivos = (
        "\n\nEjecutivos que no coinciden con el directorio (se guardan con el nombre de Power BI; "
        "agrégalos como alias en Administración > Ejecutivos para evitar duplicados):\n- "
        + "\n- ".join(sin_coincidencia)
    ) if sin_coincidencia else ""
    detalle_omitidos += aviso_ejecutivos

    if not registros:
        QMessageBox.information(
            parent, "Sin unidades nuevas",
            "Todas las unidades del Excel ya existen en PruebasFM o están incompletas." + detalle_omitidos
        )
        on_lote_terminado()
        return

    confirmar = QMessageBox.question(
        parent, "Confirmar importación",
        f"Se agregarán {len(registros)} unidad(es) nueva(s) a PruebasFM y quedarán en "
        f"\"Nuevas oportunidades\".{detalle_omitidos}\n\n¿Confirmar?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if confirmar != QMessageBox.StandardButton.Yes:
        on_lote_terminado()
        return

    if boton_importar is not None:
        boton_importar.setEnabled(False)
    parent._importar_powerbi_cantidad = len(registros)
    worker = ImportarPowerBIWriteWorker(writer, registros)
    # Referencia desde `parent` para que el hilo no sea recolectado antes de terminar
    parent._importar_powerbi_worker = worker
    worker.finished_signal.connect(on_finished)
    worker.start()
