import calendar
import re
import pandas as pd
from datetime import datetime
import logging
import os
from src.core.constants import (
    TIPO_SERVICIO_MAP, FORMA_CONTRATO_MAP, ESTADO_COMERCIAL_MAP, ESTADO_DEL_CM_MAP,
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ, COL_TIPO_FACTURACION, COL_ETAPA_GESTION,
    COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, VALOR_TIPO_FACT_SIN_REGISTRO,
    VALOR_TIPO_FACT_FACTURACION_MANUAL, COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT,
    COL_ESTADO_ENTREGA,
)

# --- NUEVA CONFIGURACIÓN DE LOGS ---
if not os.path.exists("logs"):
    os.makedirs("logs")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/sistema.log", encoding='utf-8'), 
        logging.StreamHandler()                                    
    ]
)
logger = logging.getLogger(__name__)
# -----------------------------------

def _memoizar_por_valor(func):
    # Evalúa func una vez por valor distinto; la clave incluye el tipo para no mezclar 1, 1.0 y True.
    cache = {}
    def envoltura(valor):
        try:
            clave = (type(valor), valor)
            if clave in cache:
                return cache[clave]
        except TypeError:
            return func(valor)
        resultado = func(valor)
        cache[clave] = resultado
        return resultado
    return envoltura


def aplicar_por_fila_memoizado(df, func, columnas):
    """Equivale a df.apply(func, axis=1) cuando func solo lee `columnas` vía
    row.get(): evalúa func una vez por combinación distinta de esas columnas,
    sin construir un Series por fila (lo que dominaba el costo de clean())."""
    presentes = [c for c in columnas if c in df.columns]
    if not presentes:
        return pd.Series([func({}) for _ in range(len(df))], index=df.index)
    cache = {}
    resultados = []
    for fila in zip(*(df[c].tolist() for c in presentes)):
        clave = tuple((type(v), v) for v in fila)
        try:
            resultado = cache[clave]
        except KeyError:
            resultado = cache[clave] = func(dict(zip(presentes, fila)))
        except TypeError:
            resultado = func(dict(zip(presentes, fila)))
        resultados.append(resultado)
    return pd.Series(resultados, index=df.index)


