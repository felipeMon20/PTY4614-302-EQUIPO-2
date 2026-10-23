import hashlib
import os
import pickle
import threading
import time
import uuid
import urllib3
import psutil
import warnings
import shutil
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
import config.settings
from src.core.cdb_columnas import cdb_a_memoria, asegurar_cdb_flota
from src.core.dataframe_formatter import DataFrameFormatter, aplicar_por_fila_memoizado
from src.core.constants import *
from src.core.hilos import iniciar_hilo_retenido

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
# El filtro anterior no atrapa este warning: pandas lo emite con stacklevel apuntando
# al código llamante (este módulo), no a "pandas", así que hay que filtrarlo por mensaje.
warnings.filterwarnings("ignore", message="Parsing dates in .* format when dayfirst=True was specified", category=UserWarning)

# =========================================================
# FORMATEO DE FECHAS "LEGADO" (columnas INICIO/TERMINO/ESTADO DE ENTREGA/
# PERIODO INTERNO de PruebasFM, ver MainDataLoaderThread.run() mas abajo).
# Extraido a nivel de modulo (antes vivia como funcion anidada dentro de
# run()) para poder testearlo de forma aislada -- sin cambios de logica.
# =========================================================
COLUMNAS_FECHA_LEGADO = ['INICIO', 'TERMINO', 'ESTADO DE ENTREGA', 'PERIODO INTERNO']

# Tiempo máximo que se reutiliza una lectura hecha por el watchdog (ver
# DataManager.guardar_precarga_principal); además se exige mismo mtime.
VIGENCIA_PRECARGA_SEGUNDOS = 300


FILAS_POR_TRAMO_STRFTIME = 2000


def _strftime_por_tramos(fechas, formato):
    """Mismo resultado que fechas.dt.strftime(formato). strftime es una sola
    llamada en C que retiene el GIL (~80 ms con 12.000 filas) y congela la
    animación del hilo de la interfaz; por tramos la retiene ~10 ms cada vez."""
    if len(fechas) <= FILAS_POR_TRAMO_STRFTIME:
        return fechas.dt.strftime(formato)
    return pd.concat([fechas.iloc[i:i + FILAS_POR_TRAMO_STRFTIME].dt.strftime(formato)
                      for i in range(0, len(fechas), FILAS_POR_TRAMO_STRFTIME)])


def formatear_columna_fecha_legado(serie):
    """Formatea de una vez toda la columna (vectorizado, ver auditoria de
    rendimiento Fase 2.1/2.2: ~25x mas rapido que el .apply() celda por
    celda anterior; benchmark sobre datos reales, 0 diferencias en 12.172
    filas x 4 columnas). Mismos casos especiales que la version anterior,
    en el mismo orden de prioridad: vacio/NaN/"nan" literal -> "", "MENSUAL"
    (case-insensitive) -> "MENSUAL", fecha parseable (dayfirst=True, solo el
    primer token separado por espacio) -> "dd-mm-yyyy", cualquier otra cosa
    (incluye texto que no es fecha, ej. "agosto - 2022" de PERIODO INTERNO)
    -> se devuelve tal cual. Incluye a proposito el bug conocido de
    pd.to_datetime(dayfirst=True) con fechas ISO ambiguas (dia/mes <=12
    intercambiados -- mismo bug ya documentado en dataframe_formatter.py
    para calcular_termino) y el caso limite donde " NaN " con espacios NO se
    trata como vacio (a diferencia de "NaN" exacto), porque la comparacion
    usa el string sin recortar (str_s, no texto) -- ver
    test_data_manager.py para el detalle de cada caso."""
    str_s = serie.astype(str)
    texto = str_s.str.strip()
    upper = texto.str.upper()

    mask_na = serie.isna()
    mask_vacio = (texto == "")
    mask_nan_lit = (str_s.str.lower() == "nan")
    mask_mensual = (upper == "MENSUAL")
    mask_vacio_total = mask_na | mask_vacio | mask_nan_lit

    resultado = texto.copy()
    resultado[mask_vacio_total] = ""
    resultado[mask_mensual] = "MENSUAL"

    mask_intentar_fecha = ~(mask_vacio_total | mask_mensual)
    primer_token = texto[mask_intentar_fecha].str.split().str[0]

    fechas = pd.to_datetime(primer_token, dayfirst=True, format='mixed', errors='coerce')
    formateadas = _strftime_por_tramos(fechas, '%d-%m-%Y')

    # Donde el parseo vectorizado fallo (NaT), se conserva el texto original
    # -- mismo comportamiento que el except Exception: return texto del
    # safe_date_format original.
    idx_fallo = formateadas[formateadas.isna()].index
    formateadas.loc[idx_fallo] = texto.loc[idx_fallo]

    resultado.loc[mask_intentar_fecha] = formateadas
    return resultado


