"""Backend de escritura CSV para ExcelWriter (Fase 1, migracion PruebasFM.xlsx
-> RM_CONTRATOS.csv, 23-09-2026). Implementa el mismo contrato/comportamiento que
la rama .xlsx de update_cells/add_new_row/delete_row en excel_writer.py, pero
persistiendo sobre un DataFrame + pd.read_csv/to_csv en vez de un Workbook de
openpyxl. Estas funciones NO se llaman directo desde la UI: ExcelWriter las
invoca internamente cuando el archivo objetivo termina en '.csv', pasandose a
si mismo (`writer`) para reutilizar _crear_backup/_log_changes/_log_deleted
sin duplicar esa logica aqui.

Deliberadamente NO usa WorkbookCache (es especifico de openpyxl.Workbook, no
aplica a CSV) -- en su lugar usa un lock por ruta propio, mas liviano
(_lock_para), solo para serializar escrituras concurrentes sobre el mismo
archivo dentro del mismo proceso (misma proteccion que WorkbookCache.lock_para
le da a la rama .xlsx, sin el cacheo de Workbook)."""

from src.core.normalizacion import normalizar_para_escritura
import os
import threading
import time
import uuid
import logging
from datetime import datetime

import pandas as pd
from src.core.cdb_columnas import cdb_a_memoria, cdb_a_disco, asegurar_cdb_flota, CDB_COMERCIAL_EN_DISCO

from src.core.data_manager import DataManager

logger = logging.getLogger(__name__)

_locks_por_ruta = {}
_meta_lock = threading.Lock()


def _lock_para(ruta):
    ruta_norm = os.path.normcase(os.path.normpath(ruta))
    with _meta_lock:
        if ruta_norm not in _locks_por_ruta:
            _locks_por_ruta[ruta_norm] = threading.Lock()
        return _locks_por_ruta[ruta_norm]


def _leer_csv(target_file):
    """dtype=str + keep_default_na=False: mismo criterio de lectura que ya
    usa el resto de la app para CSV (MainDataLoaderThread, Correos.csv,
    LogApp.csv) -- no perder ceros/guiones ni convertir '' en NaN."""
    return asegurar_cdb_flota(cdb_a_memoria(pd.read_csv(target_file, dtype=str, keep_default_na=False)))


def _archivo_usa_cdb_comercial(target_file):
    """True si el CSV de destino ya tiene el encabezado CDB COMERCIAL."""
    try:
        if not os.path.exists(target_file):
            return False
        columnas = pd.read_csv(target_file, nrows=0, encoding='utf-8-sig').columns
        return CDB_COMERCIAL_EN_DISCO in columnas
    except Exception:
        return False


def _escribir_csv_atomico(df, target_file, temp_file):
    """Mismo patron seguro que ya usa la rama .xlsx de ExcelWriter: escribir
    a un temporal, fsync, y copy2 sobre el destino (copy2, no os.replace: es
    el que ya tolera mejor las particularidades de SharePoint/OneDrive en
    esta app)."""
    if _archivo_usa_cdb_comercial(target_file):
        df = cdb_a_disco(df)
    df.to_csv(temp_file, index=False, encoding='utf-8-sig')
    try:
        with open(temp_file, 'rb+') as f:
            os.fsync(f.fileno())
    except Exception:
        pass
    import shutil
    shutil.copy2(temp_file, target_file)


def _limpiar_temp(temp_file):
    try:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    except Exception:
        pass


def _localizar_fila_por_keys(df, keys):
    """Replica la logica de matching de update_cells/delete_row para
    changes_dict con 'keys' (varias columnas identificadoras a la vez).
    Mismo criterio de tolerancia '.0' que la rama .xlsx (str(...).replace
    ('.0','')) para columnas normales. 'AÑO - MES' usa el mismo criterio
    "contiene" que normalize_fecha() en la rama .xlsx -- ahi normalize_fecha
    solo formatea a 'YYYY - Mes' si el valor es datetime/tiene strftime; un
    CSV nunca trae datetime nativo (confirmado en la auditoria de lectura:
    dtype=str siempre), asi que el valor ya es texto tal cual quedo
    guardado y se compara igual que el fallback de esa funcion
    (str(val).strip()). Devuelve el indice de la primera fila que matchea
    todas las keys, o None."""
    if df.empty:
        return None
    mask = pd.Series(True, index=df.index)
    for k_col, k_val in keys.items():
        if k_col not in df.columns:
            return None
        if k_col == 'AÑO - MES':
            col_norm = df[k_col].astype(str).str.upper()
            mask &= col_norm.str.contains(str(k_val).strip().upper(), regex=False)
        else:
            col_norm = df[k_col].astype(str).str.strip().str.replace('.0', '', regex=False)
            val_norm = str(k_val).strip().replace('.0', '')
            mask &= (col_norm == val_norm)
    coincidencias = df.index[mask]
    return coincidencias[0] if len(coincidencias) > 0 else None