class DataFrameFormatter:

    @staticmethod
    def _validate_columns(df):
        """
        Escudo protector: Verifica que las columnas mínimas vitales existan 
        antes de procesar el DataFrame.
        """
        columnas_vitales = ['VIN', 'CHASIS']
        columnas_faltantes = [col for col in columnas_vitales if col not in df.columns]
        
        if columnas_faltantes:
            error_msg = f"El archivo cargado es inválido o está corrupto.\nFaltan las siguientes columnas obligatorias:\n- {', '.join(columnas_faltantes)}"
            logger.error(error_msg.replace('\n', ' '))
            raise ValueError(error_msg)

    @staticmethod
    def parsear_fecha_segura(valor):
        """Interpreta un valor de fecha según su tipo/formato real, sin
        depender de pd.to_datetime(dayfirst=True) directo sobre un valor que
        ya viene en formato ISO: esa combinación intercambia día y mes
        cuando ambos son <=12 (bug confirmado con datos reales de
        RM_CONTRATOS/PruebasFM -- primero en INICIO CONTRATO/TÉRMINO CONTRATO al
        calcular, ~60% de los registros con duración numérica quedaban
        incorrectos; el mismo bug se replicó luego en
        comercial_services.clasificar_vigencia_contrato, 25-09-2026, donde
        fechas ISO con hora como "2026-02-12 04:00:00" -- 12 de febrero --
        se interpretaban como 2 de diciembre, dejando unidades ya vencidas
        fuera de Renovaciones/Vencidos/Bajas). Única fuente de verdad para
        este parseo: no reimplementar esta lógica en otro lado.

        Día de calendario inexistente en formato DD-MM-YYYY/DD/MM/YYYY (ej.
        "31-06-2026": junio tiene 30 días -- dato real encontrado en
        PruebasFM, 25-09-2026, a pedido explícito del usuario): se ajusta al
        último día real de ese mes/año (30-06-2026) en vez de devolver
        pd.NaT -- el mes y año sí son datos válidos, solo el día se pasó del
        límite del mes (error de digitación típico), así que se conserva el
        mes/año tal cual y se corrige solo el día.

        Devuelve un Timestamp o pd.NaT."""
        if isinstance(valor, (pd.Timestamp, datetime)):
            return pd.Timestamp(valor)

        texto = str(valor).strip()
        if not texto or texto.upper() in ['NAN', 'NAT', '<NA>']:
            return pd.NaT

        # Serial de Excel (dias desde 1899-12-30) - mismo criterio que antes.
        if texto.replace('.', '', 1).isdigit():
            return pd.to_datetime(float(texto), unit='D', origin='1899-12-30')

        # ISO inequivoco (YYYY-MM-DD, con o sin hora): NO es dayfirst.
        if len(texto) >= 10 and texto[4] == '-' and texto[7] == '-':
            try:
                return pd.to_datetime(texto[:10], format='%Y-%m-%d')
            except ValueError:
                pass

        # Formato de negocio DD-MM-YYYY (o DD/MM/YYYY): dayfirst=True es correcto aqui.
        # Se parsea a mano (no con pd.to_datetime) para poder detectar un día
        # de calendario inexistente y ajustarlo al último día real del mes,
        # en vez de que pd.to_datetime lo descarte silenciosamente como NaT.
        match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$', texto)
        if match:
            dia, mes, anio = (int(g) for g in match.groups())
            if 1 <= mes <= 12:
                ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
                dia_ajustado = min(dia, ultimo_dia_mes) if dia >= 1 else 1
                try:
                    return pd.Timestamp(year=anio, month=mes, day=dia_ajustado)
                except ValueError:
                    pass

        return pd.to_datetime(texto, dayfirst=True, errors='coerce')

    @staticmethod
    def calcular_etapa_gestion_esperada(row):
        """Única fuente de verdad de la regla de negocio ETAPA GESTIÓN.

        Prioridad 1 (reordenada 25-09-2026, a pedido explícito del usuario
        -- "la matriz de ESTADO COMERCIAL manda a todas las demás": (ESTADO
        COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) -> ETAPA GESTIÓN vía
        ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ, SIEMPRE que ambos ejes
        sean reconocidos por la matriz -- gana incluso sobre TIPO DE
        FACTURACION (antes tenía prioridad 1/2). Caso real que motivó el
        cambio: unidades enviadas a "Baja" desde Comercial que seguían
        Conectadas pero tenían TIPO DE FACTURACION=SIN REGISTRO nunca le
        llegaban a Operaciones para la desconexión física, porque la regla
        vieja las dejaba en COMERCIAL sin mirar su ESTADO DE ACTIVACIÓN
        ACTUAL real.

        Prioridad 2 (antes prioridad 1/2, ahora solo aplica cuando la
        matriz NO resuelve -- ESTADO COMERCIAL no está en la matriz, o
        ESTADO DE ACTIVACIÓN ACTUAL no es ninguno de sus valores conocidos
        para esa fila): TIPO DE FACTURACION contiene SIN REGISTRO, o es
        FACTURACIÓN MANUAL (definida con la contraparte comercial, 16-09-2026, para el flujo
        futuro de la app -- ver ComercialAgregarDialog) -> COMERCIAL.

        Prioridad 3 (fallback final, "no inventar"): se conserva el valor
        de ETAPA GESTIÓN que ya traía la fila. CLIENTE queda retirado del
        catálogo (21-09-2026): la matriz solo produce COMERCIAL u
        OPERACIONES.

        Usada tanto por clean() (recalculo real al cargar/sincronizar) como
        por comercial_services.detectar_contradicciones_etapa_gestion()
        (deteccion de filas cuyo valor actual no coincide con el esperado),
        para no duplicar la regla en dos lugares."""
        estado = str(row.get(COL_ESTADO_COMERCIAL, '')).strip().upper()
        activacion = str(row.get(COL_ESTADO_ACTIVACION, '')).strip().upper()
        etapa_actual = row.get(COL_ETAPA_GESTION, '')

        fila_matriz = ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ.get(estado)
        if fila_matriz is not None and activacion in fila_matriz:
            return fila_matriz[activacion]

        tipo_fact = str(row.get(COL_TIPO_FACTURACION, '')).strip().upper()
        if VALOR_TIPO_FACT_SIN_REGISTRO in tipo_fact:
            return 'COMERCIAL'
        if tipo_fact == VALOR_TIPO_FACT_FACTURACION_MANUAL:
            return 'COMERCIAL'

        return etapa_actual

    @staticmethod
    def calcular_etapa_gestion_df(df):
        """calcular_etapa_gestion_esperada sobre todo el DataFrame (mismo
        resultado que df.apply(..., axis=1), una evaluación por combinación)."""
        return aplicar_por_fila_memoizado(
            df, DataFrameFormatter.calcular_etapa_gestion_esperada,
            [COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION, COL_TIPO_FACTURACION])

    @staticmethod
    def clean(df):
        if df.empty: 
            logger.warning("El DataFrame recibido está vacío. Abortando limpieza.")
            return df
        
        logger.info(f"Iniciando limpieza del DataFrame. Filas totales: {len(df)}")

        # 1. Validar la estructura del Excel antes de tocar los datos
        DataFrameFormatter._validate_columns(df)

        if 'VIN' in df.columns:
            df['VIN'] = df['VIN'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        if 'CDB FLOTA' in df.columns:
            cdb_flota = df['CDB FLOTA']
            df['CDB FLOTA'] = cdb_flota.where(cdb_flota.isna(), cdb_flota.astype(str).str.strip()
                                              .str.replace(r'^(\d+)\.0$', r'\1', regex=True))

        float_cols = df.select_dtypes(include=['float64']).columns
        for col in float_cols:
            if col != 'VIN':
                df[col] = df[col].apply(lambda x: int(x) if pd.notnull(x) and x.is_integer() else x)

        date_columns = [
            'INICIO CONTRATO',
            'TÉRMINO CONTRATO',
            'FECHA DE BAJA',
            'FECHA INICIO CM',
            'FECHA TERMINO CM',
            # Corregido (25-09-2026): esta lista tenía los nombres de RM_CONTRATOS
            # ANTES del renombrado (RM_CONTRATOS_COLUMN_ALIASES en constants.py),
            # que nunca llegan a existir en el DataFrame que recibe clean()
            # -- para cuando RMReporteSyncWorker.run() llama a clean(), esas
            # columnas ya se renombraron a COL_FECHA_INICIO_FACT/
            # COL_FECHA_TERMINO_FACT ("INICIO"/"TERMINO"). Por eso nunca se
            # formateaban: llegaban tal cual las entrega pandas al leer una
            # celda de fecha de Excel (ej. "2022-04-22 00:00:00"). Se agrega
            # también COL_ESTADO_ENTREGA (ESTADO DE ENTREGA): pese al nombre,
            # es un campo de fecha (ver 'date' en comercial_agregar.py), con
            # el mismo origen y el mismo problema.
            COL_FECHA_INICIO_FACT,
            COL_FECHA_TERMINO_FACT,
            COL_ESTADO_ENTREGA,
        ]
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'^(nan|NaN|NaT|<NA>)$', '', regex=True, case=False).str.strip()

        # --- RECALCULO A PRUEBA DE BALAS (FORMATO CHILENO DD-MM-YYYY) ---
        if 'INICIO CONTRATO' in df.columns and 'DURACIÓN (MESES)' in df.columns and 'TÉRMINO CONTRATO' in df.columns:
            def calcular_termino(row):
                duracion_raw = str(row.get('DURACIÓN (MESES)', '')).strip().upper()
                inicio = row.get('INICIO CONTRATO')
                termino_manual = row.get('TÉRMINO CONTRATO')

                if not duracion_raw or duracion_raw in ['NAN', '']:
                    if pd.notna(termino_manual) and str(termino_manual).strip().upper() not in ['NAN', 'NAT', '']:
                        return termino_manual
                    return ""

                if duracion_raw == 'MENSUAL': return "MENSUAL"
                if duracion_raw == '-':
                    # '-' explicito en DURACIÓN (MESES) es mensual, EXCEPTO si
                    # TÉRMINO CONTRATO tambien es '-' explicito: ese combo
                    # ('-' / '-') significa que el dato aun no fue informado/
                    # gestionado (ej. VIN nuevo en RM_CONTRATOS), no que sea mensual.
                    # Cualquier otro TÉRMINO CONTRATO (fecha real, 'MENSUAL' o
                    # vacio) si confirma mensual, reemplazando lo que hubiera.
                    termino_previo = str(termino_manual).strip().upper() if pd.notna(termino_manual) else ''
                    if termino_previo == '-':
                        return "-"
                    return "MENSUAL"

                duracion_limpia = duracion_raw.replace(',', '.')

                try:
                    meses = int(float(duracion_limpia))
                    if not inicio or pd.isna(inicio) or str(inicio).strip().upper() in ['NAN', '']: return ""

                    inicio_dt = DataFrameFormatter.parsear_fecha_segura(inicio)

                    if pd.isna(inicio_dt): return ""
                    return (inicio_dt + pd.DateOffset(months=meses)).strftime("%d-%m-%Y")

                except ValueError:
                    return ""
                except Exception as e:
                    return ""

            df['TÉRMINO CONTRATO'] = aplicar_por_fila_memoizado(
                df, calcular_termino, ['DURACIÓN (MESES)', 'INICIO CONTRATO', 'TÉRMINO CONTRATO'])

        def format_date_fast(val):
            if pd.isna(val) or val == "": return ""
            if isinstance(val, (pd.Timestamp, datetime)): return val.strftime("%d-%m-%Y")
            
            if isinstance(val, str):
                texto = val.strip()
                texto_upper = texto.upper()
                if not texto or texto_upper in ["NAN", "NAT"]: return ""
                if texto_upper in ["MENSUAL", "-"]: return texto_upper
                
                # Formatos ya listos
                if len(texto) >= 10 and texto[2] == '-' and texto[5] == '-': return texto[:10]
                # Si viene con slashes (DD/MM/YYYY), cambiar a guiones (DD-MM-YYYY)
                if len(texto) >= 10 and texto[2] == '/' and texto[5] == '/': return texto[:10].replace('/', '-')
                
                # Si viene en YYYY-MM-DD
                if len(texto) >= 10 and texto[4] == '-' and texto[7] == '-':
                    try: 
                        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d-%m-%Y")
                    except Exception: 
                        pass

                if texto.replace('.', '', 1).isdigit():
                    try: 
                        return pd.to_datetime(float(texto), unit='D', origin='1899-12-30').strftime("%d-%m-%Y")
                    except Exception: 
                        pass
                
            if isinstance(val, (int, float)):
                try: 
                    return pd.to_datetime(val, unit='D', origin='1899-12-30').strftime("%d-%m-%Y")
                except Exception: 
                    pass

            try: 
                # Forzar dayfirst=True para que siempre entienda que el primer número es el día
                return pd.to_datetime(val, dayfirst=True, format='mixed').strftime("%d-%m-%Y")
            except Exception: 
                return str(val).strip()

        format_date_memo = _memoizar_por_valor(format_date_fast)
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].apply(format_date_memo)

        if 'DURACIÓN (MESES)' in df.columns and 'TÉRMINO CONTRATO' in df.columns:
            df['DURACIÓN (MESES)'] = df['DURACIÓN (MESES)'].astype(str).str.strip().str.upper()
            termino_actual = df['TÉRMINO CONTRATO'].astype(str).str.strip().str.upper()
            # 'MENSUAL' en DURACIÓN (MESES) siempre normaliza y fuerza mensual.
            # '-' en DURACIÓN (MESES) fuerza mensual SALVO que TÉRMINO CONTRATO ya
            # sea '-' (dato aun no informado, ver calcular_termino mas arriba):
            # en ese caso no se toca (calcular_termino ya dejo el valor correcto).
            mask_mensual_texto = df['DURACIÓN (MESES)'] == 'MENSUAL'
            mask_guion_informado = (df['DURACIÓN (MESES)'] == '-') & (termino_actual != '-')
            df.loc[mask_mensual_texto, 'DURACIÓN (MESES)'] = '-'
            df.loc[mask_mensual_texto | mask_guion_informado, 'TÉRMINO CONTRATO'] = 'MENSUAL'

        # Desactivado (30-09-2026, a pedido explícito): "PROVISION +" ya NO se
        # fuerza a mensual. RM_CONTRATOS siempre trae una fecha real de término
        # para estas filas (nunca 'Mensual'); esta regla la sobrescribía y
        # ocultaba contratos ya caducados. Ahora Provisión + sigue la regla
        # general de DURACIÓN/TÉRMINO de arriba, igual que el resto de los
        # valores de FORMA DE CONTRATO.

        # --- NORMALIZACIÓN ETL DE CATÁLOGOS COMERCIAL (mismo patrón que INDUSTRIA_MAP) ---
        def _mapear_categoria(val, mapa):
            if pd.isna(val):
                return val
            val_str = str(val).strip().upper()
            return mapa.get(val_str, val)  # si no está mapeado, se conserva sin modificar

        mapas_normalizacion = {
            'TIPO DE SERVICIO': TIPO_SERVICIO_MAP,
            'FORMA DE CONTRATO': FORMA_CONTRATO_MAP,
            'ESTADO COMERCIAL': ESTADO_COMERCIAL_MAP,
            'ESTADO DEL CM': ESTADO_DEL_CM_MAP,
            # CONTRATO CREADO EN JUSTTIME no se normaliza: se muestra como
            # viene y se corrige a mano desde la pantalla JustTime
        }
        for col, mapa in mapas_normalizacion.items():
            if col in df.columns:
                df[col] = df[col].apply(lambda v: _mapear_categoria(v, mapa))

        # --- CÁLCULO DE ETAPA GESTIÓN (única fuente de verdad, ejecutada tras
        # la normalización de ESTADO COMERCIAL de arriba) ---
        if COL_ETAPA_GESTION in df.columns:
            df[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_df(df)

        df = df.fillna("")
        logger.info("Limpieza del DataFrame finalizada con éxito.")
        return df