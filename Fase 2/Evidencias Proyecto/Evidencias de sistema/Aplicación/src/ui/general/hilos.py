"""Hilos de General: carga de directores de empresa (Power BI) y preparación pesada de clientes y unidades."""
import os
from PyQt6.QtCore import QThread, pyqtSignal
from src.services import comercial_services, powerbi_cache_service
from config.settings import POWERBI_EXCEL_PATH
from src.services import general_services
from src.ui.general.constantes import (
    logger,
)


class PowerBiDirectorEmpresaLoaderThread(QThread):
    """Lee CDB + Correo electrónico + Teléfono + Dirección + Comuna desde BBDD CLIENTES CM.xlsx
    (Power BI, config.settings.POWERBI_EXCEL_PATH) en un hilo secundario
    para no bloquear la UI -- mismo patrón que PowerBiFlotasLoaderThread
    (contactos_agregar.py) y PowerBiSyncWorker (contactos.py), que ya
    expone esta misma fuente bajo la pestaña "Director de empresas (Power
    BI)" de ContactosModule. Solo lectura: nunca escribe en ese Excel. Si
    el archivo no está configurado, no existe o no tiene ninguna de las
    columnas esperadas, emite un mapa vacío en vez de fallar.

    Usa powerbi_cache_service (cache CSV en data/cache/, auditoria de
    rendimiento 23-09-2026) en vez de leer el .xlsx directamente: baja de
    ~11s a ~0.5s por lectura una vez generado el cache."""
    data_loaded_signal = pyqtSignal(dict)

    def __init__(self, ruta_excel):
        super().__init__()
        self.ruta_excel = ruta_excel

    def run(self):
        # Siempre emite: el aviso "Cargando directores" depende de esta señal
        try:
            df_pbi = powerbi_cache_service.leer_bbdd_clientes_cm(
                self.ruta_excel, columnas=['CDB', 'Correo electrónico', 'Teléfono', 'Dirección', 'Comuna'])
            mapa = general_services.construir_mapa_director_empresa_pbi(df_pbi)
        except Exception as e:
            logger.warning(f"No se pudo leer BBDD CLIENTES CM para el director de empresa: {e}")
            mapa = {}
        self.data_loaded_signal.emit(mapa)


# Precarga del mapa "Director de empresa" durante la pantalla de carga inicial
# (ver precargar_director_empresa_pbi y GeneralModule._load_pbi_director_empresa_async)
_precarga_director_pbi = {'hilo': None, 'mapa': None, 'diferida': False, 'esperando': []}


def diferir_director_empresa_pbi():
    """Hasta que se llame a `precargar_director_empresa_pbi`, ningún módulo lee
    BBDD CLIENTES CM: se anotan y reciben el mapa cuando llega."""
    _precarga_director_pbi['diferida'] = True


def precargar_director_empresa_pbi():
    """Lanza la lectura de BBDD CLIENTES CM con la app ya abierta y las demás
    pantallas armadas: si el espejo CSV está viejo, regenerarlo (~11-17 s)
    compite por el GIL con la animación de carga."""
    _precarga_director_pbi['diferida'] = False
    esperando, _precarga_director_pbi['esperando'] = _precarga_director_pbi['esperando'], []
    if _precarga_director_pbi['hilo'] is not None:
        return
    if not POWERBI_EXCEL_PATH or not os.path.exists(POWERBI_EXCEL_PATH):
        return
    hilo = PowerBiDirectorEmpresaLoaderThread(POWERBI_EXCEL_PATH)
    hilo.data_loaded_signal.connect(lambda mapa: _precarga_director_pbi.__setitem__('mapa', mapa))
    for modulo in esperando:
        hilo.data_loaded_signal.connect(modulo._on_pbi_director_empresa_loaded)
    _precarga_director_pbi['hilo'] = hilo
    hilo.start()


class GeneralDataPrepThread(QThread):
    """Pipeline pesado de GeneralModule.load_data() (procesar_df_comercial +
    los 3 _build_*_df + las listas de filtro derivadas de los datos) movido
    a un hilo secundario para no bloquear la UI (auditoria de rendimiento,
    fase 4, 21-09-2026) -- mismo patron que PowerBiDirectorEmpresaLoaderThread
    de mas arriba: recibe en el constructor un snapshot ya independiente
    (DataManager.get_comercial_df() ya hace .copy()), nunca toca self ni
    ningun widget, y al terminar emite el resultado por señal para que el
    hilo principal lo aplique (guardar los DataFrames, poblar listas de
    filtro con QListWidget, y construir las tarjetas via filter_clientes/
    filter_unidades -- todo eso requiere afinidad con el hilo
    de UI y se queda en GeneralModule._on_prep_finished).

    _build_clientes_df/_build_unidades_df son @staticmethod
    de GeneralModule (no usan self): se llaman aqui via la clase, nunca via
    una instancia de GeneralModule, para que este hilo jamas quede con una
    referencia a un QWidget."""
    data_prepared_signal = pyqtSignal(object)

    def __init__(self, snapshot_df_comercial):
        super().__init__()
        self.snapshot_df_comercial = snapshot_df_comercial
        self.extras = None

    def run(self):
        df_comercial = comercial_services.contratos_actuales(
            comercial_services.procesar_df_comercial(self.snapshot_df_comercial))
        df_clientes = general_services.build_clientes_df(df_comercial)
        df_unidades = general_services.build_unidades_df(df_comercial)
        # Lo demás que antes se calculaba en el hilo de la interfaz; si falla, la pantalla lo calcula como antes
        try:
            self.extras = (df_comercial, general_services.preparar_extras_general(df_comercial))
        except Exception:
            self.extras = None

        self.data_prepared_signal.emit((df_comercial, df_clientes, df_unidades))
