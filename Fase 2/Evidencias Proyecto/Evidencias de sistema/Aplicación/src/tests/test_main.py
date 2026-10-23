import gc
import os
import sys
import json
import shutil
import unittest
import logging
from datetime import datetime

# Los tests instancian ventanas y dialogos reales de PyQt6 (ComercialModule,
# MainWindow, QMessageBox, etc.) y varios los muestran con .show(). Sin esto,
# Qt usa el plugin de pantalla real de Windows y esas ventanas aparecen
# fisicamente en el escritorio mientras corre la bateria (a veces en blanco,
# si se capturan antes de terminar de pintarse). "offscreen" hace que Qt
# renderice todo en memoria: el comportamiento que los tests verifican
# (isVisible(), tamanios, animaciones, señales) no cambia, pero nada se
# dibuja en pantalla. Debe fijarse ANTES de crear la primera QApplication
# (mas abajo, en el bloque __main__), por eso va al inicio del archivo.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from unittest.mock import patch as _patch
from PyQt6.QtWidgets import QApplication, QMessageBox
from generar_mock_data import generar_excels_prueba

# Mock global de QMessageBox para TODA la bateria: cualquier test que
# dispare un dialogo real (QMessageBox.information/warning/critical/question)
# sin mockearlo explicitamente quedaria bloqueado esperando un clic humano
# que nunca llega bajo "offscreen" (antes, con pantalla real, esto se veia
# como una ventana de confirmacion que aparecia y a veces se quedaba
# congelada). Se aplica UNA sola vez, antes de correr cualquier test, y
# nunca se detiene (dura todo el proceso). Los tests que ya hacen su propio
# @patch/context manager sobre estos mismos metodos (para simular un click
# especifico o verificar que se llamaron) siguen funcionando exactamente
# igual: mock.patch guarda y restaura el valor "actual" en ese momento (este
# mock global), nunca el original real, asi que nunca puede quedar expuesto
# un dialogo real por accidente.
for _metodo, _valor_por_defecto in [
    ('information', QMessageBox.StandardButton.Ok),
    ('warning', QMessageBox.StandardButton.Ok),
    ('critical', QMessageBox.StandardButton.Ok),
    ('question', QMessageBox.StandardButton.Yes),
]:
    _patch.object(QMessageBox, _metodo, return_value=_valor_por_defecto).start()