# =========================================================
# MOTOR 1: DEDICADO SOLO AL EXCEL PRINCIPAL (Ultra Rápido)
# =========================================================
class MainDataLoaderThread(QThread):
    data_loaded_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        if not os.path.exists(self.filepath):
            self.error_signal.emit("El archivo Excel no existe en la ruta configurada.")
            return

        try:
            self.data_loaded_signal.emit(leer_datos_principales(self.filepath))
        except Exception as e:
            self.error_signal.emit(str(e))


def leer_datos_principales(filepath):
    """Pipeline completo de lectura del archivo principal (antes vivía dentro
    de MainDataLoaderThread.run()). Lo reutiliza también el hilo de
    comparación del watchdog (main_window.CompareSnapshotThread) para leer y
    limpiar una sola vez. Devuelve (df, df_logs, df_deleted, load_time,
    deleted_sheets); propaga cualquier excepción al llamador."""
    start_time = time.time()

    # Mismo patron que ContactosLoaderThread mas abajo (unico lugar
    # que ya resolvia este problema): si el Excel principal esta
    # abierto en el PC del usuario, pd.read_excel puede lanzar
    # PermissionError (WinError 13) directo, sin pasar por el
    # ValueError de sheet_name. Antes esto tumbaba toda la carga
    # inicial (error_signal con "[Errno 13] Permission denied...")
    # y obligaba a cerrar Excel y reabrir la app. Ahora se copia el
    # archivo a un temporal (una copia normalmente se puede leer
    # aunque el original este abierto en Excel) y se reintenta unas
    # pocas veces antes de rendirse.
    # Fase 2 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): el
    # formato de origen se decide por extension de filepath.
    # CSV no tiene concepto de hoja (sheet_name), asi que ese
    # fallback no aplica; el resto del metodo (clean(), columnas
    # legado, logs, deleted_sheets) es identico para ambos formatos.
    es_csv = filepath.lower().endswith('.csv')
    extension_temp = '.csv' if es_csv else '.xlsx'

    temp_dir = os.path.join(os.getcwd(), 'data', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    # Nombre único: el watchdog y una recarga manual pueden leer a la vez.
    temp_main_path = os.path.join(temp_dir, f'ghost_main_{uuid.uuid4().hex}{extension_temp}')

    ruta_lectura = filepath
    intentos_maximos = 5
    for intento in range(intentos_maximos):
        try:
            shutil.copy2(filepath, temp_main_path)
            ruta_lectura = temp_main_path
            break
        except PermissionError:
            if intento < intentos_maximos - 1:
                time.sleep(1)

    try:
        for intento in range(intentos_maximos):
            try:
                if es_csv:
                    # dtype=str + keep_default_na=False: mismo criterio
                    # ya validado (Fase 0) para que '' no se convierta en
                    # NaN ni se pierdan ceros/guiones antes de clean().
                    df = pd.read_csv(ruta_lectura, dtype=str, keep_default_na=False)
                else:
                    try:
                        df = pd.read_excel(ruta_lectura, sheet_name='BBDD (2)')
                    except ValueError:
                        df = pd.read_excel(ruta_lectura)
                break
            except PermissionError:
                if intento == intentos_maximos - 1:
                    raise
                time.sleep(1)
    finally:
        if ruta_lectura == temp_main_path:
            try: os.remove(temp_main_path)
            except Exception: pass

    df = asegurar_cdb_flota(cdb_a_memoria(df))
    # clean() recalcula TÉRMINO CONTRATO: las diferencias con INICIO + DURACIÓN
    # se detectan antes y viajan en df.attrs para el botón de Comercial.
    from src.services.comercial_services import detectar_termino_distinto_de_duracion
    termino_distinto = detectar_termino_distinto_de_duracion(df)
    df = DataFrameFormatter.clean(df)

    for col in COLUMNAS_FECHA_LEGADO:
        if col in df.columns:
            df[col] = formatear_columna_fecha_legado(df[col])

    # LogApp.csv (config.settings.LOG_CSV_PATH) es el unico historial
    # oficial; ya no depende de LOG_EXCEL_PATH salvo para la migracion
    # unica desde el .xlsx legado (ver excel_writer.migrar_historial_legacy).
    df_logs = pd.DataFrame()
    try:
        from src.core.excel_writer import migrar_historial_legacy
        migrar_historial_legacy(config.settings.LOG_EXCEL_PATH, config.settings.LOG_CSV_PATH)
        if config.settings.LOG_CSV_PATH and os.path.exists(config.settings.LOG_CSV_PATH):
            df_logs = pd.read_csv(config.settings.LOG_CSV_PATH, dtype=str, keep_default_na=False)
    except Exception as e:
        pass

    # df_deleted (legado, se conserva tal cual para no romper nada que
    # ya dependa de el): solo la PRIMERA hoja de RegistroEliminado.xlsx,
    # que es el comportamiento historico de pd.read_excel sin sheet_name.
    df_deleted = pd.DataFrame()
    # deleted_sheets (nuevo): TODAS las hojas de RegistroEliminado.xlsx,
    # una por modulo de origen (Comercial, Contactos, etc.), cada una
    # con su propio esquema de columnas intacto. RegistroEliminado.xlsx
    # ya guarda una hoja por module_name (ver ExcelWriter._log_deleted);
    # antes esta lectura solo tomaba la primera hoja del archivo
    # (comportamiento por defecto de pd.read_excel sin sheet_name),
    # dejando invisibles en la app las eliminaciones de cualquier otro
    # modulo. deleted_sheets es la fuente que usa HistorialModule.
    deleted_sheets = {}
    if os.path.exists(config.settings.DELETED_LOG_EXCEL_PATH):
        # Una sola lectura del libro (antes se abría dos veces): la
        # primera hoja es df_deleted, con el mismo procesamiento.
        try:
            hojas = pd.read_excel(config.settings.DELETED_LOG_EXCEL_PATH, sheet_name=None)
            for nombre_hoja, df_hoja in hojas.items():
                df_hoja = df_hoja.fillna("")
                for col in df_hoja.select_dtypes(include=['datetime64']).columns:
                    df_hoja[col] = df_hoja[col].dt.strftime('%m/%d/%Y')
                deleted_sheets[nombre_hoja] = df_hoja
            if deleted_sheets:
                df_deleted = next(iter(deleted_sheets.values())).copy()
        except Exception as e:
            pass

    load_time = round(time.time() - start_time, 2)
    df.attrs['termino_distinto_de_duracion'] = termino_distinto
    return (df, df_logs, df_deleted, load_time, deleted_sheets)

# =========================================================
# MOTOR 2: DEDICADO SOLO A PROVISIONES
# =========================================================
# Copia rápida del resultado (20-10-2026): leer provisionFelipe.xlsx con
# openpyxl toma ~1 s en el hilo de fondo compitiendo por el GIL con la
# interfaz. Solo se usa si el Excel tiene la misma fecha de modificación y
# tamaño que cuando se guardó la copia; cualquier escritura la invalida.
_DIR_CACHE = os.path.join(os.getcwd(), 'data', 'cache')
_VERSION_CACHE_PROVISIONES = 1


def _ruta_cache_provisiones(ruta):
    # Una por ruta de origen: los tests apuntan a otro Excel y no deben pisarse
    hash_ruta = hashlib.sha1(os.path.abspath(ruta).encode('utf-8')).hexdigest()[:16]
    return os.path.join(_DIR_CACHE, f'provisiones_{hash_ruta}.pkl')


def _firma_archivo(ruta):
    estado = os.stat(ruta)
    return (estado.st_mtime_ns, estado.st_size)


def _leer_cache_provisiones(ruta, firma):
    try:
        with open(_ruta_cache_provisiones(ruta), 'rb') as archivo:
            guardado = pickle.load(archivo)
        if guardado.get('version') == _VERSION_CACHE_PROVISIONES and guardado.get('firma') == firma:
            return guardado['datos']
    except Exception:
        pass
    return None


def _guardar_cache_provisiones(ruta, firma, datos):
    """Escritura atómica; deja solo la copia de esta ruta (las de otras
    rutas, como las de los tests, se borran)."""
    destino = _ruta_cache_provisiones(ruta)
    temporal = f"{destino}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(_DIR_CACHE, exist_ok=True)
        with open(temporal, 'wb') as archivo:
            pickle.dump({'version': _VERSION_CACHE_PROVISIONES, 'firma': firma, 'datos': datos},
                        archivo, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporal, destino)
    except Exception:
        try:
            os.remove(temporal)
        except OSError:
            pass
        return
    try:
        for nombre in os.listdir(_DIR_CACHE):
            ruta_otro = os.path.join(_DIR_CACHE, nombre)
            if nombre.startswith('provisiones_') and nombre.endswith('.pkl') and ruta_otro != destino:
                os.remove(ruta_otro)
    except OSError:
        pass


class ProvisionesLoaderThread(QThread):
    data_loaded_signal = pyqtSignal(object) 
    error_signal = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        if not os.path.exists(self.filepath):
            self.error_signal.emit("El archivo de provisiones no existe.")
            return

        try:
            # La firma se toma antes de leer: si el archivo cambia a mitad de
            # la lectura, la copia queda con la firma vieja y no se reutiliza
            firma = _firma_archivo(self.filepath)
            datos = _leer_cache_provisiones(self.filepath, firma)
            if datos is not None:
                self.data_loaded_signal.emit(datos)
                return

            df_prov = pd.DataFrame()
            lista_planes = []
            valor_uf = 0
            valor_civ = 0

            try:
                # Un solo ExcelFile para las 3 hojas: antes cada read_excel
                # volvía a abrir y parsear el libro completo.
                with pd.ExcelFile(self.filepath) as xls:
                    df_vars = xls.parse("Variables")
                    df_planes = xls.parse("Planes")
                    df_prov_raw = xls.parse("Prov")

                for _, row in df_vars.iterrows():
                    var_name = str(row.iloc[0]).strip().upper()
                    if var_name == "UF": valor_uf = row.iloc[1] if pd.notna(row.iloc[1]) else 0
                    elif var_name == "CIV": valor_civ = row.iloc[1] if pd.notna(row.iloc[1]) else 0

                dict_mult = {}
                
                for idx, row in df_planes.iterrows():
                    p_nombre = str(row.iloc[0]).strip()
                    if p_nombre and p_nombre.lower() not in ["nan", ""]:
                        try: mult = float(row.iloc[1])
                        except Exception: mult = 0.0
                        if pd.isna(mult): mult = 0.0
                        dict_mult[p_nombre] = mult

                for p_nombre in dict_mult.keys():
                    if "+ CIV" in p_nombre.upper() and dict_mult[p_nombre] == 0.0:
                        base_name = p_nombre.upper().replace("+ CIV", "").strip()
                        base_val = next((v for k, v in dict_mult.items() if k.upper() == base_name), 0.0)
                        dict_mult[p_nombre] = base_val + valor_civ
                
                dict_exact_clp = {} 
                for p_nombre, mult in dict_mult.items():
                    exact_val = mult * valor_uf
                    p_clp = round(exact_val)
                    lista_planes.append({'nombre': p_nombre, 'uf_mult': mult, 'clp': p_clp})
                    dict_exact_clp[p_nombre] = exact_val 

                if 'AÑO - MES' in df_prov_raw.columns:
                    df_prov_raw['AÑO - MES'] = df_prov_raw['AÑO - MES'].astype(str).str.strip()
                
                if not df_prov_raw.empty:
                    df_prov_raw['DYNAFLEET'] = pd.to_numeric(df_prov_raw['DYNAFLEET'], errors='coerce').fillna(0)
                    df_prov_raw['Cantidad de Meses'] = pd.to_numeric(df_prov_raw['Cantidad de Meses'], errors='coerce').fillna(1)
                    
                    def get_float_safe(val):
                        if pd.isna(val) or str(val).strip() == '': return None
                        try: return float(val)
                        except Exception: return None
                        
                    def get_monto(row):
                        val = get_float_safe(row.get('Monto Provisionado'))
                        if val is not None: return val
                        return row['DYNAFLEET'] / row['Cantidad de Meses'] if row['Cantidad de Meses'] > 0 else 0.0
                        
                    def get_valor_plan(row):
                        val = get_float_safe(row.get('Valor Plan'))
                        if val is not None: return val
                        return dict_exact_clp.get(str(row.get('Plan')).strip(), 0.0)
                        
                    def get_var(row):
                        val = get_float_safe(row.get('VAR'))
                        if val is not None: return val
                        try: return get_monto(row) - get_valor_plan(row)
                        except Exception: return 0.0

                    # Mismo orden que antes: get_var lee Monto/Valor Plan ya recalculados.
                    cols_monto = ['Monto Provisionado', 'DYNAFLEET', 'Cantidad de Meses']
                    cols_plan = ['Valor Plan', 'Plan']
                    df_prov_raw['Monto Provisionado'] = aplicar_por_fila_memoizado(df_prov_raw, get_monto, cols_monto)
                    df_prov_raw['Valor Plan'] = aplicar_por_fila_memoizado(df_prov_raw, get_valor_plan, cols_plan)
                    df_prov_raw['VAR'] = aplicar_por_fila_memoizado(df_prov_raw, get_var, ['VAR'] + cols_monto + cols_plan)

                df_prov = df_prov_raw.fillna("")

            except Exception as e:
                self.error_signal.emit(f"Error procesando provisiones: {str(e)}")
                return

            datos = (df_prov, lista_planes, valor_uf, valor_civ)
            _guardar_cache_provisiones(self.filepath, firma, datos)
            self.data_loaded_signal.emit(datos)
            
        except Exception as e:
            self.error_signal.emit(str(e))

# =========================================================
# MOTOR 3: DEDICADO A CONTACTOS
# =========================================================
class ContactosLoaderThread(QThread):
    data_loaded_signal = pyqtSignal(object) 
    error_signal = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        if not os.path.exists(self.filepath):
            self.error_signal.emit("El archivo de Contactos no existe o no ha sido sincronizado.")
            return

        temp_dir = os.path.join(os.getcwd(), 'data', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_contactos_path = os.path.join(temp_dir, 'ghost_contactos.xlsx')

        try:
            ruta_lectura = self.filepath
            
            intentos_maximos = 5
            for intento in range(intentos_maximos):
                try:
                    shutil.copy2(self.filepath, temp_contactos_path)
                    ruta_lectura = temp_contactos_path
                    break 
                except PermissionError:
                    if intento == intentos_maximos - 1: pass
                    time.sleep(1) 
            
            for intento in range(intentos_maximos):
                try:
                    df = pd.read_excel(ruta_lectura, sheet_name=0)
                    break
                except PermissionError:
                    if intento == intentos_maximos - 1: raise 
                    time.sleep(1)

            df = df.fillna("")
            
            # --- VALIDACIÓN ESTRICTA DE LA IDENTIDAD FÍSICA ---
            if 'ID' not in df.columns:
                self.error_signal.emit("ERROR FATAL: El archivo de Contactos no contiene la columna 'ID' requerida para identificar los registros.")
                return

            if df['ID'].isna().any() or (df['ID'].astype(str).str.strip() == "").any():
                self.error_signal.emit("ERROR FATAL: Existen contactos en la base de datos sin un ID asignado (valores nulos o vacíos).")
                return

            try:
                # Forzamos la limpieza a número entero y luego a string limpio (ej. "458" sin ".0")
                df['ID'] = pd.to_numeric(df['ID']).astype(int).astype(str)
            except ValueError:
                self.error_signal.emit("ERROR FATAL: La columna 'ID' en Contactos contiene valores que no son números enteros.")
                return

            if df['ID'].duplicated().any():
                dups = df[df['ID'].duplicated()]['ID'].unique().tolist()
                self.error_signal.emit(f"ERROR FATAL: Corrupción de Identidad. Existen IDs duplicados en el Excel de Contactos: {dups}")
                return
            
            if 'CDB' in df.columns: 
                df['CDB'] = df['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            if 'Teléfono' in df.columns: 
                df['Teléfono'] = df['Teléfono'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                
            if ruta_lectura == temp_contactos_path:
                try: os.remove(temp_contactos_path)
                except: pass

            self.data_loaded_signal.emit(df)
            
        except Exception as e:
            self.error_signal.emit(f"Error procesando contactos: {str(e)}")


class DataManager(QObject):
    _instance = None
    _qobject_initialized = False
    
    data_ready = pyqtSignal()
    load_error = pyqtSignal(str)

    # Senal ligera especifica para "el historial en RAM cambio": a
    # diferencia de data_ready (que dispara recargas pesadas de tablas en
    # varios modulos y puede cambiar la pestana visible), esta solo debe
    # hacer que Historial se refresque con lo que ya hay en self.df_logs.
    logs_updated = pyqtSignal()

    # Se registró un correo en Historial_Envios_VC.csv (alimenta los KPI de
    # "Clientes contactados" de Comercial).
    correos_registrados = pyqtSignal()

    provisiones_ready = pyqtSignal()
    load_provisiones_error = pyqtSignal(str)

    contactos_ready = pyqtSignal()
    load_contactos_error = pyqtSignal(str)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if DataManager._qobject_initialized:
            return

        super().__init__()

        self.df_master = pd.DataFrame()
        self.termino_distinto_de_duracion = {}
        self.df_logs = pd.DataFrame()
        self.df_deleted = pd.DataFrame()
        # deleted_sheets: {nombre_modulo: DataFrame} — una entrada por hoja de
        # RegistroEliminado.xlsx, cada una con el esquema propio de su origen.
        # Ver MainDataLoaderThread.run() y HistorialModule (pestaña Papelera).
        self.deleted_sheets = {}
        self.df_prov = pd.DataFrame()
        self.df_contactos = pd.DataFrame()
        self.lista_planes = []
        self.valor_uf = 0
        self.valor_civ = 0
        self.last_load_time = 0.0
        self.is_loading_main = False
        self.is_loading_prov = False
        self.is_loading_contactos = False
        self.is_app_saving = False
        self.save_timestamp = 0.0
        self._contactos_reload_pending = False
        self._main_reload_pending = False
        self._prov_reload_pending = False
        self._precarga_principal = None
        self.last_contactos_error = ""
        DataManager._qobject_initialized = True

    def load_data_async(self):
        # Si ya hay una carga en curso no se lanza un segundo hilo ni se emite
        # data_ready con datos viejos: se relanza al terminar la actual.
        if self.is_loading_main:
            self._main_reload_pending = True
            return
        self.is_loading_main = True
        self._main_reload_pending = False

        # Si el watchdog ya leyó y limpió el archivo y no cambió desde
        # entonces, se reutiliza esa lectura (asíncrono igual que un hilo).
        precarga = self._tomar_precarga_principal(config.settings.EXCEL_PATH)
        if precarga is not None:
            QTimer.singleShot(0, lambda: self._on_main_data_loaded(precarga))
            return

        self.thread_main = MainDataLoaderThread(config.settings.EXCEL_PATH)
        self.thread_main.data_loaded_signal.connect(self._on_main_data_loaded)
        self.thread_main.error_signal.connect(self._on_main_load_error)
        self._iniciar_hilo_retenido(self.thread_main)

    @staticmethod
    def _iniciar_hilo_retenido(hilo):
        iniciar_hilo_retenido(hilo)

    def guardar_precarga_principal(self, payload, ruta, mtime):
        """Guarda una lectura completa ya hecha fuera de load_data_async
        (hilo de comparación del watchdog). `mtime` es el del archivo ANTES
        de leerlo: si cambió desde entonces, la precarga se descarta."""
        self._precarga_principal = (payload, ruta, mtime, time.time())

    def _tomar_precarga_principal(self, ruta):
        precarga = getattr(self, '_precarga_principal', None)
        self._precarga_principal = None
        if precarga is None:
            return None
        payload, ruta_precarga, mtime_precarga, instante = precarga
        if ruta_precarga != ruta or (time.time() - instante) > VIGENCIA_PRECARGA_SEGUNDOS:
            return None
        try:
            if os.path.getmtime(ruta) != mtime_precarga:
                return None
        except OSError:
            return None
        return payload

    def load_provisiones_async(self):
        if self.is_loading_prov:
            self._prov_reload_pending = True
            return
        self.is_loading_prov = True
        self._prov_reload_pending = False
        self.thread_prov = ProvisionesLoaderThread(config.settings.PROVISION_EXCEL_PATH)
        self.thread_prov.data_loaded_signal.connect(self._on_prov_data_loaded)
        self.thread_prov.error_signal.connect(self._on_prov_load_error)
        self._iniciar_hilo_retenido(self.thread_prov)

    def _on_main_data_loaded(self, dataframes):
        deleted_sheets = {}
        if len(dataframes) == 5:
            df_clean, df_logs, df_deleted, load_time, deleted_sheets = dataframes
            self.last_load_time = load_time
        elif len(dataframes) == 4:
            df_clean, df_logs, df_deleted, load_time = dataframes
            self.last_load_time = load_time
        else:
            df_clean, df_logs, df_deleted = dataframes

        self.df_master = df_clean
        # Se saca de attrs: pandas lo copia en cada operación sobre el df
        self.termino_distinto_de_duracion = df_clean.attrs.pop('termino_distinto_de_duracion', {})
        self.df_logs = df_logs
        self.df_deleted = df_deleted
        self.deleted_sheets = deleted_sheets
        self.is_loading_main = False
        if getattr(self, '_main_reload_pending', False):
            self.load_data_async()
            return
        self.data_ready.emit()

    def _on_main_load_error(self, error_msg):
        self.is_loading_main = False
        self._main_reload_pending = False
        self.load_error.emit(error_msg)

    def _on_prov_data_loaded(self, dataframes):
        df_prov, lista_planes, uf, civ = dataframes
        self.df_prov = df_prov
        self.lista_planes = lista_planes
        self.valor_uf = uf
        self.valor_civ = civ
        self.is_loading_prov = False
        if getattr(self, '_prov_reload_pending', False):
            self.load_provisiones_async()
            return
        self.provisiones_ready.emit()

    def _on_prov_load_error(self, error_msg):
        self.is_loading_prov = False
        self._prov_reload_pending = False
        self.load_provisiones_error.emit(error_msg)

    def load_contactos_async(self):
        if self.is_loading_contactos: 
            self._contactos_reload_pending = True
            return

        self.is_loading_contactos = True
        self._contactos_reload_pending = False
        self.last_contactos_error = ""
        
        ruta_contactos = config.settings.CONTACTOS_EXCEL_PATH
        
        thread = ContactosLoaderThread(ruta_contactos)
        self.thread_contactos = thread
        thread.data_loaded_signal.connect(self._on_contactos_loaded)
        thread.error_signal.connect(self._on_contactos_error)
        self._iniciar_hilo_retenido(thread)

    def _on_contactos_loaded(self, df):
        self.df_contactos = df
        self.is_loading_contactos = False
        self.last_contactos_error = ""
        
        if getattr(self, '_contactos_reload_pending', False):
            self._contactos_reload_pending = False
            self.load_contactos_async()
            return

        self.contactos_ready.emit()

    def _on_contactos_error(self, error_msg):
        self.is_loading_contactos = False
        self._contactos_reload_pending = False
        self.last_contactos_error = str(error_msg)
        self.load_contactos_error.emit(error_msg)

    def get_contactos_df(self): return self.df_contactos.copy()
    
    def get_general_df(self):
        cols = [COL_VIN, COL_CHASIS, COL_MODELO, COL_FLOTA_VC, COL_EJECUTIVO, COL_RAZON_SOCIAL, COL_RUT, COL_CDB, COL_CDB_FLOTA, COL_FORMA_CONTRATO, COL_TIPO_SERVICIO, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_INICIO_CONTRATO, COL_DURACION_MESES, COL_TERMINO_CONTRATO, COL_ESTADO_CM, COL_PERIODO_INTERNO]
        available = [c for c in cols if c in self.df_master.columns]
        return self.df_master[available].copy()

    def get_comercial_df(self):
        return self.df_master.copy()

    def get_contratos_actuales_df(self):
        """Una fila por VIN: el contrato actual (mayor ID), con todas las columnas."""
        from src.services.comercial_services import contratos_actuales
        return contratos_actuales(self.df_master).copy()

    def get_operaciones_df(self):
        cols = [COL_VIN, COL_CHASIS, COL_MODELO, COL_FLOTA_VC, COL_CDB, COL_CDB_FLOTA, COL_ESTADO_ACTIVACION, COL_ESTADO_ENTREGA, COL_FECHA_BAJA]
        available = [c for c in cols if c in self.df_master.columns]
        return self.df_master[available].copy()
        
    def get_logs_df(self): return self.df_logs.copy()

    def set_logs_df(self, df_logs):
        # Actualiza el historial en RAM sin recargar todo lo demas (Excel
        # principal, provisiones, etc.) y avisa a quien este escuchando
        # (Historial) para que se refresque solo. Pensado para flujos que ya
        # leyeron LogApp.csv en un hilo de fondo (ej. sincronizaciones) y
        # solo necesitan propagar el resultado, sin volver a tocar disco.
        self.df_logs = df_logs
        self.logs_updated.emit()
    def get_deleted_logs_df(self): return self.df_deleted.copy()

    def get_deleted_logs_sheets(self):
        # {nombre_modulo: DataFrame}, una entrada por hoja de
        # RegistroEliminado.xlsx, cada una con su propio esquema intacto (sin
        # mezclar columnas entre modulos). Fuente que usa HistorialModule
        # para la pestaña Papelera; ver MainDataLoaderThread.run().
        return {nombre: df.copy() for nombre, df in self.deleted_sheets.items()}
    def get_provisiones_df(self): return self.df_prov.copy()
    def get_costos(self): return self.lista_planes.copy()
    def get_variables(self): return self.valor_uf, self.valor_civ

    def get_system_health(self):
        from datetime import datetime
        import os
        from config.settings import EXCEL_PATH
        from src.theme.colors import SUCCESS, DANGER, WARNING

        health = {
            "db_status": "Desconectado",
            "db_rows": 0,
            "last_modified": "Desconocido",
            "backups_count": 0,
            "log_status": "Sin revisar",
            "log_color": "#6B7280",
            "recent_errors": [],
            "ram_usage": "N/A",
            "load_time": f"{getattr(self, 'last_load_time', 0.0)} s"
        }
        
        try:
            process = psutil.Process(os.getpid())
            mem_mb = process.memory_info().rss / (1024 * 1024)
            health["ram_usage"] = f"{mem_mb:.0f} MB"
        except ImportError:
            health["ram_usage"] = "Falta psutil"
        
        if not self.df_master.empty:
            health["db_status"] = "Conectado y Estable"
            health["db_rows"] = len(self.df_master)
            
        if os.path.exists(EXCEL_PATH):
            mtime = os.path.getmtime(EXCEL_PATH)
            health["last_modified"] = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            
        backup_dir = os.path.join(os.getcwd(), 'data', 'backups')
        if os.path.exists(backup_dir):
            extension_backup = os.path.splitext(EXCEL_PATH)[1] or '.xlsx'
            health["backups_count"] = len([f for f in os.listdir(backup_dir) if f.endswith(extension_backup)])
            
        log_path = os.path.join(os.getcwd(), 'logs', 'sistema.log')
        if os.path.exists(log_path):
            try:
                # Solo se usan las últimas 50 líneas: se lee el final del
                # archivo en vez de cargar el log completo en cada data_ready.
                with open(log_path, 'rb') as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 65536))
                    lines = f.read().decode('utf-8', errors='ignore').splitlines()
                    errores = [line.strip() for line in lines[-50:] if 'ERROR' in line]
                    warnings_log = sum(1 for line in lines[-50:] if 'WARNING' in line)
                    
                    if errores:
                        health["log_status"] = f"{len(errores)} Errores"
                        health["log_color"] = DANGER
                        health["recent_errors"] = errores[::-1] 
                    elif warnings_log > 0:
                        health["log_status"] = f"{warnings_log} Alertas"
                        health["log_color"] = WARNING
                    else:
                        health["log_status"] = "100% Saludable"
                        health["log_color"] = SUCCESS
            except Exception: pass
                
        return health