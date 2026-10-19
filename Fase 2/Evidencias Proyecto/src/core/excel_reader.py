import pandas as pd
import os
import hashlib
import pickle
import warnings
from config.settings import EXCEL_PATH, LOG_CSV_PATH, DELETED_LOG_EXCEL_PATH
from src.core.cdb_columnas import cdb_a_memoria
from src.core.dataframe_formatter import DataFrameFormatter  # IMPORTACIÓN MAESTRA

warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

COLUMNAS_SNAPSHOT_COMERCIAL = [
    'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'FLOTA VC 2',
    'EJECUTIVO', 'RAZÓN SOCIAL', 'RUT', 'CDB', 'CDB FLOTA', 'FORMA DE CONTRATO',
    'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL',
    'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO',
    'FECHA DE BAJA', 'ESTADO DE ENTREGA', 'PERIODO INTERNO', 'OBSERVACIONES',
    'TIPO DE FACTURACION', 'CONTRATO CREADO EN JUSTTIME',
    'INICIO', 'TERMINO',
    'N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM'
]

class ExcelReader:
    def __init__(self):
        self.filepath = EXCEL_PATH
        self.log_csv_filepath = LOG_CSV_PATH
        self.deleted_filepath = DELETED_LOG_EXCEL_PATH
        # Snapshot local (data/cache), no en la carpeta sincronizada con
        # SharePoint: evita subirlo en cada comparación y que dos usuarios
        # compartan el mismo archivo. El nombre depende de la ruta vigilada.
        carpeta_cache = os.path.join(os.getcwd(), 'data', 'cache')
        os.makedirs(carpeta_cache, exist_ok=True)
        clave = hashlib.md5(os.path.abspath(self.filepath or '').lower().encode('utf-8')).hexdigest()[:12]
        self.snapshot_path = os.path.join(carpeta_cache, f"snapshot_comercial_{clave}.pkl")

    def _clean_and_format_dataframe(self, df):
        # La limpieza ahora incluye la validación estructural (DataFrameFormatter._validate_columns)
        df = DataFrameFormatter.clean(df)
        return df.to_dict('records')

    def _leer_dataframe(self):
        # Fase 3.1 (soporte CSV en ExcelReader/Watchdog): misma bifurcacion
        # por extension ya usada en MainDataLoaderThread (data_manager.py).
        if self.filepath.lower().endswith('.csv'):
            return cdb_a_memoria(pd.read_csv(self.filepath, dtype=str, keep_default_na=False))
        return pd.read_excel(self.filepath)

    def get_commercial_data(self):
        if not os.path.exists(self.filepath): return []
        try:
            df = self._leer_dataframe()
            # Solo filtramos las columnas si existen en el df original
            available_cols = [c for c in COLUMNAS_SNAPSHOT_COMERCIAL if c in df.columns]
            df_filtered = df[available_cols].copy()
            return self._clean_and_format_dataframe(df_filtered)

        except PermissionError:
            print("El Excel está bloqueado por SharePoint. El Watchdog lo intentará más tarde.")
            return [] 
        except ValueError as ve:
            # Capturamos errores de validación específicos (como falta de columnas)
            print(f"Error de Integridad (Comercial): {ve}")
            raise  # Relanzamos el error para que la interfaz lo muestre al usuario
        except Exception as e:
            print(f"Error inesperado leyendo datos comerciales: {e}")
            return []

    def get_general_data(self):
        if not os.path.exists(self.filepath): return []
        try:
            df = self._leer_dataframe()
            cols_general = [
                'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'EJECUTIVO', 
                'RAZÓN SOCIAL', 'RUT', 'CDB', 'FORMA DE CONTRATO', 
                'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL', 
                'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO', 
                'ESTADO DEL CM', 'PERIODO INTERNO'
            ]
            available_cols = [c for c in cols_general if c in df.columns]
            df_filtered = df[available_cols].copy()
            return self._clean_and_format_dataframe(df_filtered)
        except ValueError as ve:
            print(f"Error de Integridad (General): {ve}")
            raise
        except Exception as e:
            print(f"Error inesperado leyendo datos generales: {e}")
            return []

    def get_operaciones_data(self):
        if not os.path.exists(self.filepath): return []
        try:
            df = self._leer_dataframe()
            cols_operaciones = [
                'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'CDB', 
                'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'
            ]
            available_cols = [c for c in cols_operaciones if c in df.columns]
            df_filtered = df[available_cols].copy()
            return self._clean_and_format_dataframe(df_filtered)
        except ValueError as ve:
            print(f"Error de Integridad (Operaciones): {ve}")
            raise
        except Exception as e:
            print(f"Error inesperado leyendo datos de operaciones: {e}")
            return []

    def get_logs_data(self):
        # LogApp.csv (self.log_csv_filepath = config.settings.LOG_CSV_PATH)
        # es el unico historial oficial (ver excel_writer.ExcelWriter._log_changes).
        if not self.log_csv_filepath or not os.path.exists(self.log_csv_filepath): return []
        try:
            df = pd.read_csv(self.log_csv_filepath, dtype=str, keep_default_na=False)
            return df.to_dict('records')
        except Exception as e:
            print(f"Error leyendo logs: {e}")
            return []

    def get_deleted_logs_data(self):
        if not os.path.exists(self.deleted_filepath): return []
        try:
            df = pd.read_excel(self.deleted_filepath)
            for col in df.select_dtypes(include=['datetime64']).columns:
                df[col] = df[col].dt.strftime('%m/%d/%Y')
            return df.fillna("").to_dict('records')
        except Exception as e: 
            print(f"Error leyendo logs eliminados: {e}")
            return []

    def _guardar_snapshot(self, data):
        if not data:
            return False
        try:
            with open(self.snapshot_path, 'wb') as f: pickle.dump(data, f)
            return True
        except Exception as e:
            print(f"Aviso al crear snapshot: {e}")
        return False

    def create_snapshot(self):
        return self._guardar_snapshot(self.get_commercial_data())

    def compare_snapshot(self):
        return self._comparar_y_actualizar_snapshot(self.get_commercial_data())

    def compare_snapshot_desde_df(self, df_limpio):
        """Igual que compare_snapshot(), pero sobre un DataFrame ya leído y
        limpiado (leer_datos_principales), sin volver a leer el archivo."""
        if df_limpio is None or df_limpio.empty:
            data = []
        else:
            cols = [c for c in COLUMNAS_SNAPSHOT_COMERCIAL if c in df_limpio.columns]
            data = df_limpio[cols].to_dict('records')
        return self._comparar_y_actualizar_snapshot(data)

    def _comparar_y_actualizar_snapshot(self, new_data):
        # El snapshot nuevo se escribe con los datos ya leídos (antes
        # create_snapshot() volvía a leer y limpiar el archivo completo).
        if not os.path.exists(self.snapshot_path):
            self._guardar_snapshot(new_data)
            return []
        try:
            with open(self.snapshot_path, 'rb') as f: old_data = pickle.load(f)

            if not new_data and old_data: return []
                
            df_old = pd.DataFrame(old_data).astype(str).drop_duplicates(subset=['VIN']).set_index('VIN') if old_data else pd.DataFrame()
            df_new = pd.DataFrame(new_data).astype(str).drop_duplicates(subset=['VIN']).set_index('VIN') if new_data else pd.DataFrame()
            
            cambios_encontrados = []
            if df_old.empty and df_new.empty: return cambios_encontrados
            
            vins_viejos = set(df_old.index)
            vins_nuevos = set(df_new.index)
            
            agregados = vins_nuevos - vins_viejos
            eliminados = vins_viejos - vins_nuevos
            comunes = list(vins_viejos.intersection(vins_nuevos))
            
            for vin in agregados: cambios_encontrados.append({"VIN": str(vin), "campo": "Nuevo Camión", "viejo": "-", "nuevo": "Agregado", "tipo": "Alta"})
            for vin in eliminados: cambios_encontrados.append({"VIN": str(vin), "campo": "Camión Eliminado", "viejo": "Existía", "nuevo": "Eliminado", "tipo": "Baja"})
            
            if comunes:
                df_comun_old = df_old.loc[comunes].fillna("").replace("nan", "")
                df_comun_new = df_new.loc[comunes].fillna("").replace("nan", "")
                df_comun_old, df_comun_new = df_comun_old.align(df_comun_new, axis=1)
                
                diff_mask = df_comun_old != df_comun_new
                
                for col in diff_mask.columns:
                    vins_diff = diff_mask.index[diff_mask[col]].tolist()
                    for vin in vins_diff:
                        val_viejo = df_comun_old.at[vin, col]
                        val_nuevo = df_comun_new.at[vin, col]
                        cambios_encontrados.append({
                            "VIN": str(vin), 
                            "campo": col, 
                            "viejo": val_viejo if val_viejo else "Vacío", 
                            "nuevo": val_nuevo if val_nuevo else "Vacío", 
                            "tipo": "Modificación"
                        })
            
            # --- AUTO-HEALING: Si hay más de 200 cambios, es un choque de formatos (no real) ---
            if len(cambios_encontrados) > 200:
                print(f"Auto-Heal: Se detectaron {len(cambios_encontrados)} cambios. Reconstruyendo snapshot en silencio.")
                self._guardar_snapshot(new_data)
                return []

            self._guardar_snapshot(new_data)
            return cambios_encontrados
        except Exception as e:
            print(f"Error crítico al comparar snapshot: {e}")
            return []