from test_comercial import (
    TestComercial, TestRMJaviSyncActualizaHistorial, TestRMJaviSyncColumnasAutorizadas, TestComercialTabsEstructura,
    TestComercialRevisionCM, TestConfirmarBajaCM, TestDialogoAccionCm, TestEnviarCorreoCM,
    TestEnviarCorreoOtrasSubpestanas, TestEditarUnidadComercial, TestAgregarContactoComercial,
    TestConfirmarBajaCmFlujoRealDeGuardado,
    TestReglaSinContrato, TestReglaTerminatedCm, TestRMJaviSyncNormalizaEstadoComercial,
    TestReconciliacionEstadoExpiredAlGuardarEnComercial, TestComercialFiltrosHeader,
    TestSaveExcelThreadLogsActualizadosSignal, TestSetLogsDfIntegracionConGeneralModule,
)
from test_contratos import (
    TestContratosNoLimpiaAutomaticamenteVinAusente, TestContratosReglaTerminatedCm,
    TestContratosReconciliacionEstadoExpiredAlGuardar, TestContratosReconciliacionEstadoExpiredAlImportar,
    TestContratosEdicionManualFlujoReal, TestContratosImportacionMasivaFlujoReal,
)
from test_cm_bajas_service import (
    TestTieneDatosCm, TestDetectarPosiblesBajasCm, TestActualizarCasosBajaCm,
    TestPersistenciaCasosBajaCm, TestProcesarDeteccionBajaCmIntegracion,
    TestDetectarCasosExpiredActuales, TestReconciliarCasosEstadoExpired,
    TestActualizarCasosBajaCmNoTocaCasosExpired, TestProcesarReconciliacionEstadoExpiredIntegracion,
    TestCompatibilidadOrigenCasoCsvViejo,
    TestConfirmarBajaCaso, TestProcesarConfirmacionBajaCmIntegracion,
    TestConfirmarBajaCasos, TestProcesarConfirmacionBajaCmMultipleIntegracion,
)
from test_provisiones import TestProvisiones
from test_contactos import TestContactos
from test_excel_writer import TestExcelWriter, TestUpdateCellsConfirmarBajaCm
from test_main_window import (
    TestMainWindowSincronizacion, TestTriggerLoadDataUsaRefreshIfDirty, TestSidebarToggleAnimacion,
    TestMultiSearchLineEditLimite, TestDataLoadedTriggersRevisionCmReconciliation,
    TestMainWindowLockBanner, TestGlobalSearchDebounce,
)
from test_backups import (
    TestBackups, TestPuntoCAbortaEscrituraSiBackupFalla, TestLogDeletedNoDestruyeRegistroExistente,
    TestLogDeletedSeparaPorModuloYEsquema, TestRestoreBackupValidation,
)
from test_backup_manager import TestBackupManagerSnapshot, TestBackupManagerRetencionYProgramacion
from test_configuracion import TestConfiguracionHistorialCsv, TestConfiguracionCasosBajaCmPath
from test_settings import TestNormalizacionLogCsvPath
from test_historial import (
    TestClearLogsBloqueadoTemporalmente, TestPapeleraPorModulo, TestVaciarPapeleraConBackupYMultiplesHojas,
    TestVaciarLogsModificacionesConBackup,
)
from test_mail_registro import TestMailRegistro, TestOutlookSenderThreadUsaMailRegistro
from test_mail_service import (
    TestAgruparDestinatarios, TestValidarDestinatarios, TestObtenerConfiguracionPlantilla,
    TestSinCorreoPersonalHardcodeado, TestSinReferenciasAlModoPrueba,
)
from test_mail_sync_service import TestCruzarCorreosMaestro, TestGuardarCorreosExcel, TestVinsFaltantesEnCorreos
from test_contacto_correo_service import TestActualizarCorreoPorCdb
from test_comercial_services import (
    TestProcesarDfComercial, TestCalcularKpisVigencia, TestValidarValorPegado, TestQuitarVin, TestAgregarFila,
    TestAplicarCambiosPendientes, TestValidarDuracion, TestValidarFechaDdmmyyyy, TestParsearPagoCm,
    TestFormatearPagoCm, TestAplicaReglaSinContrato, TestExcluirContratosCerrados,
    TestClasificarVigenciaContratoCalendario, TestFiltrarRenovaciones, TestFiltrarVencimientos,
    TestFiltrarGestionarBajas, TestFiltrarPorGestionar, TestConstruirMascaraBusqueda,
    TestFormatearDiasRestantes, TestParsearDiasRestantes,
    TestCalcularEtapaGestionEsperadaVectorizadoEquivaleARowWise, TestContratosPorId,
)
from test_vin_service import TestObtenerModeloDesdeVin
from test_comercial_agregar import (
    TestComercialAgregarDialogAutoModelo, TestComercialAgregarDialogGestionUnidades,
    TestComercialAgregarDialogModoLote, TestComercialAgregarDialogPrecargaValoresLegados,
    TestComercialUnidadFormContratosPorId,
)
from test_theme_manager import TestThemeManagerIconCache
from test_general import (
    TestBuildUnidadesDf, TestFiltrarContactosPorCdb,
    TestConstruirMapaDirectorEmpresaPbi, TestPowerBiDirectorEmpresaLoaderThread, TestAplicarFiltrosUnidades,
    TestEstadoActivacionColores, TestResolverTextoFlotaVcSinCliente,
    TestPopulateContactCards, TestAplicarBusquedaUnidades,
    TestBuscadorGlobalTresPestanas, TestClientesYUnidadesColumnasVisibles, TestFiltrarHistorialPorVin,
    TestValorFicha, TestSeleccionVinUnidades, TestDetalleClienteSinHistorial,
    TestAgregarContactoCliente,
    TestGeneralDataPrepThread, TestGeneralDataPrepThreadEquivaleAlPipelineSincronoAnterior, TestContratosAnterioresEnUnidades,
    TestLoadDataGuardDeReentrancia, TestRenderDiferidoPestanasOcultasFase5,
)
from test_dataframe_formatter import (
    TestCalcularTerminoContrato, TestBajaNoLimpiaCamposContractualesAlCargar, TestNormalizaEstadoDelCm,
)
from test_data_manager import (
    TestFormatearColumnaFechaLegadoCasosBase, TestFormatearColumnaFechaLegadoColumnaCompleta,
    TestMainDataLoaderThreadLecturaExcelPrincipal,
)
from test_provisiones_services import (
    TestFormatearMoneda, TestValidarCantidadMeses, TestParsearDynafleet, TestCalcularMontosProvision,
    TestLimpiarCantidadMesesDisplay, TestConstruirCambiosProvisiones, TestConvertirPeriodoInterno,
    TestParsearNumeroUf, TestMapearIndustria, TestNormalizarCliente, TestConstruirLookupRazonSocial,
    TestBuscarCandidatosPorCliente, TestMapearTipoServicioDesdePlan,
)
from test_facturacion_manual_service import (
    TestFiltrarFacturacionManual, TestObtenerEmpresas, TestObtenerUnidadesEmpresa,
    TestSeleccionarColumnasDetalle, TestConstruirContextoEmpresa,
)
from test_facturacion_manual_template import (
    TestConstruirPlantillaBase, TestGenerarPlantillaBase,
)
from test_mail_dialog_correo_faltante import (
    TestMailDialogCeldaCorreoFaltante, TestContactosAddDialogPrefillBloqueado,
    TestMailDialogPreseleccionDesdeGestionarCM,
)
from test_table_sorting import (
    TestVolvoTableWidgetSorting, TestVolvoTableWidgetMenuEliminados, TestInstalacionesMenuType,
    TestPandasTableModelHeaderData, TestSetTableIdDescartaEstadoDesactualizado,
    TestPandasTableModelTerminoContratoForeground,
)
from test_contactos_service import (
    TestNormalizarIdContacto, TestFavoritos, TestMigrarFavoritosLegacy, TestGenerarNuevoIdContacto,
    TestFormatearTelefonoChile, TestAplicarCambiosPendientesContactos, TestAplicarFiltroCheckbox,
    TestBuscarTextoGlobal, TestOrdenarPorFavoritosEId,
)
from test_dirty_refresh import (
    TestActualizacionDiferidaComercial, TestActualizacionDiferidaOtrosModulos, TestHistorialDualSenal,
    TestVisibilidadDentroDeTabs, TestConfiguracionSinCambios, TestGeneralCargaInicial,
)
from test_operaciones_services import (
    TestFiltrarActivaciones, TestFiltrarBajas, TestArmarExportContactosEjecutivo,
    TestCalcularCambiosMarcarDesconectado, TestCicloBajaOperacionesComercial, TestOperacionesPorContrato,
)
from test_quality_sync import (
    TestSincronizacionNormal, TestIdempotencia, TestNuevoTestNoRenumera, TestMetodoNuevoEnClaseExistente,
    TestNuevoTestAlfabeticamenteEnMedioNoRenumera, TestFailNoRompeSincronizacion,
    TestErrorConocidoNoDuplicaDefecto, TestErrorDesconocidoQuedaComoAviso,
    TestErrorDeEscrituraNoRompeElResto, TestVolskipQualitySyncOmite,
)
from test_file_lock_monitor import (
    TestFileLockMonitorArchivoDisponible, TestFileLockMonitorConfirmacion,
    TestFileLockMonitorCuatroArchivosIndependientes, TestFileLockMonitorIgnoraGuardadoPropio,
)
from test_app_lock_coordinator import (
    TestAppLockCoordinatorTodosDisponibles, TestAppLockCoordinatorUnArchivoOcupado,
    TestAppLockCoordinatorDosArchivosOcupados, TestAppLockCoordinatorVueltaANormal,
    TestAppLockCoordinatorTransitorioNoBloquea, TestAppLockCoordinatorGuardadoPropio,
    TestAppLockCoordinatorSenalEstadoCambiado, TestAppLockCoordinatorArchivosOcupadosCambiado,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# config.settings.py resuelve su app_config.json dos niveles arriba de config/settings.py,
# es decir, en la raíz del proyecto. Debemos apuntar al MISMO archivo, si no,
# importlib.reload(config.settings) vuelve a leer las rutas reales de producción.
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'app_config.json')
BACKUP_CONFIG_PATH = os.path.join(PROJECT_ROOT, 'app_config_backup.json')
MOCK_DIR = os.path.join(BASE_DIR, 'mock_data')
LOG_FILE = os.path.join(BASE_DIR, 'logs', 'test.log')
# src/core/dataframe_formatter.py configura el logger raíz (via
# logging.basicConfig) apuntando siempre a <raiz>/logs/sistema.log, sin
# distinguir si corre la app real o los tests. Como excel_writer.py y
# backup_manager.py registran ahi (logging.getLogger(__name__) hereda el
# handler raiz), los fallos simulados a propósito en los tests (backup
# bloqueado, Excel corrupto, etc.) terminaban ensuciando el log real que lee
# Configuración. SISTEMA_LOG_TEST redirige ese handler mientras corren los
# tests, y se restaura el original en teardown_sandbox().
SISTEMA_LOG_TEST = os.path.join(BASE_DIR, 'logs', 'sistema_test.log')
_original_root_file_handlers = []