def _localizar_fila_por_vin(df, vin):
    """Replica el matching de VIN de la rama .xlsx: comparacion EXACTA tras
    strip (a diferencia de 'keys', el VIN no aplica tolerancia '.0')."""
    if df.empty or 'VIN' not in df.columns:
        return None
    target_vin = str(vin).strip()
    coincidencias = df.index[df['VIN'].astype(str).str.strip() == target_vin]
    return coincidencias[0] if len(coincidencias) > 0 else None


def _indice_vin(df):
    """VIN (tras strip) -> primera fila donde aparece: mismo resultado que
    _localizar_fila_por_vin, pero armado una sola vez por lote. Con 500 VIN
    sobre ~12.000 filas, buscar uno por uno tomaba ~1 s de GIL y trababa la
    pantalla de carga."""
    indice = {}
    if df.empty or 'VIN' not in df.columns:
        return indice
    for idx, vin in zip(df.index, df['VIN'].astype(str).str.strip()):
        indice.setdefault(vin, idx)
    return indice


def _tiene_columna_id(df):
    """PruebasFM con contratos por ID: tiene ID y VIN (contactos tiene ID pero no VIN)."""
    return 'ID' in df.columns and 'VIN' in df.columns


def _normalizar_id(valor):
    """ID como texto entero ('115'): sin espacios ni '.0'; '' si viene vacío."""
    if valor is None or pd.isna(valor):
        return ''
    texto = str(valor).strip()
    if texto.lower() in ('nan', 'none', '-'):
        return ''
    return texto[:-2] if texto.endswith('.0') else texto


def _indice_id(df):
    """ID (texto entero, tras strip) -> primera fila donde aparece."""
    indice = {}
    if df.empty or 'ID' not in df.columns:
        return indice
    for idx, valor in zip(df.index, df['ID'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)):
        if valor:
            indice.setdefault(valor, idx)
    return indice


def _proximo_id(df):
    """Máximo ID numérico del archivo + 1 (1 si no hay ninguno)."""
    if 'ID' not in df.columns:
        return None
    numeros = pd.to_numeric(df['ID'].astype(str).str.strip(), errors='coerce').dropna()
    return int(numeros.max()) + 1 if len(numeros) else 1


