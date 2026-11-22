import pandas as pd
import os
import hashlib
import pickle
import warnings
from config.settings import EXCEL_PATH, LOG_CSV_PATH, DELETED_LOG_EXCEL_PATH
from src.core.cdb_columnas import cdb_a_memoria
from src.core.dataframe_formatter import DataFrameFormatter  # IMPORTACIÓN MAESTRA
import logging

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

COLUMNAS_SNAPSHOT_COMERCIAL = [
    'ID', 'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'FLOTA VC 2',
    'EJECUTIVO', 'RAZÓN SOCIAL', 'RUT', 'CDB', 'CDB FLOTA', 'FORMA DE CONTRATO',
    'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL',
    'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO',
    'FECHA DE BAJA', 'ESTADO DE ENTREGA', 'PERIODO INTERNO', 'OBSERVACIONES',
    'TIPO DE FACTURACION', 'CONTRATO CREADO EN JUSTTIME',
    'INICIO', 'TERMINO',
    'N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM',
    'ULTIMO PAGO CM', 'FECHA ULTIMO PAGO CM',
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
            logger.warning("El Excel está bloqueado por SharePoint. El Watchdog lo intentará más tarde.")
            return [] 
        except ValueError as ve:
            # Capturamos errores de validación específicos (como falta de columnas)
            logger.error(f"Error de Integridad (Comercial): {ve}")
            raise  # Relanzamos el error para que la interfaz lo muestre al usuario
        except Exception as e:
            logger.error(f"Error inesperado leyendo datos comerciales: {e}", exc_info=True)
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
            logger.error(f"Error de Integridad (General): {ve}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado leyendo datos generales: {e}", exc_info=True)
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
            logger.error(f"Error de Integridad (Operaciones): {ve}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado leyendo datos de operaciones: {e}", exc_info=True)
            return []

    def get_logs_data(self):
        # LogApp.csv (self.log_csv_filepath = config.settings.LOG_CSV_PATH)
        # es el unico historial oficial (ver excel_writer.ExcelWriter._log_changes).
        if not self.log_csv_filepath or not os.path.exists(self.log_csv_filepath): return []
        try:
            df = pd.read_csv(self.log_csv_filepath, dtype=str, keep_default_na=False)
            return df.to_dict('records')
        except Exception as e:
            logger.warning(f"Error leyendo logs: {e}")
            return []

    def get_deleted_logs_data(self):
        if not os.path.exists(self.deleted_filepath): return []
        try:
            df = pd.read_excel(self.deleted_filepath)
            for col in df.select_dtypes(include=['datetime64']).columns:
                df[col] = df[col].dt.strftime('%m/%d/%Y')
            return df.fillna("").to_dict('records')
        except Exception as e: 
            logger.warning(f"Error leyendo logs eliminados: {e}")
            return []

    def _guardar_snapshot(self, data):
        if not data:
            return False
        try:
            with open(self.snapshot_path, 'wb') as f: pickle.dump(data, f)
            return True
        except Exception as e:
            logger.warning(f"Aviso al crear snapshot: {e}")
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

    _CAMPOS_RENOVACION = ('INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO')

    @classmethod
    def _agrupar_renovaciones(cls, cambios, df_old, df_new, agregados, con_id):
        """Un contrato que pasa a Renovado es una renovación: se junta con el contrato nuevo del mismo VIN (si ya
        está en el archivo) y el aviso muestra el contrato anterior → el nuevo, en vez de «modificado» y «agregado»."""
        renovados = [c for c in cambios if c['tipo'] == 'Modificación' and c['campo'] == 'ESTADO COMERCIAL'
                     and str(c['nuevo']).strip().upper() == 'RENOVADO' and str(c['viejo']).strip().upper() != 'RENOVADO']
        if not renovados:
            return cambios
        por_vin_nuevo = {}
        if con_id and not df_new.empty:
            for clave in agregados:
                por_vin_nuevo.setdefault(df_new.at[clave, 'VIN'], []).append(clave)
        quitar, renovaciones = set(), []
        for c in renovados:
            vin = c['VIN']
            quitar.add(id(c))
            detalle = [{"VIN": vin, "campo": "ESTADO COMERCIAL", "viejo": c['viejo'], "nuevo": c['nuevo'], "tipo": "Renovación"}]
            claves = por_vin_nuevo.get(vin, [])
            if claves:
                nuevo = max(claves, key=lambda k: int(df_new.at[k, 'ID']) if str(df_new.at[k, 'ID']).isdigit() else 0)
                viejo = [k for k in df_old.index if df_old.at[k, 'VIN'] == vin and str(df_old.at[k, 'ESTADO COMERCIAL']).strip().upper() != 'RENOVADO'] \
                    if 'ESTADO COMERCIAL' in df_old.columns else []
                fila_vieja = df_old.loc[viejo[0]] if viejo else None
                for campo in cls._CAMPOS_RENOVACION:
                    if campo in df_new.columns and fila_vieja is not None and campo in df_old.columns:
                        a = str(fila_vieja[campo]).strip()
                        b = str(df_new.at[nuevo, campo]).strip()
                        if a != b and not (a.lower() in ('', 'nan') and b.lower() in ('', 'nan')):
                            detalle.append({"VIN": vin, "campo": campo, "viejo": a or "Vacío", "nuevo": b or "Vacío", "tipo": "Renovación"})
                for c2 in cambios:
                    if c2['tipo'] == 'Alta' and c2['VIN'] == vin and c2['campo'] == 'Nuevo contrato':
                        quitar.add(id(c2))
            renovaciones.extend(detalle)
        return [c for c in cambios if id(c) not in quitar] + renovaciones

    def _comparar_y_actualizar_snapshot(self, new_data):
        # El snapshot nuevo se escribe con los datos ya leídos (antes
        # create_snapshot() volvía a leer y limpiar el archivo completo).
        if not os.path.exists(self.snapshot_path):
            self._guardar_snapshot(new_data)
            return []
        try:
            with open(self.snapshot_path, 'rb') as f: old_data = pickle.load(f)

            if not new_data and old_data: return []
                
            # Cada fila es un contrato: la clave es VIN + ID. Con solo el VIN, un contrato nuevo de un camión que ya
            # estaba no se avisaba, ni los cambios de su segundo contrato. Una base guardada sin ID compara por VIN.
            con_id = bool(old_data) and bool(new_data) and 'ID' in old_data[0] and 'ID' in new_data[0]

            def indexar(datos):
                if not datos:
                    return pd.DataFrame()
                df = pd.DataFrame(datos).astype(str)
                df['_K'] = df['VIN'] + '|' + df['ID'] if con_id else df['VIN']
                return df.drop_duplicates(subset=['_K']).set_index('_K')

            df_old, df_new = indexar(old_data), indexar(new_data)

            cambios_encontrados = []
            if df_old.empty and df_new.empty: return cambios_encontrados

            claves_viejas = set(df_old.index)
            claves_nuevas = set(df_new.index)
            vins_viejos = set(df_old['VIN']) if not df_old.empty else set()
            vins_nuevos = set(df_new['VIN']) if not df_new.empty else set()

            agregados = claves_nuevas - claves_viejas
            eliminados = claves_viejas - claves_nuevas
            comunes = list(claves_viejas.intersection(claves_nuevas))

            for clave in agregados:
                vin = df_new.at[clave, 'VIN']
                campo = "Nuevo contrato" if vin in vins_viejos else "Nuevo Camión"
                cambios_encontrados.append({"VIN": str(vin), "campo": campo, "viejo": "-", "nuevo": "Agregado", "tipo": "Alta"})
            for clave in eliminados:
                vin = df_old.at[clave, 'VIN']
                campo = "Contrato Eliminado" if vin in vins_nuevos else "Camión Eliminado"
                cambios_encontrados.append({"VIN": str(vin), "campo": campo, "viejo": "Existía", "nuevo": "Eliminado", "tipo": "Baja"})

            if comunes:
                columnas = [c for c in df_old.columns if c not in ('VIN', 'ID')]
                df_comun_old = df_old.loc[comunes, columnas].fillna("").replace("nan", "")
                df_comun_new = df_new.loc[comunes, [c for c in df_new.columns if c in columnas]].fillna("").replace("nan", "")
                df_comun_old, df_comun_new = df_comun_old.align(df_comun_new, axis=1)

                diff_mask = df_comun_old != df_comun_new

                for col in diff_mask.columns:
                    claves_diff = diff_mask.index[diff_mask[col]].tolist()
                    for clave in claves_diff:
                        val_viejo = df_comun_old.at[clave, col]
                        val_nuevo = df_comun_new.at[clave, col]
                        cambios_encontrados.append({
                            "VIN": str(df_old.at[clave, 'VIN']),
                            "campo": col,
                            "viejo": val_viejo if val_viejo else "Vacío",
                            "nuevo": val_nuevo if val_nuevo else "Vacío",
                            "tipo": "Modificación"
                        })
            
            cambios_encontrados = self._agrupar_renovaciones(cambios_encontrados, df_old, df_new, agregados, con_id)

            # Más de 200 cambios (importación del 3PC, corrección en bloque o cambio de formato): un solo aviso resumido
            if len(cambios_encontrados) > 200:
                from src.services.cambios_archivos_service import resumir_carga_masiva
                logger.info(f"Se detectaron {len(cambios_encontrados)} cambios; se avisan resumidos como carga masiva.")
                self._guardar_snapshot(new_data)
                return resumir_carga_masiva(cambios_encontrados)

            self._guardar_snapshot(new_data)
            return cambios_encontrados
        except Exception as e:
            logger.error(f"Error crítico al comparar snapshot: {e}", exc_info=True)
            return []