import config.settings
config.settings.EXCEL_PATH = os.path.join(MOCK_DIR, "PruebasFM_Test.xlsx").replace('\\', '/')
config.settings.PROVISION_EXCEL_PATH = os.path.join(MOCK_DIR, "provisionFelipe_Test.xlsx").replace('\\', '/')
config.settings.CONTACTOS_EXCEL_PATH = os.path.join(MOCK_DIR, "contactos_Test.xlsx").replace('\\', '/')
config.settings.LOG_EXCEL_PATH = os.path.join(MOCK_DIR, "LogApp_Test.xlsx").replace('\\', '/')
config.settings.DELETED_LOG_EXCEL_PATH = os.path.join(MOCK_DIR, "RegistroEliminado_Test.xlsx").replace('\\', '/')
config.settings.METAS_VC_PATH = os.path.join(MOCK_DIR, "MetasVC_Test.csv").replace('\\', '/')

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logger = logging.getLogger("TestRunner")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s', "%Y-%m-%d %H:%M:%S"))
logger.addHandler(fh)
ch = logging.StreamHandler()
logger.addHandler(ch)

def _redirigir_logging_global_a_tests():
    """Reemplaza el/los FileHandler del logger raíz (los que apuntan al
    logs/sistema.log real, configurados por dataframe_formatter.py al
    importar el resto de módulos) por uno que escribe en
    src/tests/logs/sistema_test.log. Guarda los handlers originales en
    _original_root_file_handlers para restaurarlos en teardown_sandbox()."""
    os.makedirs(os.path.dirname(SISTEMA_LOG_TEST), exist_ok=True)
    root_logger = logging.getLogger()

    for h in [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]:
        root_logger.removeHandler(h)
        _original_root_file_handlers.append(h)

    test_handler = logging.FileHandler(SISTEMA_LOG_TEST, mode='w', encoding='utf-8')
    test_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(test_handler)

def _restaurar_logging_global():
    root_logger = logging.getLogger()
    for h in [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]:
        root_logger.removeHandler(h)
        h.close()
    for h in _original_root_file_handlers:
        root_logger.addHandler(h)
    _original_root_file_handlers.clear()

def setup_sandbox():
    _redirigir_logging_global_a_tests()
    logger.info("=== INICIANDO ENTORNO DE PRUEBAS (SANDBOX) ===")
    logger.info("Regenerando bases de datos falsas (Clean Slate)...")
    generar_excels_prueba(MOCK_DIR)
    
    if os.path.exists(CONFIG_PATH):
        shutil.copy2(CONFIG_PATH, BACKUP_CONFIG_PATH)
        logger.info("Respaldo de app_config.json creado.")

    mock_config = {
        "EXCEL_PATH": os.path.join(MOCK_DIR, "PruebasFM_Test.xlsx").replace('\\', '/'),
        "PROVISION_EXCEL_PATH": os.path.join(MOCK_DIR, "provisionFelipe_Test.xlsx").replace('\\', '/'),
        "CONTACTOS_EXCEL_PATH": os.path.join(MOCK_DIR, "contactos_Test.xlsx").replace('\\', '/'),
        "INSTALACIONES_PATH": os.path.join(MOCK_DIR, "Instalaciones_Test.xlsx").replace('\\', '/'),
        "DELETED_LOG_EXCEL_PATH": os.path.join(MOCK_DIR, "RegistroEliminado_Test.xlsx").replace('\\', '/'),
        "LOG_EXCEL_PATH": os.path.join(MOCK_DIR, "LogApp_Test.xlsx").replace('\\', '/')
    }
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(mock_config, f, indent=4)
        
    # Forzar recarga de configuración en el módulo settings global
    import importlib
    import config.settings
    importlib.reload(config.settings)
    
    # Limpiar instancia previa del Singleton DataManager para que lea el nuevo EXCEL_PATH
    import src.core.data_manager
    src.core.data_manager.DataManager._instance = None
    src.core.data_manager.DataManager._qobject_initialized = False
    
    logger.info("Rutas falsas inyectadas y DataManager reiniciado.")

def teardown_sandbox():
    logger.info("=== RESTAURANDO ENTORNO ORIGINAL ===")
    if os.path.exists(BACKUP_CONFIG_PATH):
        shutil.copy2(BACKUP_CONFIG_PATH, CONFIG_PATH)
        os.remove(BACKUP_CONFIG_PATH)
        logger.info("Rutas originales restauradas con éxito.")
    _restaurar_logging_global()