def update_cells_csv(writer, target_file, changes_dict, module_name="Sistema"):
    dm = DataManager()
    dm.is_app_saving = True
    dm.save_timestamp = time.time()

    writer._crear_backup(target_file)
    if not writer.last_backup_ok:
        dm.is_app_saving = False
        logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
        return False

    os.makedirs(writer.temp_dir, exist_ok=True)
    temp_file = os.path.join(writer.temp_dir, f"temp_update_{uuid.uuid4().hex}.csv")

    lock = _lock_para(target_file)
    lock.acquire()
    try:
        try:
            df = _leer_csv(target_file)
        except FileNotFoundError:
            logger.warning(f"No se encontro '{os.path.basename(target_file)}' para actualizar.")
            return False

        logs_to_write = []
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        indice_vin = None
        indice_id = None

        for row_id, data in changes_dict.items():
            cambios = data.get('cambios', {})
            id_contrato = _normalizar_id(data.get('ID')) if 'keys' not in data and _tiene_columna_id(df) else ''

            if 'keys' in data:
                row_idx = _localizar_fila_por_keys(df, data['keys'])
                identificador_log = " | ".join(str(v) for v in data['keys'].values())
            elif id_contrato:
                if indice_id is None:
                    indice_id = _indice_id(df)
                row_idx = indice_id.get(id_contrato)
                identificador_log = str(data.get('VIN') or id_contrato).strip()
            else:
                target_vin = str(data.get('VIN')).strip()
                if indice_vin is None:
                    indice_vin = _indice_vin(df)
                row_idx = indice_vin.get(target_vin)
                identificador_log = target_vin

            if row_idx is None:
                print(f"No se encontró la fila objetivo para guardar: {identificador_log}")
                # Mismo criterio conservador que la rama .xlsx: si una fila
                # de este mismo changes_dict ya no se encuentra, se aborta
                # todo el lote sin escribir nada (ninguna mutacion parcial).
                return False

            for col_name, new_value in cambios.items():
                new_value = normalizar_para_escritura(col_name, new_value)
                if col_name == 'TÉRMINO CONTRATO':
                    # Igual que la rama .xlsx: nunca se escribe directo, se
                    # recalcula siempre en DataFrameFormatter.clean().
                    continue

                if col_name in df.columns:
                    old_value_raw = df.at[row_idx, col_name]
                    old_value = "" if pd.isna(old_value_raw) else str(old_value_raw).strip()
                    if old_value != str(new_value).strip():
                        df.at[row_idx, col_name] = new_value
                        logs_to_write.append([current_time, module_name, identificador_log, col_name, old_value, str(new_value)])
                        if col_name == 'VIN':
                            indice_vin = None  # el índice quedó desactualizado
                        elif col_name == 'ID':
                            indice_id = None

        _escribir_csv_atomico(df, target_file, temp_file)
        dm.save_timestamp = time.time()
        writer._log_changes(logs_to_write)
        return True

    except PermissionError:
        print(f"El CSV {os.path.basename(target_file)} está bloqueado.")
        return False
    except Exception as e:
        print(f"Fallo inesperado al guardar CSV: {e}")
        return False
    finally:
        lock.release()
        dm.is_app_saving = False
        _limpiar_temp(temp_file)


def add_new_row_csv(writer, target_file, new_data_dict, module_name="Sistema"):
    dm = DataManager()
    dm.is_app_saving = True
    dm.save_timestamp = time.time()

    writer._crear_backup(target_file)
    if not writer.last_backup_ok:
        dm.is_app_saving = False
        logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
        return False

    os.makedirs(writer.temp_dir, exist_ok=True)
    temp_file = os.path.join(writer.temp_dir, f"temp_add_{uuid.uuid4().hex}.csv")

    lock = _lock_para(target_file)
    lock.acquire()
    try:
        try:
            df = _leer_csv(target_file)
        except FileNotFoundError:
            logger.warning(f"No se encontro '{os.path.basename(target_file)}' para agregar la fila.")
            return False

        # Mismo criterio que la rama .xlsx (sheet.max_row+1, fila nueva al
        # final): se inicializan TODAS las columnas existentes en "" (una
        # celda de Excel nunca tocada se lee como None/vacio, equivalente),
        # y solo se sobreescriben las que llegan en new_data_dict Y tienen
        # valor truthy -- "if col_name in header_map and value" en la rama
        # .xlsx: un valor falsy (0, '', None) deja la columna en blanco,
        # igual que aqui. Una columna de new_data_dict que NO exista en el
        # CSV se ignora silenciosamente (no se crea una columna nueva),
        # igual que la rama .xlsx.
        nueva_fila = {col: "" for col in df.columns}
        logs_to_write = []
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target_id = new_data_dict.get('ID', new_data_dict.get('VIN', new_data_dict.get('CDB', 'N/A')))
        if _tiene_columna_id(df) and not _normalizar_id(new_data_dict.get('ID')):
            new_data_dict = {**new_data_dict, 'ID': str(_proximo_id(df))}

        for col_name, value in new_data_dict.items():
            value = normalizar_para_escritura(col_name, value)
            if col_name in df.columns and value:
                nueva_fila[col_name] = value
                logs_to_write.append([current_time, module_name, target_id, col_name, "NUEVO REGISTRO", str(value)])

        df.loc[len(df)] = nueva_fila

        _escribir_csv_atomico(df, target_file, temp_file)
        writer._log_changes(logs_to_write)
        dm.save_timestamp = time.time()
        return True

    except PermissionError:
        print(f"El CSV {os.path.basename(target_file)} está bloqueado.")
        return False
    except Exception as e:
        print(f"Fallo inesperado al añadir fila en CSV: {e}")
        return False
    finally:
        lock.release()
        dm.is_app_saving = False
        _limpiar_temp(temp_file)


