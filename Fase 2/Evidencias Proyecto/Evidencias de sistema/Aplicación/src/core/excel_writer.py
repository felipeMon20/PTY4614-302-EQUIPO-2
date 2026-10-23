from src.core.normalizacion import normalizar_para_escritura
import copy
import os
import re
import glob
import shutil
import time
import openpyxl
import uuid
import csv
import logging
from datetime import datetime
import config.settings
from src.core.data_manager import DataManager
from src.core.workbook_cache import WorkbookCache
from src.core import excel_writer_csv_backend
import pandas as pd

logger = logging.getLogger(__name__)

_HEADER_LOG_DEFAULT = ["FECHA Y HORA", "MÓDULO", "IDENTIFICADOR", "CAMPO MODIFICADO", "VALOR ANTERIOR", "NUEVO VALOR"]


def migrar_historial_legacy(log_xlsx_path, log_csv_path):
    # Migracion unica e idempotente del historial legado (LogApp.xlsx +
    # LogApp_incremental.csv, ubicados via log_xlsx_path) al archivo
    # canonico unico LogApp.csv (log_csv_path, ver config.settings.LOG_CSV_PATH).
    #
    # No hace nada (devuelve False) si log_csv_path esta vacio, si ya existe
    # -- ya fue migrado antes, o ya es la fuente activa en una instalacion
    # nueva -- o si no hay ningun archivo legado que migrar. Los archivos
    # originales nunca se modifican ni se borran: esta funcion solo los lee.
    #
    # Lanza RuntimeError si la verificacion de integridad post-escritura
    # falla, dejando LogApp.csv sin crear para no perder ni duplicar datos.
    if not log_csv_path:
        return False

    csv_path = log_csv_path
    if os.path.exists(csv_path):
        return False

    legacy_csv_path = os.path.splitext(log_xlsx_path)[0] + "_incremental.csv" if log_xlsx_path else ""
    xlsx_existe = bool(log_xlsx_path) and os.path.exists(log_xlsx_path)
    legacy_csv_existe = bool(legacy_csv_path) and os.path.exists(legacy_csv_path)

    if not xlsx_existe and not legacy_csv_existe:
        return False

    header = None
    filas_xlsx = []
    filas_csv = []

    if xlsx_existe:
        try:
            wb = openpyxl.load_workbook(log_xlsx_path, read_only=True)
            ws = wb.active
            filas_iter = ws.iter_rows(values_only=True)
            header = next(filas_iter, None)
            for row in filas_iter:
                if row is None or all(v is None for v in row):
                    continue
                filas_xlsx.append(["" if v is None else v for v in row])
            wb.close()
        except Exception as e:
            logger.error(f"Migracion de historial abortada: no se pudo leer {os.path.basename(log_xlsx_path)}: {e}")
            raise

    if legacy_csv_existe:
        try:
            with open(legacy_csv_path, encoding='utf-8-sig', newline='') as f:
                lector = csv.reader(f)
                header_csv = next(lector, None)
                if header is None:
                    header = header_csv
                for row in lector:
                    filas_csv.append(row)
        except Exception as e:
            logger.error(f"Migracion de historial abortada: no se pudo leer {os.path.basename(legacy_csv_path)}: {e}")
            raise

    if header is None:
        header = _HEADER_LOG_DEFAULT

    filas_esperadas = len(filas_xlsx) + len(filas_csv)
    tmp_path = csv_path + f".migrando_{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp_path, 'w', newline='', encoding='utf-8-sig') as f:
            escritor = csv.writer(f)
            escritor.writerow(header)
            for row in filas_xlsx:
                escritor.writerow(row)
            for row in filas_csv:
                escritor.writerow(row)

        with open(tmp_path, encoding='utf-8-sig') as f:
            filas_escritas = sum(1 for _ in f) - 1

        if filas_escritas != filas_esperadas:
            raise RuntimeError(
                f"Verificacion de migracion de historial fallida: se esperaban {filas_esperadas} filas "
                f"y se escribieron {filas_escritas}. LogApp.csv no fue creado; los archivos originales "
                "permanecen intactos."
            )

        os.replace(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

    logger.info(f"Historial migrado a {os.path.basename(csv_path)}: {filas_esperadas} filas.")
    return True


class ExcelWriter:
    def __init__(self):
        self.filepath = config.settings.EXCEL_PATH
        self.log_filepath = config.settings.LOG_EXCEL_PATH  # legado, solo para ubicar el .xlsx a migrar
        self.log_csv_filepath = config.settings.LOG_CSV_PATH  # historial oficial (LogApp.csv)
        self.deleted_filepath = config.settings.DELETED_LOG_EXCEL_PATH
        self.backup_dir = os.path.join(os.getcwd(), 'data', 'backups')
        self.temp_dir = os.path.join(os.getcwd(), 'data', 'temp')
        self.last_backup_ok = True

    def _crear_backup(self, target_filepath=None):
        # Devuelve True si el backup se creo (o si no habia nada que respaldar
        # todavia, ej. primer guardado) y False si el intento de copia fallo.
        # El fallo NO debe frenar el guardado real (por eso solo se registra),
        # pero self.last_backup_ok permite que la UI avise al usuario.
        ruta_base = target_filepath or self.filepath
        try:
            if not os.path.exists(ruta_base):
                self.last_backup_ok = True
                return True
            if not os.path.exists(self.backup_dir):
                os.makedirs(self.backup_dir)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Preserva la extension real del archivo (B-5.2, 18-09-2026: antes
            # se hardcodeaba ".xlsx" aqui, asi que un backup de un archivo
            # .csv -- ej. Correos.csv -- quedaba mal nombrado como
            # "..._backup_<timestamp>.xlsx" aunque el contenido copiado
            # siguiera siendo CSV. os.path.splitext no cambia nada para los
            # .xlsx existentes: mismo nombre de backup que antes.
            nombre_base, extension = os.path.splitext(os.path.basename(ruta_base))
            backup_name = f"{nombre_base}_backup_{timestamp}{extension}"
            backup_path = os.path.join(self.backup_dir, backup_name)

            shutil.copy2(ruta_base, backup_path)

            archivos = sorted(glob.glob(os.path.join(self.backup_dir, f"{nombre_base}_backup_*{extension}")), key=os.path.getmtime)
            if len(archivos) > 10:
                for f in archivos[:-10]:
                    try: os.remove(f)
                    except: pass
            self.last_backup_ok = True
            return True
        except Exception as e:
            print(f"Aviso: No se pudo crear el backup automático: {e}")
            logger.warning(f"No se pudo crear el backup automático de '{os.path.basename(ruta_base)}': {e}")
            self.last_backup_ok = False
            return False

    def _get_log_csv_path(self):
        return self.log_csv_filepath

    def leer_logs_actual(self):
        """Relee LogApp.csv desde disco tal cual queda despues de
        _log_changes (mismo criterio de lectura que MainDataLoaderThread:
        dtype=str, keep_default_na=False, para no perder ceros/guiones ni
        convertir "NaN" a texto). Pensado para que los hilos de guardado
        (SaveExcelThread, etc.) lean el CSV ya actualizado en su propio hilo
        de fondo justo despues de escribir, y devuelvan el resultado a
        DataManager.set_logs_df() en el hilo principal -- mismo patron que
        ya usa RMJaviSyncWorker/SyncRMJaviDialog.handle_success. Devuelve
        DataFrame vacio si el archivo todavia no existe, o None si la
        lectura falla (para que el llamador no pise datos buenos con un
        error)."""
        csv_path = self._get_log_csv_path()
        if not csv_path or not os.path.exists(csv_path):
            return pd.DataFrame()
        try:
            return pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        except Exception as e:
            logger.error(f"No se pudo releer el historial (LogApp.csv) tras el guardado: {e}")
            return None

    def _log_changes(self, log_entries):
        # LogApp.csv (self.log_csv_filepath, ver config.settings.LOG_CSV_PATH)
        # es el unico historial oficial. Ya no depende de LOG_EXCEL_PATH salvo
        # para la migracion unica desde el .xlsx legado (migrar_historial_legacy).
        # Se anexa una linea por entrada; el costo no depende de cuantas filas
        # ya existen, a diferencia de reabrir y reescribir un .xlsx completo.
        if not log_entries: return
        if not self.log_csv_filepath:
            logger.warning("No se pudo registrar el historial: LOG_CSV_PATH no esta configurado.")
            return
        try:
            try:
                migrar_historial_legacy(self.log_filepath, self.log_csv_filepath)
            except Exception as e:
                logger.error(f"No se pudo migrar el historial legado antes de escribir: {e}")

            csv_path = self._get_log_csv_path()
            csv_existe = os.path.exists(csv_path)

            with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer_csv = csv.writer(f)
                if not csv_existe:
                    writer_csv.writerow(_HEADER_LOG_DEFAULT)
                for entry in log_entries:
                    writer_csv.writerow(entry)
        except Exception as e:
            print(f"Error escribiendo en logs: {e}")

    def _get_active_sheet(self, wb):
        if 'BBDD (2)' in wb.sheetnames:
            return wb['BBDD (2)']
        return wb.active

    def overwrite_dataframe(self, df, sheet_name, custom_filepath=None):
        if df is None or df.empty:
            return False
            
        target_file = custom_filepath or self.filepath
        
        dm = DataManager()
        dm.is_app_saving = True
        dm.save_timestamp = time.time()

        self._crear_backup(target_file)
        if not self.last_backup_ok:
            dm.is_app_saving = False
            logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
            return False

        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file = os.path.join(self.temp_dir, f"temp_overwrite_{uuid.uuid4().hex}.xlsx")

        try:
            shutil.copy2(target_file, temp_file)
            
            with pd.ExcelWriter(temp_file, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer_pd:
                df.to_excel(writer_pd, sheet_name=sheet_name, index=False)
                
            try:
                with open(temp_file, 'rb+') as f:
                    os.fsync(f.fileno())
            except Exception:
                pass
                
            shutil.copy2(temp_file, target_file)
            
            dm.save_timestamp = time.time()
            return True
            
        except PermissionError:
            print(f"El Excel {os.path.basename(target_file)} está bloqueado.")
            return False
        except Exception as e:
            print(f"Fallo inesperado al sobrescribir DataFrame: {e}")
            return False
        finally:
            dm.is_app_saving = False
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    @staticmethod
    def agregar_columna(sheet, nombre, header_map):
        """Escribe el encabezado `nombre` en la primera columna totalmente
        vacía a la derecha de los encabezados existentes (la hoja puede tener
        celdas auxiliares más a la derecha) y devuelve su índice."""
        idx = max(header_map.values(), default=0) + 1
        while any(sheet.cell(row=r, column=idx).value is not None for r in range(1, sheet.max_row + 1)):
            idx += 1
        celda = sheet.cell(row=1, column=idx)
        celda.value = nombre
        if idx > 1:
            celda._style = copy.copy(sheet.cell(row=1, column=idx - 1)._style)
        return idx

    def update_cells(self, changes_dict, module_name="Sistema", custom_filepath=None, sheet_name=None,
                     columnas_nuevas=None):
        """`columnas_nuevas`: encabezados que se agregan al final de la hoja si
        aún no existen (solo para archivos .xlsx)."""
        if not changes_dict: return True

        target_file = custom_filepath or self.filepath

        # Fase 1 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): si el
        # archivo objetivo es CSV, se delega al backend pandas -- mismo
        # contrato (True/False), mismo criterio de localizacion de fila,
        # mismo backup/log, pero SIN WorkbookCache (especifico de
        # openpyxl.Workbook). La rama .xlsx de abajo queda intacta.
        if target_file.lower().endswith('.csv'):
            return excel_writer_csv_backend.update_cells_csv(self, target_file, changes_dict, module_name)

        dm = DataManager()
        dm.is_app_saving = True
        dm.save_timestamp = time.time()

        self._crear_backup(target_file)
        if not self.last_backup_ok:
            dm.is_app_saving = False
            logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
            return False

        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file = os.path.join(self.temp_dir, f"temp_update_{uuid.uuid4().hex}.xlsx")

        cache = WorkbookCache.instancia()
        lock = cache.lock_para(target_file)
        lock.acquire()
        try:
            # WorkbookCache (piloto 22-09-2026, ver docs/12): reutiliza el
            # Workbook en memoria si sigue vigente (mismo mtime/tamaño que
            # cuando quedo cacheado tras el ultimo guardado exitoso),
            # evitando repetir el load_workbook() completo -- el costo
            # dominante medido (~7,2s de ~11,5s totales en PruebasFM.xlsx).
            # Si no hay entrada vigente (primer guardado de la sesion, o el
            # archivo cambio por fuera de la app), carga fresco igual que
            # antes.
            wb = cache.obtener_workbook(target_file)

            if sheet_name:
                if sheet_name in wb.sheetnames:
                    sheet = wb[sheet_name]
                else:
                    print(f"Error: La hoja '{sheet_name}' no existe en el archivo {os.path.basename(target_file)}.")
                    # No se muto nada todavia en este intento, pero se
                    # descarta igual: mas simple y seguro que distinguir
                    # caso por caso (prioridad: integridad > rendimiento).
                    cache.descartar(target_file)
                    return False
            else:
                sheet = self._get_active_sheet(wb)
            
            header_map = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value: 
                    header_map[str(cell.value).strip()] = col_idx

            for nombre_col in (columnas_nuevas or []):
                if nombre_col not in header_map:
                    header_map[nombre_col] = self.agregar_columna(sheet, nombre_col, header_map)

            logs_to_write = []
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            def normalize_fecha(val):
                if isinstance(val, datetime):
                    meses = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio', 
                             7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
                    return f"{val.year} - {meses.get(val.month, '')}"
                elif hasattr(val, 'strftime'): 
                    meses = {1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril', 5:'Mayo', 6:'Junio', 
                             7:'Julio', 8:'Agosto', 9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'}
                    return f"{val.year} - {meses.get(val.month, '')}"
                return str(val).strip() if val else ""

            for row_id, data in changes_dict.items():
                cambios = data.get('cambios', {})
                excel_row = None
                
                if 'keys' in data: 
                    for r_idx, row_cells in enumerate(sheet.iter_rows(min_row=2), start=2):
                        match = True
                        for k_col, k_val in data['keys'].items():
                            if k_col not in header_map:
                                match = False
                                break
                                
                            c_idx = header_map[k_col]
                            cell_val_raw = row_cells[c_idx-1].value
                            
                            if k_col == 'AÑO - MES':
                                cell_val = normalize_fecha(cell_val_raw).upper()
                                if str(k_val).strip().upper() not in cell_val:
                                    match = False
                                    break
                            else:
                                cell_val = str(cell_val_raw).strip() if cell_val_raw else ""
                                if cell_val.replace('.0', '') != str(k_val).strip().replace('.0', ''):
                                    match = False
                                    break
                        if match:
                            excel_row = r_idx
                            break
                    identificador_log = " | ".join(str(v) for v in data['keys'].values())
                else: 
                    target_vin = str(data.get('VIN')).strip()
                    vin_col_idx = header_map.get('VIN')
                    if vin_col_idx:
                        for r_idx, row_cells in enumerate(sheet.iter_rows(min_row=2, min_col=vin_col_idx, max_col=vin_col_idx), start=2):
                            if str(row_cells[0].value).strip() == target_vin:
                                excel_row = r_idx
                                break
                    identificador_log = target_vin

                if not excel_row:
                    print(f"No se encontró la fila objetivo para guardar: {identificador_log}")
                    # Iteraciones anteriores de este mismo changes_dict
                    # pueden haber mutado ya celdas del Workbook cacheado sin
                    # llegar a wb.save(). Descartar es obligatorio aqui: de
                    # lo contrario el siguiente guardado exitoso persistiria
                    # tambien esas mutaciones a medio hacer del intento
                    # fallido actual.
                    cache.descartar(target_file)
                    return False

                for col_name, new_value in cambios.items():
                    new_value = normalizar_para_escritura(col_name, new_value)
                    if col_name == 'TÉRMINO CONTRATO':
                        continue 

                    if col_name in header_map:
                        excel_col = header_map[col_name]
                        old_value_raw = sheet.cell(row=excel_row, column=excel_col).value
                        old_value = "" if old_value_raw is None else str(old_value_raw).strip()
                        
                        if old_value != str(new_value).strip():
                            sheet.cell(row=excel_row, column=excel_col).value = new_value
                            logs_to_write.append([current_time, module_name, identificador_log, col_name, old_value, str(new_value)])

            wb.save(temp_file)
            try:
                with open(temp_file, 'rb+') as f:
                    os.fsync(f.fileno())
            except Exception:
                pass
            # No se cierra el Workbook: sigue vivo en WorkbookCache para el
            # proximo guardado sobre esta misma ruta (wb.close() en modo
            # lectura/escritura normal de openpyxl es un no-op de todas
            # formas -- no libera nada que necesitemos mantener cerrado).

            shutil.copy2(temp_file, target_file)

            dm.save_timestamp = time.time()
            # Recien ahora, con el archivo real ya escrito, el Workbook en
            # memoria vuelve a coincidir con el disco: se actualiza el
            # fingerprint para que el proximo guardado lo reutilice.
            cache.actualizar_fingerprint(target_file)
            self._log_changes(logs_to_write)
            return True

        except PermissionError:
            print(f"El Excel {os.path.basename(target_file)} está bloqueado.")
            cache.descartar(target_file)
            return False
        except Exception as e:
            print(f"Fallo inesperado al guardar Excel: {e}")
            cache.descartar(target_file)
            return False
        finally:
            lock.release()
            dm.is_app_saving = False
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    def delete_row(self, primary_key_val=None, module_name="Sistema", custom_filepath=None, keys_dict=None):
        target_file = custom_filepath or self.filepath

        # Fase 1 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): ver
        # comentario equivalente en update_cells. RegistroEliminado.xlsx
        # (via self._log_deleted, llamado dentro de delete_row_csv) sigue
        # siendo .xlsx siempre, sin cambios.
        if target_file.lower().endswith('.csv'):
            return excel_writer_csv_backend.delete_row_csv(self, target_file, primary_key_val, module_name, keys_dict)

        dm = DataManager()
        dm.is_app_saving = True
        dm.save_timestamp = time.time()

        self._crear_backup(target_file)
        if not self.last_backup_ok:
            dm.is_app_saving = False
            logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
            return False

        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file = os.path.join(self.temp_dir, f"temp_delete_{uuid.uuid4().hex}.xlsx")

        cache = WorkbookCache.instancia()
        lock = cache.lock_para(target_file)
        lock.acquire()
        try:
            # Ver comentario equivalente en update_cells (WorkbookCache,
            # piloto 22-09-2026): reutiliza el Workbook en memoria si sigue
            # vigente, en vez de load_workbook() directo.
            wb = cache.obtener_workbook(target_file)
            sheet = self._get_active_sheet(wb)
            
            header_map = {}
            headers_list = []
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value:
                    col_name = str(cell.value).strip()
                    header_map[col_name] = col_idx
                    headers_list.append(col_name)

            row_to_delete = None
            row_data = []

            if keys_dict:
                for r_idx, row_cells in enumerate(sheet.iter_rows(min_row=2), start=2):
                    match = True
                    for k_col, k_val in keys_dict.items():
                        if k_col not in header_map:
                            match = False
                            break
                        c_idx = header_map[k_col]
                        cell_val = str(row_cells[c_idx-1].value).strip() if row_cells[c_idx-1].value else ""
                        if cell_val.replace('.0', '') != str(k_val).strip().replace('.0', ''):
                            match = False
                            break
                    if match:
                        row_to_delete = r_idx
                        row_data = [cell.value for cell in row_cells[:len(headers_list)]]
                        break
            else:
                vin_col = header_map.get('VIN')
                if vin_col:
                    for r_idx, row_cells in enumerate(sheet.iter_rows(min_row=2, min_col=vin_col, max_col=vin_col), start=2):
                        if str(row_cells[0].value).strip() == str(primary_key_val).strip():
                            row_to_delete = r_idx
                            row_data = [cell.value for cell in row_cells[:len(headers_list)]]
                            break

            if row_to_delete:
                self._log_deleted(headers_list, row_data, module_name)
                sheet.delete_rows(row_to_delete, 1)

                wb.save(temp_file)
                try:
                    with open(temp_file, 'rb+') as f:
                        os.fsync(f.fileno())
                except Exception:
                    pass
                # No se cierra: ver comentario equivalente en update_cells.

                shutil.copy2(temp_file, target_file)
                dm.save_timestamp = time.time()
                cache.actualizar_fingerprint(target_file)
                return True

            # No se encontro la fila a eliminar: no hubo mutacion (delete_rows
            # solo se llama dentro del if de arriba), pero se descarta igual
            # por el mismo criterio conservador que update_cells.
            cache.descartar(target_file)
            return False

        except PermissionError:
            print(f"El Excel {os.path.basename(target_file)} está bloqueado.")
            cache.descartar(target_file)
            return False
        except Exception as e:
            print(f"Fallo inesperado al eliminar fila en Excel: {e}")
            cache.descartar(target_file)
            return False
        finally:
            lock.release()
            dm.is_app_saving = False
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    @staticmethod
    def _siguiente_nombre_hoja_version(workbook, base_title):
        """Genera un nombre de hoja disponible del tipo 'Base (2)', 'Base (3)',
        respetando el limite de 31 caracteres de Excel. Se usa quando el
        esquema de origen cambio (columnas agregadas/quitadas/reordenadas)
        respecto a la hoja ya existente con ese module_name, para no
        desplazar ni corromper las filas historicas ya guardadas bajo el
        encabezado anterior."""
        n = 2
        while True:
            sufijo = f" ({n})"
            candidato = base_title[:31 - len(sufijo)] + sufijo
            if candidato not in workbook.sheetnames:
                return candidato
            n += 1

    @staticmethod
    def _hoja_version_con_encabezado(workbook, base_title, headers):
        """Hoja 'Base (n)' ya existente cuyo encabezado coincide con `headers`, o None."""
        esperado = list(headers)
        for nombre in workbook.sheetnames:
            m = re.fullmatch(r"(.*) \(\d+\)", nombre)
            if m and base_title.startswith(m.group(1)):
                ws = workbook[nombre]
                if [cell.value for cell in ws[1]][2:] == esperado:
                    return ws
        return None

    def _log_deleted(self, headers, row_data, module_name):
        self._log_deleted_lote(headers, [row_data], module_name)

    def _log_deleted_lote(self, headers, filas, module_name):
        """Registra varias filas eliminadas abriendo, respaldando y guardando
        RegistroEliminado.xlsx una sola vez."""
        if not filas:
            return
        try:
            workbook = None
            if os.path.exists(self.deleted_filepath):
                try:
                    workbook = openpyxl.load_workbook(self.deleted_filepath)
                except Exception as e:
                    # No destruir la papelera existente ante un fallo de
                    # lectura (ej. archivo bloqueado momentaneamente): se
                    # aborta el registro de esta eliminacion en vez de
                    # reemplazar RegistroEliminado.xlsx por uno nuevo vacio.
                    logger.error(
                        f"No se pudo leer '{os.path.basename(self.deleted_filepath)}' para registrar la "
                        f"eliminacion: {e}. Se aborta el registro; el archivo existente no se modifica."
                    )
                    return

            # sheet_title identifica el origen (module_name, ej. "Comercial",
            # "Contactos"): cada origen conserva su propia hoja con su propio
            # esquema de columnas. No se crea ningun esquema comun artificial
            # entre modulos ni se rellenan columnas inexistentes.
            sheet_title = str(module_name)[:31]

            if workbook is None:
                workbook = openpyxl.Workbook()
                ws = workbook.active
                ws.title = sheet_title
                ws.append(["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO"] + headers)
            else:
                if sheet_title in workbook.sheetnames:
                    ws = workbook[sheet_title]
                    encabezado_existente = [cell.value for cell in ws[1]][2:]
                    if encabezado_existente != list(headers):
                        # El Excel de origen de este modulo cambio su esquema
                        # (columnas agregadas/quitadas/reordenadas) desde la
                        # ultima eliminacion registrada aqui. Forzar el append
                        # bajo el encabezado viejo desplazaria los valores a
                        # columnas incorrectas. Se versiona la hoja en vez de
                        # tocar la existente: las filas historicas quedan
                        # intactas bajo su encabezado original. Si ya existe
                        # una version con este mismo esquema, se reutiliza
                        # (antes se creaba una hoja nueva por cada fila).
                        ws = self._hoja_version_con_encabezado(workbook, sheet_title, headers)
                        if ws is None:
                            sheet_title = self._siguiente_nombre_hoja_version(workbook, sheet_title)
                            logger.warning(
                                f"El esquema de '{module_name}' cambio respecto al registro previo en "
                                f"RegistroEliminado.xlsx. Se crea la hoja '{sheet_title}' con el esquema "
                                "actual; la hoja anterior no se modifica."
                            )
                            ws = workbook.create_sheet(title=sheet_title)
                            ws.append(["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO"] + headers)
                else:
                    ws = workbook.create_sheet(title=sheet_title)
                    ws.append(["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO"] + headers)

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for row_data in filas:
                ws.append([current_time, module_name] + list(row_data))

            self._crear_backup(self.deleted_filepath)
            workbook.save(self.deleted_filepath)
            workbook.close()
        except Exception as e:
            print(f"Error escribiendo log de eliminados: {e}")
            pass
            
    def add_new_row(self, new_data_dict, module_name="Sistema", custom_filepath=None):
        target_file = custom_filepath or self.filepath

        # Fase 1 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): ver
        # comentario equivalente en update_cells.
        if target_file.lower().endswith('.csv'):
            return excel_writer_csv_backend.add_new_row_csv(self, target_file, new_data_dict, module_name)

        dm = DataManager()
        dm.is_app_saving = True
        dm.save_timestamp = time.time()

        self._crear_backup(target_file)
        if not self.last_backup_ok:
            dm.is_app_saving = False
            logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
            return False

        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file = os.path.join(self.temp_dir, f"temp_add_{uuid.uuid4().hex}.xlsx")

        cache = WorkbookCache.instancia()
        lock = cache.lock_para(target_file)
        lock.acquire()
        try:
            # Ver comentario equivalente en update_cells (WorkbookCache,
            # piloto 22-09-2026).
            wb = cache.obtener_workbook(target_file)
            sheet = self._get_active_sheet(wb)

            header_map = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value: header_map[str(cell.value).strip()] = col_idx

            new_row_idx = sheet.max_row + 1
            logs_to_write = []
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # --- PRIORIDAD AL ID FÍSICO PERMANENTE COMO IDENTIFICADOR DEL LOG ---
            target_id = new_data_dict.get('ID', new_data_dict.get('VIN', new_data_dict.get('CDB', 'N/A')))

            for col_name, value in new_data_dict.items():
                value = normalizar_para_escritura(col_name, value)
                if col_name in header_map and value:
                    excel_col = header_map[col_name]
                    sheet.cell(row=new_row_idx, column=excel_col).value = value
                    logs_to_write.append([current_time, module_name, target_id, col_name, "NUEVO REGISTRO", str(value)])

            wb.save(temp_file)
            try:
                with open(temp_file, 'rb+') as f:
                    os.fsync(f.fileno())
            except Exception:
                pass
            # No se cierra: ver comentario equivalente en update_cells.

            shutil.copy2(temp_file, target_file)
            self._log_changes(logs_to_write)
            dm.save_timestamp = time.time()
            cache.actualizar_fingerprint(target_file)
            return True

        except PermissionError:
            print(f"El Excel {os.path.basename(target_file)} está bloqueado.")
            cache.descartar(target_file)
            return False
        except Exception as e:
            print(f"Fallo inesperado al añadir fila en Excel: {e}")
            cache.descartar(target_file)
            return False
        finally:
            lock.release()
            dm.is_app_saving = False
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    def add_new_rows_batch(self, new_data_dicts, module_name="Sistema", custom_filepath=None):
        """Igual que add_new_row, pero para insertar varias filas nuevas con
        una unica apertura/guardado del workbook (un solo backup, un solo
        log de auditoria). Pensada para importaciones en lote (ej. Power BI)
        donde escribir fila por fila seria lento y generaria N backups
        sucesivos. Mismo criterio de "todo o nada" que el resto de
        ExcelWriter: si algo falla, no se guarda ninguna fila del lote."""
        if not new_data_dicts:
            return True

        target_file = custom_filepath or self.filepath

        if target_file.lower().endswith('.csv'):
            return excel_writer_csv_backend.add_new_rows_batch_csv(self, target_file, new_data_dicts, module_name)

        dm = DataManager()
        dm.is_app_saving = True
        dm.save_timestamp = time.time()

        self._crear_backup(target_file)
        if not self.last_backup_ok:
            dm.is_app_saving = False
            logger.warning(f"Escritura abortada: no se pudo crear el backup previo de '{os.path.basename(target_file)}'.")
            return False

        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file = os.path.join(self.temp_dir, f"temp_add_batch_{uuid.uuid4().hex}.xlsx")

        try:
            shutil.copy2(target_file, temp_file)
            wb = openpyxl.load_workbook(temp_file)
            sheet = self._get_active_sheet(wb)

            header_map = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value: header_map[str(cell.value).strip()] = col_idx

            logs_to_write = []
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_row_idx = sheet.max_row + 1

            for new_data_dict in new_data_dicts:
                target_id = new_data_dict.get('ID', new_data_dict.get('VIN', new_data_dict.get('CDB', 'N/A')))
                for col_name, value in new_data_dict.items():
                    value = normalizar_para_escritura(col_name, value)
                    if col_name in header_map and value:
                        excel_col = header_map[col_name]
                        sheet.cell(row=new_row_idx, column=excel_col).value = value
                        logs_to_write.append([current_time, module_name, target_id, col_name, "NUEVO REGISTRO", str(value)])
                new_row_idx += 1

            wb.save(temp_file)
            try:
                with open(temp_file, 'rb+') as f:
                    os.fsync(f.fileno())
            except Exception:
                pass
            wb.close()

            shutil.copy2(temp_file, target_file)
            self._log_changes(logs_to_write)
            dm.save_timestamp = time.time()
            return True

        except PermissionError:
            print(f"El Excel {os.path.basename(target_file)} está bloqueado.")
            return False
        except Exception as e:
            print(f"Fallo inesperado al añadir el lote de filas en Excel: {e}")
            return False
        finally:
            dm.is_app_saving = False
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