if __name__ == '__main__':
    setup_sandbox()
    app = QApplication(sys.argv)

    suite_comercial = unittest.TestLoader().loadTestsFromTestCase(TestComercial)
    suite_comercial_filtros_header = unittest.TestLoader().loadTestsFromTestCase(TestComercialFiltrosHeader)
    suite_save_excel_thread_logs_signal = unittest.TestLoader().loadTestsFromTestCase(TestSaveExcelThreadLogsActualizadosSignal)
    suite_set_logs_df_integracion_general = unittest.TestLoader().loadTestsFromTestCase(TestSetLogsDfIntegracionConGeneralModule)
    suite_provisiones = unittest.TestLoader().loadTestsFromTestCase(TestProvisiones)
    suite_contactos = unittest.TestLoader().loadTestsFromTestCase(TestContactos)
    suite_excel_writer = unittest.TestLoader().loadTestsFromTestCase(TestExcelWriter)
    suite_update_cells_confirmar_baja_cm = unittest.TestLoader().loadTestsFromTestCase(TestUpdateCellsConfirmarBajaCm)
    suite_main_window = unittest.TestLoader().loadTestsFromTestCase(TestMainWindowSincronizacion)
    suite_trigger_load_data_dirty = unittest.TestLoader().loadTestsFromTestCase(TestTriggerLoadDataUsaRefreshIfDirty)
    suite_sidebar_toggle = unittest.TestLoader().loadTestsFromTestCase(TestSidebarToggleAnimacion)
    suite_multi_search_limite = unittest.TestLoader().loadTestsFromTestCase(TestMultiSearchLineEditLimite)
    suite_global_search_debounce = unittest.TestLoader().loadTestsFromTestCase(TestGlobalSearchDebounce)
    suite_theme_manager_icon_cache = unittest.TestLoader().loadTestsFromTestCase(TestThemeManagerIconCache)
    suite_revision_cm_al_cargar = unittest.TestLoader().loadTestsFromTestCase(TestDataLoadedTriggersRevisionCmReconciliation)
    suite_main_window_lock_banner = unittest.TestLoader().loadTestsFromTestCase(TestMainWindowLockBanner)
    suite_backups = unittest.TestLoader().loadTestsFromTestCase(TestBackups)
    suite_punto_c = unittest.TestLoader().loadTestsFromTestCase(TestPuntoCAbortaEscrituraSiBackupFalla)
    suite_log_deleted = unittest.TestLoader().loadTestsFromTestCase(TestLogDeletedNoDestruyeRegistroExistente)
    suite_log_deleted_por_modulo = unittest.TestLoader().loadTestsFromTestCase(TestLogDeletedSeparaPorModuloYEsquema)
    suite_restore_backup = unittest.TestLoader().loadTestsFromTestCase(TestRestoreBackupValidation)
    suite_backup_manager_snapshot = unittest.TestLoader().loadTestsFromTestCase(TestBackupManagerSnapshot)
    suite_backup_manager_retencion = unittest.TestLoader().loadTestsFromTestCase(TestBackupManagerRetencionYProgramacion)
    suite_rm_javi_historial = unittest.TestLoader().loadTestsFromTestCase(TestRMJaviSyncActualizaHistorial)
    suite_rm_javi_columnas_autorizadas = unittest.TestLoader().loadTestsFromTestCase(TestRMJaviSyncColumnasAutorizadas)
    suite_comercial_tabs = unittest.TestLoader().loadTestsFromTestCase(TestComercialTabsEstructura)
    suite_comercial_revision_cm = unittest.TestLoader().loadTestsFromTestCase(TestComercialRevisionCM)
    suite_confirmar_baja_cm = unittest.TestLoader().loadTestsFromTestCase(TestConfirmarBajaCM)
    suite_enviar_correo_cm = unittest.TestLoader().loadTestsFromTestCase(TestEnviarCorreoCM)
    suite_enviar_correo_otras_subpestanas = unittest.TestLoader().loadTestsFromTestCase(TestEnviarCorreoOtrasSubpestanas)
    suite_editar_unidad_comercial = unittest.TestLoader().loadTestsFromTestCase(TestEditarUnidadComercial)
    suite_agregar_contacto_comercial = unittest.TestLoader().loadTestsFromTestCase(TestAgregarContactoComercial)
    suite_dialogo_accion_cm = unittest.TestLoader().loadTestsFromTestCase(TestDialogoAccionCm)
    suite_confirmar_baja_cm_flujo_real = unittest.TestLoader().loadTestsFromTestCase(TestConfirmarBajaCmFlujoRealDeGuardado)
    suite_regla_sin_contrato = unittest.TestLoader().loadTestsFromTestCase(TestReglaSinContrato)
    suite_regla_terminated_cm = unittest.TestLoader().loadTestsFromTestCase(TestReglaTerminatedCm)
    suite_reconciliacion_expired_comercial = unittest.TestLoader().loadTestsFromTestCase(TestReconciliacionEstadoExpiredAlGuardarEnComercial)
    suite_rm_javi_normaliza_estado_comercial = unittest.TestLoader().loadTestsFromTestCase(TestRMJaviSyncNormalizaEstadoComercial)
    suite_contratos_no_limpia_vin_ausente = unittest.TestLoader().loadTestsFromTestCase(TestContratosNoLimpiaAutomaticamenteVinAusente)
    suite_contratos_regla_terminated_cm = unittest.TestLoader().loadTestsFromTestCase(TestContratosReglaTerminatedCm)
    suite_contratos_reconciliacion_expired_guardar = unittest.TestLoader().loadTestsFromTestCase(TestContratosReconciliacionEstadoExpiredAlGuardar)
    suite_contratos_reconciliacion_expired_importar = unittest.TestLoader().loadTestsFromTestCase(TestContratosReconciliacionEstadoExpiredAlImportar)
    suite_contratos_edicion_manual_flujo_real = unittest.TestLoader().loadTestsFromTestCase(TestContratosEdicionManualFlujoReal)
    suite_contratos_importacion_masiva_flujo_real = unittest.TestLoader().loadTestsFromTestCase(TestContratosImportacionMasivaFlujoReal)
    suite_cm_bajas_tiene_datos = unittest.TestLoader().loadTestsFromTestCase(TestTieneDatosCm)
    suite_cm_bajas_detectar = unittest.TestLoader().loadTestsFromTestCase(TestDetectarPosiblesBajasCm)
    suite_cm_bajas_actualizar = unittest.TestLoader().loadTestsFromTestCase(TestActualizarCasosBajaCm)
    suite_cm_bajas_persistencia = unittest.TestLoader().loadTestsFromTestCase(TestPersistenciaCasosBajaCm)
    suite_cm_bajas_integracion = unittest.TestLoader().loadTestsFromTestCase(TestProcesarDeteccionBajaCmIntegracion)
    suite_cm_expired_detectar = unittest.TestLoader().loadTestsFromTestCase(TestDetectarCasosExpiredActuales)
    suite_cm_expired_reconciliar = unittest.TestLoader().loadTestsFromTestCase(TestReconciliarCasosEstadoExpired)
    suite_cm_ausencia_no_toca_expired = unittest.TestLoader().loadTestsFromTestCase(TestActualizarCasosBajaCmNoTocaCasosExpired)
    suite_cm_expired_integracion = unittest.TestLoader().loadTestsFromTestCase(TestProcesarReconciliacionEstadoExpiredIntegracion)
    suite_cm_origen_caso_compatibilidad = unittest.TestLoader().loadTestsFromTestCase(TestCompatibilidadOrigenCasoCsvViejo)
    suite_cm_confirmar_baja_caso = unittest.TestLoader().loadTestsFromTestCase(TestConfirmarBajaCaso)
    suite_cm_confirmar_baja_integracion = unittest.TestLoader().loadTestsFromTestCase(TestProcesarConfirmacionBajaCmIntegracion)
    suite_cm_confirmar_baja_casos = unittest.TestLoader().loadTestsFromTestCase(TestConfirmarBajaCasos)
    suite_cm_confirmar_baja_multiple_integracion = unittest.TestLoader().loadTestsFromTestCase(TestProcesarConfirmacionBajaCmMultipleIntegracion)
    suite_configuracion_historial = unittest.TestLoader().loadTestsFromTestCase(TestConfiguracionHistorialCsv)
    suite_configuracion_casos_baja_cm_path = unittest.TestLoader().loadTestsFromTestCase(TestConfiguracionCasosBajaCmPath)
    suite_normalizacion_config = unittest.TestLoader().loadTestsFromTestCase(TestNormalizacionLogCsvPath)
    suite_clear_logs_bloqueado = unittest.TestLoader().loadTestsFromTestCase(TestClearLogsBloqueadoTemporalmente)
    suite_papelera_por_modulo = unittest.TestLoader().loadTestsFromTestCase(TestPapeleraPorModulo)
    suite_vaciar_papelera_backup = unittest.TestLoader().loadTestsFromTestCase(TestVaciarPapeleraConBackupYMultiplesHojas)
    suite_vaciar_logs_modificaciones_backup = unittest.TestLoader().loadTestsFromTestCase(TestVaciarLogsModificacionesConBackup)
    suite_mail_registro = unittest.TestLoader().loadTestsFromTestCase(TestMailRegistro)
    suite_outlook_registro = unittest.TestLoader().loadTestsFromTestCase(TestOutlookSenderThreadUsaMailRegistro)
    suite_agrupar_destinatarios = unittest.TestLoader().loadTestsFromTestCase(TestAgruparDestinatarios)
    suite_validar_destinatarios = unittest.TestLoader().loadTestsFromTestCase(TestValidarDestinatarios)
    suite_config_plantilla = unittest.TestLoader().loadTestsFromTestCase(TestObtenerConfiguracionPlantilla)
    suite_sin_correo_hardcodeado = unittest.TestLoader().loadTestsFromTestCase(TestSinCorreoPersonalHardcodeado)
    suite_sin_modo_prueba = unittest.TestLoader().loadTestsFromTestCase(TestSinReferenciasAlModoPrueba)
    suite_cruzar_correos_maestro = unittest.TestLoader().loadTestsFromTestCase(TestCruzarCorreosMaestro)
    suite_guardar_correos_excel = unittest.TestLoader().loadTestsFromTestCase(TestGuardarCorreosExcel)
    suite_vins_faltantes_en_correos = unittest.TestLoader().loadTestsFromTestCase(TestVinsFaltantesEnCorreos)
    suite_actualizar_correo_por_cdb = unittest.TestLoader().loadTestsFromTestCase(TestActualizarCorreoPorCdb)
    suite_procesar_df_comercial = unittest.TestLoader().loadTestsFromTestCase(TestProcesarDfComercial)
    suite_kpis_vigencia = unittest.TestLoader().loadTestsFromTestCase(TestCalcularKpisVigencia)
    suite_validar_valor_pegado = unittest.TestLoader().loadTestsFromTestCase(TestValidarValorPegado)
    suite_quitar_vin = unittest.TestLoader().loadTestsFromTestCase(TestQuitarVin)
    suite_contratos_por_id = unittest.TestLoader().loadTestsFromTestCase(TestContratosPorId)
    suite_form_contratos_por_id = unittest.TestLoader().loadTestsFromTestCase(TestComercialUnidadFormContratosPorId)
    suite_agregar_fila = unittest.TestLoader().loadTestsFromTestCase(TestAgregarFila)
    suite_aplicar_cambios_pendientes = unittest.TestLoader().loadTestsFromTestCase(TestAplicarCambiosPendientes)
    suite_validar_duracion = unittest.TestLoader().loadTestsFromTestCase(TestValidarDuracion)
    suite_validar_fecha_ddmmyyyy = unittest.TestLoader().loadTestsFromTestCase(TestValidarFechaDdmmyyyy)
    suite_parsear_pago_cm = unittest.TestLoader().loadTestsFromTestCase(TestParsearPagoCm)
    suite_formatear_pago_cm = unittest.TestLoader().loadTestsFromTestCase(TestFormatearPagoCm)
    suite_aplica_regla_sin_contrato = unittest.TestLoader().loadTestsFromTestCase(TestAplicaReglaSinContrato)
    suite_excluir_contratos_cerrados = unittest.TestLoader().loadTestsFromTestCase(TestExcluirContratosCerrados)
    suite_clasificar_vigencia_calendario = unittest.TestLoader().loadTestsFromTestCase(TestClasificarVigenciaContratoCalendario)
    suite_filtrar_renovaciones = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarRenovaciones)
    suite_filtrar_vencimientos = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarVencimientos)
    suite_filtrar_gestionar_bajas = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarGestionarBajas)
    suite_filtrar_por_gestionar = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarPorGestionar)
    suite_construir_mascara_busqueda = unittest.TestLoader().loadTestsFromTestCase(TestConstruirMascaraBusqueda)
    suite_formatear_dias_restantes = unittest.TestLoader().loadTestsFromTestCase(TestFormatearDiasRestantes)
    suite_parsear_dias_restantes = unittest.TestLoader().loadTestsFromTestCase(TestParsearDiasRestantes)
    suite_etapa_gestion_vectorizado_equivale = unittest.TestLoader().loadTestsFromTestCase(TestCalcularEtapaGestionEsperadaVectorizadoEquivaleARowWise)
    suite_obtener_modelo_desde_vin = unittest.TestLoader().loadTestsFromTestCase(TestObtenerModeloDesdeVin)
    suite_comercial_agregar_auto_modelo = unittest.TestLoader().loadTestsFromTestCase(TestComercialAgregarDialogAutoModelo)
    suite_comercial_agregar_gestion_unidades = unittest.TestLoader().loadTestsFromTestCase(TestComercialAgregarDialogGestionUnidades)
    suite_comercial_agregar_modo_lote = unittest.TestLoader().loadTestsFromTestCase(TestComercialAgregarDialogModoLote)
    suite_comercial_agregar_precarga_legados = unittest.TestLoader().loadTestsFromTestCase(TestComercialAgregarDialogPrecargaValoresLegados)
    suite_build_unidades_df = unittest.TestLoader().loadTestsFromTestCase(TestBuildUnidadesDf)
    suite_filtrar_contactos_por_cdb = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarContactosPorCdb)
    suite_construir_mapa_director_empresa_pbi = unittest.TestLoader().loadTestsFromTestCase(TestConstruirMapaDirectorEmpresaPbi)
    suite_powerbi_director_empresa_loader_thread = unittest.TestLoader().loadTestsFromTestCase(TestPowerBiDirectorEmpresaLoaderThread)
    suite_aplicar_filtros_unidades = unittest.TestLoader().loadTestsFromTestCase(TestAplicarFiltrosUnidades)
    suite_estado_activacion_colores = unittest.TestLoader().loadTestsFromTestCase(TestEstadoActivacionColores)
    suite_resolver_texto_flota_vc_sin_cliente = unittest.TestLoader().loadTestsFromTestCase(TestResolverTextoFlotaVcSinCliente)
    suite_populate_contact_cards = unittest.TestLoader().loadTestsFromTestCase(TestPopulateContactCards)
    suite_aplicar_busqueda_unidades = unittest.TestLoader().loadTestsFromTestCase(TestAplicarBusquedaUnidades)
    suite_buscador_global_tres_pestanas = unittest.TestLoader().loadTestsFromTestCase(TestBuscadorGlobalTresPestanas)
    suite_clientes_unidades_columnas_visibles = unittest.TestLoader().loadTestsFromTestCase(TestClientesYUnidadesColumnasVisibles)
    suite_filtrar_historial_por_vin = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarHistorialPorVin)
    suite_valor_ficha = unittest.TestLoader().loadTestsFromTestCase(TestValorFicha)
    suite_seleccion_vin_unidades = unittest.TestLoader().loadTestsFromTestCase(TestSeleccionVinUnidades)
    suite_agregar_contacto_cliente = unittest.TestLoader().loadTestsFromTestCase(TestAgregarContactoCliente)
    suite_detalle_cliente_sin_historial = unittest.TestLoader().loadTestsFromTestCase(TestDetalleClienteSinHistorial)
    suite_general_data_prep_thread = unittest.TestLoader().loadTestsFromTestCase(TestGeneralDataPrepThread)
    suite_contratos_anteriores_unidades = unittest.TestLoader().loadTestsFromTestCase(TestContratosAnterioresEnUnidades)
    suite_general_data_prep_equivale = unittest.TestLoader().loadTestsFromTestCase(TestGeneralDataPrepThreadEquivaleAlPipelineSincronoAnterior)
    suite_general_load_data_reentrancia = unittest.TestLoader().loadTestsFromTestCase(TestLoadDataGuardDeReentrancia)
    suite_general_render_diferido_pestanas = unittest.TestLoader().loadTestsFromTestCase(TestRenderDiferidoPestanasOcultasFase5)
    suite_calcular_termino_contrato = unittest.TestLoader().loadTestsFromTestCase(TestCalcularTerminoContrato)
    suite_baja_no_limpia_al_cargar = unittest.TestLoader().loadTestsFromTestCase(TestBajaNoLimpiaCamposContractualesAlCargar)
    suite_normaliza_estado_del_cm = unittest.TestLoader().loadTestsFromTestCase(TestNormalizaEstadoDelCm)
    suite_formatear_columna_fecha_legado_base = unittest.TestLoader().loadTestsFromTestCase(TestFormatearColumnaFechaLegadoCasosBase)
    suite_formatear_columna_fecha_legado_completa = unittest.TestLoader().loadTestsFromTestCase(TestFormatearColumnaFechaLegadoColumnaCompleta)
    suite_main_data_loader_lectura_excel = unittest.TestLoader().loadTestsFromTestCase(TestMainDataLoaderThreadLecturaExcelPrincipal)
    suite_formatear_moneda = unittest.TestLoader().loadTestsFromTestCase(TestFormatearMoneda)
    suite_validar_cantidad_meses = unittest.TestLoader().loadTestsFromTestCase(TestValidarCantidadMeses)
    suite_parsear_dynafleet = unittest.TestLoader().loadTestsFromTestCase(TestParsearDynafleet)
    suite_calcular_montos_provision = unittest.TestLoader().loadTestsFromTestCase(TestCalcularMontosProvision)
    suite_limpiar_cantidad_meses_display = unittest.TestLoader().loadTestsFromTestCase(TestLimpiarCantidadMesesDisplay)
    suite_construir_cambios_provisiones = unittest.TestLoader().loadTestsFromTestCase(TestConstruirCambiosProvisiones)
    suite_convertir_periodo_interno = unittest.TestLoader().loadTestsFromTestCase(TestConvertirPeriodoInterno)
    suite_parsear_numero_uf = unittest.TestLoader().loadTestsFromTestCase(TestParsearNumeroUf)
    suite_mapear_industria = unittest.TestLoader().loadTestsFromTestCase(TestMapearIndustria)
    suite_normalizar_cliente = unittest.TestLoader().loadTestsFromTestCase(TestNormalizarCliente)
    suite_construir_lookup_razon_social = unittest.TestLoader().loadTestsFromTestCase(TestConstruirLookupRazonSocial)
    suite_buscar_candidatos_por_cliente = unittest.TestLoader().loadTestsFromTestCase(TestBuscarCandidatosPorCliente)
    suite_mapear_tipo_servicio_desde_plan = unittest.TestLoader().loadTestsFromTestCase(TestMapearTipoServicioDesdePlan)
    suite_mail_dialog_celda_correo = unittest.TestLoader().loadTestsFromTestCase(TestMailDialogCeldaCorreoFaltante)
    suite_contactos_add_prefill = unittest.TestLoader().loadTestsFromTestCase(TestContactosAddDialogPrefillBloqueado)
    suite_mail_dialog_preseleccion = unittest.TestLoader().loadTestsFromTestCase(TestMailDialogPreseleccionDesdeGestionarCM)
    suite_table_sorting = unittest.TestLoader().loadTestsFromTestCase(TestVolvoTableWidgetSorting)
    suite_menu_eliminados = unittest.TestLoader().loadTestsFromTestCase(TestVolvoTableWidgetMenuEliminados)
    suite_instalaciones_menu = unittest.TestLoader().loadTestsFromTestCase(TestInstalacionesMenuType)
    suite_header_data_fuera_de_rango = unittest.TestLoader().loadTestsFromTestCase(TestPandasTableModelHeaderData)
    suite_set_table_id_descarta_estado = unittest.TestLoader().loadTestsFromTestCase(TestSetTableIdDescartaEstadoDesactualizado)
    suite_termino_contrato_foreground = unittest.TestLoader().loadTestsFromTestCase(TestPandasTableModelTerminoContratoForeground)
    suite_normalizar_id_contacto = unittest.TestLoader().loadTestsFromTestCase(TestNormalizarIdContacto)
    suite_favoritos = unittest.TestLoader().loadTestsFromTestCase(TestFavoritos)
    suite_migrar_favoritos_legacy = unittest.TestLoader().loadTestsFromTestCase(TestMigrarFavoritosLegacy)
    suite_generar_nuevo_id_contacto = unittest.TestLoader().loadTestsFromTestCase(TestGenerarNuevoIdContacto)
    suite_formatear_telefono_chile = unittest.TestLoader().loadTestsFromTestCase(TestFormatearTelefonoChile)
    suite_aplicar_cambios_pendientes_contactos = unittest.TestLoader().loadTestsFromTestCase(TestAplicarCambiosPendientesContactos)
    suite_aplicar_filtro_checkbox = unittest.TestLoader().loadTestsFromTestCase(TestAplicarFiltroCheckbox)
    suite_buscar_texto_global = unittest.TestLoader().loadTestsFromTestCase(TestBuscarTextoGlobal)
    suite_ordenar_por_favoritos_e_id = unittest.TestLoader().loadTestsFromTestCase(TestOrdenarPorFavoritosEId)
    suite_filtrar_activaciones = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarActivaciones)
    suite_filtrar_bajas = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarBajas)
    suite_armar_export_contactos_ejecutivo = unittest.TestLoader().loadTestsFromTestCase(TestArmarExportContactosEjecutivo)
    suite_calcular_cambios_marcar_desconectado = unittest.TestLoader().loadTestsFromTestCase(TestCalcularCambiosMarcarDesconectado)
    suite_ciclo_baja_operaciones_comercial = unittest.TestLoader().loadTestsFromTestCase(TestCicloBajaOperacionesComercial)
    suite_operaciones_por_contrato = unittest.TestLoader().loadTestsFromTestCase(TestOperacionesPorContrato)
    suite_quality_sync_normal = unittest.TestLoader().loadTestsFromTestCase(TestSincronizacionNormal)
    suite_quality_sync_idempotencia = unittest.TestLoader().loadTestsFromTestCase(TestIdempotencia)
    suite_quality_sync_nuevo_test = unittest.TestLoader().loadTestsFromTestCase(TestNuevoTestNoRenumera)
    suite_quality_sync_metodo_nuevo = unittest.TestLoader().loadTestsFromTestCase(TestMetodoNuevoEnClaseExistente)
    suite_quality_sync_alfabetico = unittest.TestLoader().loadTestsFromTestCase(
        TestNuevoTestAlfabeticamenteEnMedioNoRenumera)
    suite_quality_sync_fail = unittest.TestLoader().loadTestsFromTestCase(TestFailNoRompeSincronizacion)
    suite_quality_sync_error_conocido = unittest.TestLoader().loadTestsFromTestCase(
        TestErrorConocidoNoDuplicaDefecto)
    suite_quality_sync_error_desconocido = unittest.TestLoader().loadTestsFromTestCase(
        TestErrorDesconocidoQuedaComoAviso)
    suite_quality_sync_error_escritura = unittest.TestLoader().loadTestsFromTestCase(
        TestErrorDeEscrituraNoRompeElResto)
    suite_quality_sync_skip = unittest.TestLoader().loadTestsFromTestCase(TestVolskipQualitySyncOmite)
    suite_file_lock_monitor_disponible = unittest.TestLoader().loadTestsFromTestCase(TestFileLockMonitorArchivoDisponible)
    suite_file_lock_monitor_confirmacion = unittest.TestLoader().loadTestsFromTestCase(TestFileLockMonitorConfirmacion)
    suite_file_lock_monitor_cuatro_archivos = unittest.TestLoader().loadTestsFromTestCase(TestFileLockMonitorCuatroArchivosIndependientes)
    suite_file_lock_monitor_guardado_propio = unittest.TestLoader().loadTestsFromTestCase(TestFileLockMonitorIgnoraGuardadoPropio)
    suite_app_lock_todos_disponibles = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorTodosDisponibles)
    suite_app_lock_un_archivo_ocupado = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorUnArchivoOcupado)
    suite_app_lock_dos_archivos_ocupados = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorDosArchivosOcupados)
    suite_app_lock_vuelta_normal = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorVueltaANormal)
    suite_app_lock_transitorio = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorTransitorioNoBloquea)
    suite_app_lock_guardado_propio = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorGuardadoPropio)
    suite_app_lock_senal_estado = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorSenalEstadoCambiado)
    suite_app_lock_archivos_ocupados_cambiado = unittest.TestLoader().loadTestsFromTestCase(TestAppLockCoordinatorArchivosOcupadosCambiado)
    suite_dirty_comercial = unittest.TestLoader().loadTestsFromTestCase(TestActualizacionDiferidaComercial)
    suite_dirty_otros_modulos = unittest.TestLoader().loadTestsFromTestCase(TestActualizacionDiferidaOtrosModulos)
    suite_dirty_historial = unittest.TestLoader().loadTestsFromTestCase(TestHistorialDualSenal)
    suite_dirty_tabs = unittest.TestLoader().loadTestsFromTestCase(TestVisibilidadDentroDeTabs)
    suite_dirty_configuracion = unittest.TestLoader().loadTestsFromTestCase(TestConfiguracionSinCambios)
    suite_dirty_general_inicial = unittest.TestLoader().loadTestsFromTestCase(TestGeneralCargaInicial)
    suite_fm_filtrar = unittest.TestLoader().loadTestsFromTestCase(TestFiltrarFacturacionManual)
    suite_fm_obtener_empresas = unittest.TestLoader().loadTestsFromTestCase(TestObtenerEmpresas)
    suite_fm_obtener_unidades_empresa = unittest.TestLoader().loadTestsFromTestCase(TestObtenerUnidadesEmpresa)
    suite_fm_seleccionar_columnas_detalle = unittest.TestLoader().loadTestsFromTestCase(TestSeleccionarColumnasDetalle)
    suite_fm_construir_contexto_empresa = unittest.TestLoader().loadTestsFromTestCase(TestConstruirContextoEmpresa)
    suite_fm_construir_plantilla_base = unittest.TestLoader().loadTestsFromTestCase(TestConstruirPlantillaBase)
    suite_fm_generar_plantilla_base = unittest.TestLoader().loadTestsFromTestCase(TestGenerarPlantillaBase)

    bateria_completa = unittest.TestSuite([
        suite_comercial, suite_comercial_filtros_header, suite_comercial_tabs, suite_comercial_revision_cm, suite_confirmar_baja_cm,
        suite_save_excel_thread_logs_signal, suite_set_logs_df_integracion_general,
        suite_enviar_correo_cm, suite_enviar_correo_otras_subpestanas,
        suite_editar_unidad_comercial, suite_agregar_contacto_comercial,
        suite_dialogo_accion_cm, suite_confirmar_baja_cm_flujo_real,
        suite_regla_sin_contrato,
        suite_regla_terminated_cm, suite_reconciliacion_expired_comercial, suite_rm_javi_normaliza_estado_comercial,
        suite_contratos_no_limpia_vin_ausente, suite_contratos_regla_terminated_cm,
        suite_contratos_reconciliacion_expired_guardar, suite_contratos_reconciliacion_expired_importar,
        suite_contratos_edicion_manual_flujo_real, suite_contratos_importacion_masiva_flujo_real,
        suite_cm_bajas_tiene_datos, suite_cm_bajas_detectar, suite_cm_bajas_actualizar,
        suite_cm_bajas_persistencia, suite_cm_bajas_integracion,
        suite_cm_expired_detectar, suite_cm_expired_reconciliar, suite_cm_ausencia_no_toca_expired,
        suite_cm_expired_integracion, suite_cm_origen_caso_compatibilidad,
        suite_cm_confirmar_baja_caso, suite_cm_confirmar_baja_integracion,
        suite_cm_confirmar_baja_casos, suite_cm_confirmar_baja_multiple_integracion,
        suite_clasificar_vigencia_calendario, suite_filtrar_renovaciones, suite_filtrar_vencimientos, suite_filtrar_gestionar_bajas,
        suite_filtrar_por_gestionar, suite_construir_mascara_busqueda, suite_formatear_dias_restantes,
        suite_parsear_dias_restantes, suite_etapa_gestion_vectorizado_equivale,
        suite_provisiones, suite_contactos, suite_excel_writer, suite_update_cells_confirmar_baja_cm, suite_main_window,
        suite_trigger_load_data_dirty, suite_sidebar_toggle, suite_multi_search_limite, suite_global_search_debounce,
        suite_theme_manager_icon_cache,
        suite_revision_cm_al_cargar,
        suite_main_window_lock_banner,
        suite_dirty_comercial, suite_dirty_otros_modulos, suite_dirty_historial, suite_dirty_tabs,
        suite_dirty_configuracion, suite_dirty_general_inicial,
        suite_fm_filtrar, suite_fm_obtener_empresas, suite_fm_obtener_unidades_empresa,
        suite_fm_seleccionar_columnas_detalle, suite_fm_construir_contexto_empresa,
        suite_fm_construir_plantilla_base, suite_fm_generar_plantilla_base,
        suite_backups, suite_punto_c, suite_log_deleted, suite_log_deleted_por_modulo, suite_restore_backup,
        suite_backup_manager_snapshot, suite_backup_manager_retencion,
        suite_rm_javi_historial, suite_rm_javi_columnas_autorizadas, suite_configuracion_historial,
        suite_configuracion_casos_baja_cm_path, suite_normalizacion_config,
        suite_clear_logs_bloqueado, suite_papelera_por_modulo, suite_vaciar_papelera_backup,
        suite_vaciar_logs_modificaciones_backup,
        suite_mail_registro, suite_outlook_registro,
        suite_agrupar_destinatarios, suite_validar_destinatarios, suite_config_plantilla,
        suite_sin_correo_hardcodeado, suite_sin_modo_prueba,
        suite_cruzar_correos_maestro, suite_guardar_correos_excel, suite_vins_faltantes_en_correos,
        suite_actualizar_correo_por_cdb, suite_mail_dialog_celda_correo, suite_contactos_add_prefill,
        suite_mail_dialog_preseleccion,
        suite_procesar_df_comercial, suite_kpis_vigencia, suite_validar_valor_pegado,
        suite_quitar_vin, suite_contratos_por_id, suite_form_contratos_por_id,
        suite_agregar_fila, suite_aplicar_cambios_pendientes,
        suite_validar_duracion, suite_validar_fecha_ddmmyyyy,
        suite_parsear_pago_cm, suite_formatear_pago_cm, suite_aplica_regla_sin_contrato,
        suite_excluir_contratos_cerrados, suite_obtener_modelo_desde_vin,
        suite_comercial_agregar_auto_modelo, suite_comercial_agregar_gestion_unidades,
        suite_comercial_agregar_modo_lote, suite_comercial_agregar_precarga_legados,
        suite_calcular_termino_contrato, suite_baja_no_limpia_al_cargar,
        suite_normaliza_estado_del_cm,
        suite_formatear_columna_fecha_legado_base, suite_formatear_columna_fecha_legado_completa,
        suite_main_data_loader_lectura_excel,
        suite_build_unidades_df, suite_filtrar_contactos_por_cdb,
        suite_construir_mapa_director_empresa_pbi, suite_powerbi_director_empresa_loader_thread,
        suite_aplicar_filtros_unidades, suite_estado_activacion_colores,
        suite_resolver_texto_flota_vc_sin_cliente, suite_populate_contact_cards,
        suite_aplicar_busqueda_unidades, suite_buscador_global_tres_pestanas,
        suite_clientes_unidades_columnas_visibles,
        suite_filtrar_historial_por_vin, suite_valor_ficha, suite_seleccion_vin_unidades,
        suite_agregar_contacto_cliente,
        suite_detalle_cliente_sin_historial,
        suite_general_data_prep_thread, suite_general_data_prep_equivale, suite_general_load_data_reentrancia, suite_contratos_anteriores_unidades,
        suite_general_render_diferido_pestanas,
        suite_table_sorting, suite_menu_eliminados, suite_instalaciones_menu,
        suite_header_data_fuera_de_rango, suite_set_table_id_descarta_estado, suite_termino_contrato_foreground,
        suite_formatear_moneda, suite_validar_cantidad_meses, suite_parsear_dynafleet,
        suite_calcular_montos_provision, suite_limpiar_cantidad_meses_display,
        suite_construir_cambios_provisiones, suite_convertir_periodo_interno, suite_parsear_numero_uf,
        suite_mapear_industria, suite_normalizar_cliente, suite_construir_lookup_razon_social,
        suite_buscar_candidatos_por_cliente, suite_mapear_tipo_servicio_desde_plan,
        suite_normalizar_id_contacto, suite_favoritos, suite_migrar_favoritos_legacy,
        suite_generar_nuevo_id_contacto, suite_formatear_telefono_chile,
        suite_aplicar_cambios_pendientes_contactos, suite_aplicar_filtro_checkbox,
        suite_buscar_texto_global, suite_ordenar_por_favoritos_e_id,
        suite_filtrar_activaciones, suite_filtrar_bajas, suite_armar_export_contactos_ejecutivo,
        suite_calcular_cambios_marcar_desconectado, suite_ciclo_baja_operaciones_comercial,
        suite_operaciones_por_contrato,
        suite_quality_sync_normal, suite_quality_sync_idempotencia, suite_quality_sync_nuevo_test,
        suite_quality_sync_metodo_nuevo, suite_quality_sync_alfabetico, suite_quality_sync_fail,
        suite_quality_sync_error_conocido, suite_quality_sync_error_desconocido,
        suite_quality_sync_error_escritura, suite_quality_sync_skip,
        suite_file_lock_monitor_disponible, suite_file_lock_monitor_confirmacion,
        suite_file_lock_monitor_cuatro_archivos, suite_file_lock_monitor_guardado_propio,
        suite_app_lock_todos_disponibles, suite_app_lock_un_archivo_ocupado,
        suite_app_lock_dos_archivos_ocupados, suite_app_lock_vuelta_normal,
        suite_app_lock_transitorio, suite_app_lock_guardado_propio, suite_app_lock_senal_estado,
        suite_app_lock_archivos_ocupados_cambiado,
    ])
    
    class _ResultadoConLimpieza(unittest.TextTestResult):
        """Tras cada test fuerza la recolección de basura y procesa los eventos
        pendientes: así los widgets Qt de tests anteriores se destruyen aquí y
        no en un momento al azar (por ejemplo, mientras otra clase carga datos
        en segundo plano), lo que cerraba el proceso con una violación de acceso."""

        def stopTest(self, test):
            super().stopTest(test)
            gc.collect()
            app.processEvents()

    runner = unittest.TextTestRunner(stream=open(os.devnull, 'w'), verbosity=2, resultclass=_ResultadoConLimpieza)
    logger.info(f"Ejecutando {bateria_completa.countTestCases()} pruebas automáticas en cadena...")
    result = runner.run(bateria_completa)

    logger.info("=== RESULTADOS DE LAS PRUEBAS ===")
    if result.wasSuccessful():
        logger.info("✅ TODAS LAS PRUEBAS PASARON CORRECTAMENTE.")
    else:
        logger.error(f"❌ FALLARON {len(result.failures) + len(result.errors)} PRUEBAS.")
        # AQUÍ RECUPERAMOS EL REPORTE DE ERRORES:
        for test, traceback in result.failures + result.errors:
            logger.error(f"Fallo en: {test.id()}\nDetalle: {traceback}")

    logger.info("Fin de la ejecución global.")
    teardown_sandbox()

    # Salida inmediata con el resultado real: al cerrar el intérprete, Qt destruía
    # objetos en un orden inseguro y el proceso terminaba con una violación de
    # acceso (código de error) aunque todas las pruebas hubieran pasado.
    import faulthandler
    faulthandler.disable()
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)