def add_new_rows_batch_csv(writer, target_file, new_data_dicts, module_name="Sistema"):
    """Igual que add_new_row_csv, pero para varias filas con una unica
    apertura/backup/log -- mismo criterio de add_new_rows_batch en la rama
    .xlsx (usado por la importacion en lote de Power BI, src/ui/importar_powerbi.py)."""
    if not new_data_dicts:
        return True

    dm = DataManager()
    dm.is_app_saving = True
    dm.save_timestamp = time.time()

    writer._crear_backup(target_file)
    if not writer.last_backup_ok:
        dm.is_app_saving = False
        logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
        return False

    os.makedirs(writer.temp_dir, exist_ok=True)
    temp_file = os.path.join(writer.temp_dir, f"temp_add_batch_{uuid.uuid4().hex}.csv")

    lock = _lock_para(target_file)
    lock.acquire()
    try:
        try:
            df = _leer_csv(target_file)
        except FileNotFoundError:
            logger.warning(f"No se encontro '{os.path.basename(target_file)}' para agregar el lote de filas.")
            return False

        logs_to_write = []
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filas_nuevas = []
        siguiente_id = _proximo_id(df) if _tiene_columna_id(df) else None

        for new_data_dict in new_data_dicts:
            nueva_fila = {col: "" for col in df.columns}
            target_id = new_data_dict.get('ID', new_data_dict.get('VIN', new_data_dict.get('CDB', 'N/A')))
            if siguiente_id is not None and not _normalizar_id(new_data_dict.get('ID')):
                new_data_dict = {**new_data_dict, 'ID': str(siguiente_id)}
                siguiente_id += 1
            for col_name, value in new_data_dict.items():
                value = normalizar_para_escritura(col_name, value)
                if col_name in df.columns and value:
                    nueva_fila[col_name] = value
                    logs_to_write.append([current_time, module_name, target_id, col_name, "NUEVO REGISTRO", str(value)])
            filas_nuevas.append(nueva_fila)

        if filas_nuevas:
            df = pd.concat([df, pd.DataFrame(filas_nuevas, columns=df.columns)], ignore_index=True)

        _escribir_csv_atomico(df, target_file, temp_file)
        writer._log_changes(logs_to_write)
        dm.save_timestamp = time.time()
        return True

    except PermissionError:
        print(f"El CSV {os.path.basename(target_file)} está bloqueado.")
        return False
    except Exception as e:
        print(f"Fallo inesperado al añadir el lote de filas en CSV: {e}")
        return False
    finally:
        lock.release()
        dm.is_app_saving = False
        _limpiar_temp(temp_file)


def delete_row_csv(writer, target_file, primary_key_val=None, module_name="Sistema", keys_dict=None):
    dm = DataManager()
    dm.is_app_saving = True
    dm.save_timestamp = time.time()

    writer._crear_backup(target_file)
    if not writer.last_backup_ok:
        dm.is_app_saving = False
        logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
        return False

    os.makedirs(writer.temp_dir, exist_ok=True)
    temp_file = os.path.join(writer.temp_dir, f"temp_delete_{uuid.uuid4().hex}.csv")

    lock = _lock_para(target_file)
    lock.acquire()
    try:
        try:
            df = _leer_csv(target_file)
        except FileNotFoundError:
            return False

        columnas = list(df.columns)

        if keys_dict:
            row_idx = _localizar_fila_por_keys(df, keys_dict)
        else:
            row_idx = _localizar_fila_por_vin(df, primary_key_val)

        if row_idx is not None:
            row_data = df.loc[row_idx, columnas].tolist()
            writer._log_deleted(columnas, row_data, module_name)
            df = df.drop(index=row_idx).reset_index(drop=True)

            _escribir_csv_atomico(df, target_file, temp_file)
            dm.save_timestamp = time.time()
            return True

        return False

    except PermissionError:
        print(f"El CSV {os.path.basename(target_file)} está bloqueado.")
        return False
    except Exception as e:
        print(f"Fallo inesperado al eliminar fila en CSV: {e}")
        return False
    finally:
        lock.release()
        dm.is_app_saving = False
        _limpiar_temp(temp_file)
