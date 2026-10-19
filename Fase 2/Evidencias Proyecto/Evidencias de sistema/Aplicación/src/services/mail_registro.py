import os
import csv
import uuid
import logging
import openpyxl
import pandas as pd
import config.settings

logger = logging.getLogger(__name__)

_COLUMNAS = ["id_envio", "fecha_hora", "tipo_correo", "razon_social", "chasis", "destinatario", "estado", "asunto"]


def construir_registro(id_envio, fecha_hora, tipo_correo, razon_social, chasis, destinatario, estado, asunto):
    """Arma un registro de historial con las claves de _COLUMNAS. Unica fuente
    de verdad del schema: quien registre un envio (ej. OutlookSenderThread en
    mail_dialog.py) no debe repetir los nombres de columna a mano."""
    return dict(zip(_COLUMNAS, [id_envio, fecha_hora, tipo_correo, razon_social, chasis, destinatario, estado, asunto]))


def _sharepoint_dir():
    excel_path = config.settings.EXCEL_PATH
    if excel_path and os.path.exists(os.path.dirname(excel_path)):
        return os.path.dirname(excel_path)
    return os.path.join(os.getcwd(), 'data')


def get_historial_legacy_path():
    """Ruta del .xlsx legado (nunca se modifica ni se borra desde aqui)."""
    return os.path.join(_sharepoint_dir(), 'Historial_Envios_VC.xlsx')


def get_historial_csv_path():
    """Ruta del historial oficial (append-only)."""
    return os.path.join(_sharepoint_dir(), 'Historial_Envios_VC.csv')


def migrar_historial_legacy():
    # Migracion unica e idempotente del historial legado
    # (Historial_Envios_VC.xlsx) al CSV oficial. No hace nada (devuelve
    # False) si el CSV ya existe o si no hay legado que migrar. El .xlsx
    # original nunca se modifica ni se borra: esta funcion solo lo lee.
    # Mismo patron que excel_writer.migrar_historial_legacy (LogApp.csv).
    csv_path = get_historial_csv_path()
    if os.path.exists(csv_path):
        return False

    legacy_path = get_historial_legacy_path()
    if not os.path.exists(legacy_path):
        return False

    try:
        wb = openpyxl.load_workbook(legacy_path, read_only=True)
        ws = wb.active
        filas_iter = ws.iter_rows(values_only=True)
        header = next(filas_iter, None) or list(_COLUMNAS)
        filas = []
        for row in filas_iter:
            if row is None or all(v is None for v in row):
                continue
            filas.append(["" if v is None else v for v in row])
        wb.close()
    except Exception as e:
        logger.error(f"Migracion del historial de correos abortada: no se pudo leer {os.path.basename(legacy_path)}: {e}")
        raise

    filas_esperadas = len(filas)
    tmp_path = csv_path + f".migrando_{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp_path, 'w', newline='', encoding='utf-8-sig') as f:
            escritor = csv.writer(f)
            escritor.writerow(header)
            for fila in filas:
                escritor.writerow(fila)

        with open(tmp_path, encoding='utf-8-sig') as f:
            filas_escritas = sum(1 for _ in f) - 1

        if filas_escritas != filas_esperadas:
            raise RuntimeError(
                f"Verificacion de migracion del historial de correos fallida: se esperaban {filas_esperadas} "
                f"filas y se escribieron {filas_escritas}. El CSV no fue creado; el .xlsx original permanece intacto."
            )

        os.replace(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

    logger.info(f"Historial de correos migrado a {os.path.basename(csv_path)}: {filas_esperadas} filas.")
    return True


def registrar_envios(historial_records):
    """Append-only: agrega los envios nuevos al CSV oficial sin releer ni
    reescribir el historial completo. Devuelve True/False segun si pudo
    escribir; nunca lanza excepcion (igual que ExcelWriter._log_changes)."""
    if not historial_records:
        return True
    try:
        try:
            migrar_historial_legacy()
        except Exception as e:
            logger.error(f"No se pudo migrar el historial de correos legado antes de registrar: {e}")

        csv_path = get_historial_csv_path()
        csv_existe = os.path.exists(csv_path)

        with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
            escritor = csv.writer(f)
            if not csv_existe:
                escritor.writerow(_COLUMNAS)
            for record in historial_records:
                escritor.writerow([record.get(col, "") for col in _COLUMNAS])
        return True
    except Exception as e:
        logger.error(f"No se pudo registrar el envio de correo en el historial: {e}")
        return False


def leer_historial():
    """Devuelve el historial completo como DataFrame (columnas como texto,
    mismo criterio que el historial de modificaciones)."""
    try:
        migrar_historial_legacy()
    except Exception as e:
        logger.error(f"No se pudo migrar el historial de correos legado antes de leer: {e}")

    csv_path = get_historial_csv_path()
    if not os.path.exists(csv_path):
        return pd.DataFrame(columns=_COLUMNAS)
    try:
        return pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception as e:
        logger.error(f"No se pudo leer el historial de correos: {e}")
        return pd.DataFrame(columns=_COLUMNAS)
