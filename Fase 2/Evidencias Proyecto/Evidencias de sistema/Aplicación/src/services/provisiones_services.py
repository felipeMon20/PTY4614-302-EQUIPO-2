"""Logica de negocio de Provisiones extraida de src/ui/provisiones.py (ver
auditoria previa). Python/pandas puro: no depende de PyQt6, QThread,
QWidget, QMessageBox ni ningun widget.

No incluye la logica de TÉRMINO CONTRATO (relativedelta) que SaveProvisionesThread
usa al sincronizar con Comercial: esa cuenta esta deliberadamente fuera de
alcance (ver auditoria) porque duplica DataFrameFormatter.calcular_termino(),
que no debe tocarse en esta tarea."""

import re
from datetime import datetime

import pandas as pd

from src.core.constants import INDUSTRIA_MAP
from src.services import catalogos_service


def formatear_moneda(valor):
    """Extraccion literal de la formula de formato monetario repetida en
    ProvisionesModule.on_item_edited() (rama DYNAFLEET, fallback de error,
    format_money local) y en filter_table(): reproduce exactamente
    `f"$-" if v==0 else f"{'-' if v<0 else ''}${int(abs(v)+0.5):,}".replace(",", ".")`."""
    return f"$-" if valor == 0 else f"{'-' if valor < 0 else ''}${int(abs(valor) + 0.5):,}".replace(",", ".")


def validar_cantidad_meses(valor):
    """Extraccion literal de la validacion de 'Cantidad de Meses' en
    ProvisionesModule.on_item_edited(). No muestra mensajes ni toca ninguna
    celda; devuelve una tupla (resultado, valor_o_mensaje):
      - ("vacio", ""): valor vacio o 'nan'; provisiones.py debe guardar ""
        en pending_changes sin tocar la celda.
      - ("mensual", "-"): valor '-' o 'MENSUAL' (case-insensitive);
        provisiones.py debe fijar 'Cantidad de Meses'='-' y escribirlo en
        la celda.
      - ("numerico", "24"): numero > 0, normalizado a entero string;
        provisiones.py debe guardarlo tal cual en pending_changes.
      - ("invalido", mensaje): provisiones.py debe mostrar `mensaje` en un
        QMessageBox.warning, revertir la celda a "" y no guardar el cambio.
    """
    val_limpio = str(valor).strip()
    if val_limpio == "" or val_limpio.upper() == 'NAN':
        return "vacio", ""
    if val_limpio == '-' or val_limpio.upper() == 'MENSUAL':
        return "mensual", "-"
    if val_limpio.replace('.', '', 1).isdigit() and float(val_limpio) > 0:
        return "numerico", str(int(float(val_limpio)))
    return "invalido", "La cantidad debe ser un número mayor a 0, o un guion '-'."


def parsear_dynafleet(valor):
    """Extraccion literal del parseo de DYNAFLEET en
    ProvisionesModule.on_item_edited(): quita '$', '.' y ',' y convierte a
    float (vacio o '-' -> 0.0, mismo criterio de 'sin valor' que el resto de
    la app). No conoce self.df_base ni el fallback al valor anterior: eso
    permanece en provisiones.py. Devuelve una tupla (resultado, dato):
      - ("valido", {"num": 500000.0, "formato": "$500.000"}): provisiones.py
        debe guardar `num` en pending_changes y `formato` en la celda.
      - ("invalido", None): provisiones.py debe mostrar QMessageBox.warning,
        buscar el valor anterior en self.df_base y formatearlo con
        formatear_moneda().
    """
    val_limpio = str(valor).replace('$', '').replace('.', '').replace(',', '').strip()
    if val_limpio == '-':
        val_limpio = ''
    try:
        val_num = float(val_limpio) if val_limpio else 0.0
    except ValueError:
        return "invalido", None
    return "valido", {"num": val_num, "formato": formatear_moneda(val_num)}


def calcular_montos_provision(val_dynafleet, val_meses, nombre_plan, planes_data, uf):
    """Extraccion literal del bloque de calculo en vivo de
    ProvisionesModule.on_item_edited() ('Monto Provisionado' / 'Valor Plan' /
    'VAR'). No lee celdas Qt: `val_dynafleet`, `val_meses` y `nombre_plan` ya
    deben venir resueltos desde provisiones.py (considerando la celda recien
    editada, igual que el original). Devuelve (monto_prov, valor_plan_exacto,
    variacion)."""
    dict_exact_clp = {p['nombre']: p['uf_mult'] * uf for p in planes_data}

    if val_meses == 0:
        val_meses = 1.0

    monto_prov = val_dynafleet / val_meses
    valor_plan_exacto = dict_exact_clp.get(nombre_plan, 0.0)
    variacion = monto_prov - valor_plan_exacto

    return monto_prov, valor_plan_exacto, variacion


def limpiar_cantidad_meses_display(val):
    """Extraccion literal de clean_meses_ui(), la funcion anidada que
    ProvisionesModule.load_data() aplica a la columna 'Cantidad de Meses'
    antes de mostrarla en la tabla."""
    if pd.isna(val) or str(val).strip() in ['', 'nan', 'NaN', '<NA>', 'None']:
        return ""
    val_str = str(val).strip().upper()
    if val_str in ['-', 'MENSUAL']:
        return val_str
    try:
        return str(int(round(float(val))))
    except (ValueError, TypeError):
        return val_str


def construir_cambios_provisiones(pending_data):
    """Extraccion literal del primer bucle de SaveProvisionesThread.run():
    normaliza VIN/AÑO - MES de cada entrada de `pending_data` al formato que
    espera ExcelWriter.update_cells (clave 'keys' + 'cambios')."""
    provisiones_changes = {}
    for key, data in pending_data.items():
        target_vin = str(data['VIN']).strip().upper()
        target_fecha = str(data['AÑO - MES']).strip()

        provisiones_changes[key] = {
            'keys': {'VIN': target_vin, 'AÑO - MES': target_fecha},
            'cambios': data['cambios']
        }
    return provisiones_changes


def convertir_periodo_interno(target_fecha):
    """Extraccion literal del calculo de PERIODO INTERNO dentro del bucle de
    cross_updates de SaveProvisionesThread.run(): invierte 'AÑO - MES' /
    'MES - AÑO' segun cual de las dos partes sea el año (4 digitos). Si el
    formato no calza, devuelve `target_fecha` sin modificar."""
    periodo_interno_val = target_fecha
    if "-" in target_fecha:
        partes = [p.strip() for p in target_fecha.split("-")]
        if len(partes) == 2:
            if partes[0].isdigit() and len(partes[0]) == 4:
                periodo_interno_val = f"{partes[1]} - {partes[0]}"
            elif partes[1].isdigit() and len(partes[1]) == 4:
                periodo_interno_val = f"{partes[0]} - {partes[1]}"
    return periodo_interno_val


MESES_MINUSCULA = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio', 7: 'julio',
                   8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'}


def periodo_interno_desde_provision(target_fecha):
    """PERIODO INTERNO que recibe PruebasFM desde Provisiones: el mes siguiente
    al de la provisión, con el formato del RM. '2026 - Septiembre' -> 'octubre -
    2026'. Si el texto no se puede interpretar, queda el mismo valor."""
    anio, mes = _partes_periodo(target_fecha)
    if not anio or not mes:
        return str(target_fecha)
    if mes == 12:
        anio, mes = anio + 1, 1
    else:
        mes += 1
    return f"{MESES_MINUSCULA[mes]} - {anio}"


def periodo_interno_del_mes(hoy=None):
    """PERIODO INTERNO del mes en curso, con el formato del RM: 'noviembre - 2026'."""
    hoy = hoy or datetime.now()
    return f"{MESES_MINUSCULA[hoy.month]} - {hoy.year}"


COL_ID_CONTRATO_PROV = 'ID CONTRATO'


def resolver_destino_provision(df_actuales, vin, id_prov=''):
    """A qué contrato de PruebasFM llegan los cambios de una provisión.
    Devuelve {'estado', 'id', 'fila'}; 'estado' es uno de:
    - 'huerfano': el VIN no existe en PruebasFM.
    - 'historica': la provisión quedó ligada a otro contrato (ID CONTRATO) que
      ya no es el actual; no se toca nada.
    - 'cerrado': el contrato actual está en Baja o Baja Solicitada.
    - 'sin_contrato': unidad que llegó con el reporte de Notas de Venta y aún no
      tiene contrato (forma Sin Contrato, estado Sin Servicio, activación No
      aplica): al provisionarse pasa a Provision (ver cambios_pasar_a_provision).
    - 'no_provision': el contrato actual no es de forma Provision (Provision +
      es otro tipo de contrato).
    - 'ok': contrato abierto de forma Provision; recibe los cambios."""
    from src.services.comercial_services import es_contrato_cerrado, _normalizar_id_contrato
    vacio = {'estado': 'huerfano', 'id': '', 'fila': {}}
    if df_actuales is None or not isinstance(df_actuales, pd.DataFrame) or df_actuales.empty \
            or 'VIN' not in df_actuales.columns:
        return vacio
    vin = str(vin).strip().upper()
    coincide = df_actuales[df_actuales['VIN'].astype(str).str.strip().str.upper() == vin]
    if coincide.empty:
        return vacio

    fila = coincide.iloc[-1].to_dict()
    id_actual = _normalizar_id_contrato(fila.get('ID', ''))
    resultado = {'estado': 'ok', 'id': id_actual, 'fila': fila}
    id_prov = _normalizar_id_contrato(id_prov)
    if id_prov and id_actual and id_prov != id_actual:
        resultado['estado'] = 'historica'
    elif es_contrato_cerrado(fila.get('ESTADO COMERCIAL', '')):
        resultado['estado'] = 'cerrado'
    elif es_unidad_sin_contrato(fila):
        resultado['estado'] = 'sin_contrato'
    elif str(fila.get('FORMA DE CONTRATO', '')).strip().upper() != 'PROVISION':
        resultado['estado'] = 'no_provision'
    return resultado


def es_unidad_sin_contrato(fila):
    """Unidad pendiente de enviar a Operaciones: forma Sin Contrato o Provision, estado Sin Servicio o
    Revisar y activación No aplica, como queda al cargar el reporte de Notas de Venta (y después de
    guardar su provisión, que no cambia el estado)."""
    def texto(columna):
        return str(fila.get(columna, '')).strip().upper()

    return (texto('FORMA DE CONTRATO') in ('SIN CONTRATO', 'PROVISION')
            and texto('ESTADO COMERCIAL') in ('SIN SERVICIO', 'REVISAR')
            and texto('ESTADO DE ACTIVACIÓN ACTUAL') == 'NO APLICA')


ACTIVIDAD_PENDIENTE, ACTIVIDAD_ENVIADO, ACTIVIDAD_BAJA, ACTIVIDAD_NO_APLICA = "Pendiente", "Enviado", "Baja", "No aplica"
ACTIVIDAD_SIN_COMERCIAL = "Sin Comercial"


def mapa_actividad(df_actuales):
    """{VIN: (actividad, enviable)} de los contratos actuales. Pendiente: sin enviar a Operaciones; Enviado:
    ya pasó; Baja: contrato cerrado. `enviable` es True solo si además ya tiene forma Provision (su provisión
    está guardada), que es cuando se activa el botón Enviar a Operaciones."""
    from src.services.comercial_services import es_contrato_cerrado
    if df_actuales is None or not isinstance(df_actuales, pd.DataFrame) or df_actuales.empty \
            or 'VIN' not in df_actuales.columns:
        return {}

    def col(nombre):
        if nombre not in df_actuales.columns:
            return pd.Series('', index=df_actuales.index)
        return df_actuales[nombre].astype(str).str.strip().str.upper()

    estado, activacion, forma = col('ESTADO COMERCIAL'), col('ESTADO DE ACTIVACIÓN ACTUAL'), col('FORMA DE CONTRATO')
    pendiente = estado.isin(('SIN SERVICIO', 'REVISAR')) & (activacion == 'NO APLICA') & forma.isin(('SIN CONTRATO', 'PROVISION'))
    cerrado = df_actuales['ESTADO COMERCIAL'].map(es_contrato_cerrado) if 'ESTADO COMERCIAL' in df_actuales.columns \
        else pd.Series(False, index=df_actuales.index)
    actividad = pd.Series(ACTIVIDAD_ENVIADO, index=df_actuales.index, dtype=object)
    actividad[cerrado.astype(bool)] = ACTIVIDAD_BAJA
    actividad[pendiente] = ACTIVIDAD_PENDIENTE
    enviable = pendiente & (forma == 'PROVISION')
    vins = df_actuales['VIN'].astype(str).str.strip().str.upper()
    return dict(zip(vins, zip(actividad, enviable)))


def es_observacion_solo_cm(texto):
    """Observación de un contrato Blue, Gold o Silver sin tramo de Volvo Connect:
    es de CM y no se cruza al Registro Maestro."""
    limpio = str(texto or '').upper()
    return bool(re.search(r'CONTRATO|BLUE|GOLD|SILVER', limpio)) and interpretar_observacion(limpio)[0] is None


OPCIONES_FORMA = ["Provision", "Provision +", "CMB", "CMG", "CMS", "Sin Contrato"]


def facturaciones_de_forma(forma):
    """Tipos de facturación válidos para la forma de contrato (matriz de negocio), con su valor real."""
    from src.core.constants import FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
    return sorted(FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(str(forma).strip().upper(), set()))


def forma_sugerida(observacion):
    """(forma de contrato, tipo de facturación) que se propone según la observación: Provision/Interno si
    trae un plan de Volvo Connect, CMG/CMB/CMS con facturación CM para los contratos Gold, Blue y Silver, y
    Sin Contrato/Sin registro en los demás casos. La persona puede cambiarla antes de guardar."""
    if interpretar_observacion(observacion)[0]:
        return 'Provision', 'INTERNO'
    limpio = str(observacion or '').upper()
    for palabra, forma in (('GOLD', 'CMG'), ('BLUE', 'CMB'), ('SILVER', 'CMS')):
        if palabra in limpio:
            return forma, 'CM'
    return 'Sin Contrato', 'SIN REGISTRO'


def cambios_guardar_provision(plan, cantidad_meses, forma='Provision', facturacion=None):
    """Lo que recibe el Registro Maestro al guardar la provisión de una unidad pendiente, según la forma de
    contrato y la facturación elegidas. Provision y Provision +: forma, facturación, tipo de servicio según
    el plan (si está en el catálogo) y duración. CMB, CMG y CMS: forma, facturación CM y su tipo de CM. Sin
    Contrato no cambia nada. El estado comercial y la activación no cambian: la unidad pasa a Operaciones
    solo al enviarla."""
    from src.core.constants import FORMA_CONTRATO_TIPO_CM_MAP
    clave = str(forma).strip().upper()
    if clave == 'SIN CONTRATO':
        return {}
    facturacion = facturacion or (facturaciones_de_forma(forma) or [''])[0]
    cambios = {'FORMA DE CONTRATO': forma, 'TIPO DE FACTURACION': facturacion}
    if clave in FORMA_CONTRATO_TIPO_CM_MAP:
        cambios['TIPO DE CM'] = FORMA_CONTRATO_TIPO_CM_MAP[clave]
        return cambios
    meses = str(cantidad_meses).strip()
    cambios['DURACIÓN (MESES)'] = '-' if meses.upper() in ('', '-', 'MENSUAL', 'NAN') else meses
    servicio = mapear_tipo_servicio_desde_plan(plan)
    if servicio != '-':
        cambios['TIPO DE SERVICIO'] = servicio
    return cambios


def cambios_enviar_a_operaciones(fila, hoy=None):
    """Lo que deja una unidad pendiente al enviarla a Operaciones: Activación Pendiente y Activando (queda en
    Activaciones), su etapa, el inicio del contrato y el inicio y término de JustTime desde el día 1 del mes
    actual (mismo criterio que calcular_fechas_justtime), y el periodo interno del mes si decía No aplica."""
    from src.core.constants import (COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_TIPO_FACTURACION, COL_ETAPA_GESTION,
                                    VALOR_TIPO_FACT_INTERNO)
    from src.core.dataframe_formatter import DataFrameFormatter

    estado_comercial, estado_activacion = 'Activación Pendiente', 'Activando'
    facturacion = str(fila.get('TIPO DE FACTURACION', '')).strip() or VALOR_TIPO_FACT_INTERNO
    etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: estado_comercial, COL_ESTADO_ACTIVACION: estado_activacion,
        COL_TIPO_FACTURACION: facturacion, COL_ETAPA_GESTION: '',
    })
    inicio, termino = calcular_fechas_justtime(fila.get('DURACIÓN (MESES)', ''), hoy=hoy)
    cambios = {
        'ESTADO COMERCIAL': estado_comercial, 'ESTADO DE ACTIVACIÓN ACTUAL': estado_activacion,
        'ETAPA GESTIÓN': etapa, 'INICIO CONTRATO': inicio,
        'CONTRATO CREADO EN JUSTTIME': 'Pendiente', 'INICIO': inicio, 'TERMINO': termino,
    }
    if str(fila.get('PERIODO INTERNO', '')).strip().upper() in ('', '-', 'NO APLICA', 'NAN'):
        cambios['PERIODO INTERNO'] = periodo_interno_del_mes(hoy)
    return cambios


def parsear_numero_uf(texto):
    """Extraccion literal del parseo numerico repetido en
    CostosDialog.save_and_close() (UF, CIV y multiplicador de cada plan):
    reemplaza ',' por '.' y convierte a float. Deja propagar ValueError tal
    como el original, para que save_and_close lo siga capturando con su
    `except ValueError`."""
    return float(texto.replace(',', '.'))


def escribir_uf_en_variables(ruta, uf):
    """Escribe el valor de UF en la hoja Variables del Excel de provisiones.
    False si el archivo no tiene esa hoja o la fila UF."""
    import openpyxl
    wb = openpyxl.load_workbook(ruta)
    try:
        if "Variables" not in wb.sheetnames:
            return False
        hoja = wb["Variables"]
        for fila in range(1, 10):
            if str(hoja.cell(row=fila, column=1).value).strip().upper() == "UF":
                hoja.cell(row=fila, column=2).value = float(uf)
                wb.save(ruta)
                return True
        return False
    finally:
        wb.close()


def escribir_variables_en_hoja(hoja, valores):
    """Actualiza en la hoja Variables el valor de cada variable de `valores` ({'UF': 38000, 'CIV': 0.05, 'SZ': 0}).
    Una variable sin fila (por ejemplo un complemento nuevo) se agrega al final solo si su valor es distinto de 0."""
    filas = {}
    ultima = 0
    for fila in range(1, max(hoja.max_row, 10) + 1):
        nombre = hoja.cell(row=fila, column=1).value
        if nombre is not None and str(nombre).strip():
            filas[str(nombre).strip().upper()] = fila
            ultima = fila
    for nombre, valor in valores.items():
        fila = filas.get(str(nombre).upper())
        if fila is None:
            if not valor:
                continue
            ultima += 1
            fila = ultima
            hoja.cell(row=fila, column=1).value = nombre
        hoja.cell(row=fila, column=2).value = float(valor)


def escribir_plan_en_planes(ruta, nombre, multiplicador):
    """Agrega o actualiza un plan en la hoja Planes del Excel de provisiones, junto con su variante
    "+ CIV" (en 0: el cargador la calcula como plan base + valor del CIV). False si no hay hoja Planes."""
    import openpyxl
    wb = openpyxl.load_workbook(ruta)
    try:
        if "Planes" not in wb.sheetnames:
            return False
        hoja = wb["Planes"]
        ultima = 1
        filas = {}
        for fila in range(1, hoja.max_row + 1):
            valor = hoja.cell(row=fila, column=1).value
            if valor is not None and str(valor).strip():
                filas[str(valor).strip().upper()] = fila
                ultima = fila
        for plan, valor in ((nombre, float(multiplicador)), (f"{nombre} + CIV", None)):
            fila = filas.get(plan.upper())
            if fila is None:
                ultima += 1
                fila = ultima
                hoja.cell(row=fila, column=1).value = plan
                hoja.cell(row=fila, column=2).value = 0 if valor is None else valor
            elif valor is not None:
                hoja.cell(row=fila, column=2).value = valor
        wb.save(ruta)
        return True
    finally:
        wb.close()


def mapear_industria(industria_raw, registrar=False):
    """Normaliza a mayusculas, colapsa los valores vacios/nulos conocidos a
    'NO DEFINIDA' y traduce con las traducciones del equipo (Administración >
    Catálogos) o INDUSTRIA_MAP. Con `registrar=True`, un texto sin traducción
    queda anotado como pendiente. Reutilizada por powerbi_import_service.py
    (import de Power BI, independiente de Provisiones)."""
    industria_raw = str(industria_raw).strip().upper()
    if industria_raw in ['NAN', 'NONE', '<NA>', '', '-', '0', '0.0']:
        return "NO DEFINIDA"
    try:
        propia = catalogos_service.traducir_industria(industria_raw)
    except Exception:
        propia = None
    if propia:
        return propia
    if industria_raw in INDUSTRIA_MAP:
        return INDUSTRIA_MAP[industria_raw]
    if registrar:
        try:
            catalogos_service.anotar_pendiente(industria_raw)
        except Exception:
            pass
    return industria_raw


# =========================================================
# VINCULACIÓN DIRECTA CON COMERCIAL (RM): único camino para VIN huérfanos de
# Provisiones (30-09-2026, a pedido explícito -- reemplaza por completo al
# ex "Rescate de Contratos Huérfanos" vía Reporte de Notas de Venta/Power BI,
# eliminado). Busca el 'CLIENTE' de Provisiones directamente contra la Razón
# Social ya existente en Comercial.
# =========================================================
def normalizar_cliente(texto):
    """Normaliza texto libre (CLIENTE de Provisiones / RAZÓN SOCIAL de
    Comercial) para matching: mayúsculas, sin espacios sobrantes al
    inicio/fin ni dobles espacios internos. No quita tildes: no existe hoy
    en el proyecto ninguna normalización de acentos reutilizable (sin
    unidecode/unicodedata en ningún archivo), así que no se agrega
    infraestructura nueva solo para esto."""
    if texto is None:
        return ''
    return re.sub(r'\s+', ' ', str(texto).strip().upper())


def construir_lookup_razon_social(df_comercial):
    """Agrupa Comercial por RAZÓN SOCIAL normalizada, preservando las
    combinaciones reales de RUT/CDB/EJECUTIVO tal como existen en los datos
    (nunca cruza valores sueltos entre sí, a diferencia de un lookup por
    sets independientes). Mismo criterio de fondo que
    _ComercialUnidadFormMixin._construir_lookups (comercial_agregar.py),
    pero en sentido inverso (clave = Razón Social, no RUT) -- ese sentido no
    existe hoy en ningún lugar del proyecto."""
    lookup = {}
    cols = ['RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO']
    if df_comercial is None or not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty \
            or 'RAZÓN SOCIAL' not in df_comercial.columns:
        return lookup

    df_aux = pd.DataFrame({c: (df_comercial[c] if c in df_comercial.columns else "") for c in cols})
    df_aux = df_aux.fillna("").astype(str).apply(lambda s: s.str.strip())
    df_aux = df_aux[df_aux['RAZÓN SOCIAL'] != ""]
    df_aux['_CLAVE'] = df_aux['RAZÓN SOCIAL'].apply(normalizar_cliente)

    for clave, grupo in df_aux.groupby('_CLAVE'):
        lookup[clave] = grupo[cols].drop_duplicates().to_dict('records')
    return lookup


def buscar_candidatos_por_cliente(df_comercial, cliente, lookup=None):
    """Candidatos de Comercial para el 'CLIENTE' de Provisiones: primero
    coincidencia EXACTA (normalizada); si no hay ninguna, coincidencia por
    contención de texto (sin librería de fuzzy matching, para no generar
    coincidencias agresivas -- se exige un mínimo de 4 caracteres
    normalizados para evitar falsos positivos con textos muy cortos).
    Devuelve una lista de combinaciones reales {RAZÓN SOCIAL, RUT, CDB,
    EJECUTIVO} (nunca un único valor "elegido": la ambigüedad de RUT/CDB
    queda para que la UI la resuelva mostrándole las opciones al usuario)."""
    clave_cliente = normalizar_cliente(cliente)
    if not clave_cliente:
        return []

    if lookup is None:
        lookup = construir_lookup_razon_social(df_comercial)
    if clave_cliente in lookup:
        return lookup[clave_cliente]

    if len(clave_cliente) < 4:
        return []

    candidatos = []
    for clave, combos in lookup.items():
        if clave_cliente in clave or clave in clave_cliente:
            candidatos.extend(combos)
    return candidatos


def mapear_tipo_servicio_desde_plan(plan):
    """TIPO DE SERVICIO de una unidad nueva creada desde Provisiones: copia
    directa de 'Plan' si es un plan base del catálogo (Administración >
    Catálogos) con o sin sus complementos (salvo mayúsculas/minúsculas); si
    no coincide (ej. el placeholder '0' o vacío) queda '-' para revisión
    manual -- decisión confirmada con el usuario, no se inventa un mapeo."""
    plan_norm = str(plan).strip()
    if not plan_norm:
        return '-'
    base, complementos = catalogos_service.partir_tipo_servicio(plan_norm)
    for canonico in catalogos_service.planes_base():
        if canonico.upper() == base.upper():
            return catalogos_service.armar_tipo_servicio(canonico, complementos)
    return '-'


_PLANES_OBSERVACION = {'BASICO': 'Basico', 'MEDIO': 'Medio', 'FULL': 'Full'}
_TRAMO_VOLVO_CONNECT = re.compile(
    r'VOLVO CONNECT\s+(BASICO|MEDIO|FULL)\s*(\+\s*CIV)?\s*(\d{1,3})\s*(MESES|MES|M|AÑOS|AÑO|ANOS|ANO)\b')
_TRAMO_SIN_PREFIJO = re.compile(r'\b(BASICO|MEDIO|FULL)\s*(\+\s*CIV)?\s*(\d{1,3})\s*(MESES|MES|M|AÑOS|AÑO)\b')


def interpretar_observacion(texto):
    """Plan y cantidad de meses de una observación como 'Provisión Volvo
    Connect Medio + CIV 3 meses (5 años)' o 'Volvo Connect Full 12 MESES /
    Contrato Blue 24 MESES'. Solo cuenta el tramo 'Volvo Connect <plan> <N>';
    los contratos Blue/Gold y el '(5 años)' son otra cosa. Devuelve (plan o
    None, meses como str o None); es una sugerencia para completar registros
    vacíos y el usuario puede corregirla."""
    limpio = re.sub(r'\s+', ' ', str(texto or '')).strip().upper()
    if not limpio or limpio in ('-', 'NAN', 'NONE'):
        return None, None
    encontrado = _TRAMO_VOLVO_CONNECT.search(limpio)
    if encontrado is None and not re.search(r'CONTRATO|BLUE|GOLD|SILVER', limpio):
        encontrado = _TRAMO_SIN_PREFIJO.search(limpio)
    if encontrado is None:
        return None, None
    base, civ, cantidad, unidad = encontrado.groups()
    plan = _PLANES_OBSERVACION[base]
    resto = limpio[encontrado.end():]
    if civ or re.search(r'VOLVO CONNECT\s*\+\s*CIV', resto):
        plan += " + CIV"
    meses = int(cantidad) * (12 if unidad.startswith(('AÑ', 'AN')) else 1)
    # "(5 años)" entre paréntesis es el plazo del contrato: manda sobre los
    # meses del tramo (ej. "Medio + CIV 3 meses (5 años)" se provisiona a 60)
    plazo = re.search(r'\(\s*(\d{1,2})\s*A[ÑN]OS?\s*\)', resto)
    if plazo and int(plazo.group(1)) > 0:
        meses = int(plazo.group(1)) * 12
    return plan, str(meses) if meses > 0 else None


def meses_desde_observacion(texto):
    """Meses de la observación solo si corresponden a Volvo Connect (plan
    Básico, Medio, Full, con o sin CIV). Los contratos Blue, Gold y Silver son
    de CM y no cuentan. None si no hay."""
    return interpretar_observacion(texto)[1]


# =========================================================
# AGRUPACIÓN PARA LA PESTAÑA "PROVISIÓN" (tarjetas), agregada junto con
# ProvisionesModule (nueva) en src/ui/provisiones.py. A diferencia de
# Contratos/Facturación Manual, aquí la fila es (VIN, AÑO - MES) -- un mismo
# VIN se repite una vez por cada mes provisionado -- y no hay columna RUT ni
# RAZÓN SOCIAL, solo CLIENTE y EJECUTIVO.
# =========================================================
MESES_A_NUM = {
    'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
    'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12,
}


def _partes_periodo(periodo):
    """(año, mes_num) de un 'AÑO - MES' tipo '2026 - Agosto'. (0, 0) si no
    se puede interpretar, para que quede al final de cualquier orden."""
    texto = str(periodo).strip()
    if "-" not in texto:
        return (0, 0)
    anio_txt, mes_txt = texto.split("-", 1)
    try:
        anio = int(anio_txt.strip())
    except ValueError:
        anio = 0
    mes = MESES_A_NUM.get(mes_txt.strip().capitalize(), 0)
    return (anio, mes)


def calcular_fechas_justtime(cantidad_meses, hoy=None):
    """INICIO/TERMINO iniciales (columnas de facturación JustTime, ver
    COL_FECHA_INICIO_FACT/COL_FECHA_TERMINO_FACT) para una unidad NUEVA
    creada desde Provisiones (VincularComercialDialog). Mismo cálculo que
    usaba el `instalaciones.py` histórico: INICIO = día 1 del mes ACTUAL
    (el mes en que se hace la vinculación con Comercial/RM, no el mes que
    Provisiones tenía registrado -- confirmado con el usuario, 30-09-2026:
    en la práctica, si una unidad quedó en Provisiones en Agosto pero
    recién se vincula en Septiembre, el INICIO real que se usa es
    Septiembre). TERMINO = INICIO + cantidad_meses, o 'MENSUAL' si
    cantidad_meses es '-'/'MENSUAL'. `hoy` es inyectable para tests;
    default `datetime.now()`.

    Devuelve (inicio, termino)."""
    if hoy is None:
        hoy = datetime.now()

    inicio_dt = pd.Timestamp(year=hoy.year, month=hoy.month, day=1)
    inicio = inicio_dt.strftime('%d-%m-%Y')

    meses_txt = str(cantidad_meses).strip()
    if meses_txt in ('', '-') or meses_txt.upper() in ('NAN', 'MENSUAL'):
        return inicio, 'MENSUAL'

    try:
        meses_int = int(float(meses_txt))
        from dateutil.relativedelta import relativedelta
        termino_dt = inicio_dt + relativedelta(months=meses_int)
        return inicio, termino_dt.strftime('%d-%m-%Y')
    except (ValueError, TypeError):
        return inicio, '-'


def obtener_clientes(df_filtrado):
    """Una fila por CLIENTE unico, con su EJECUTIVO (primero encontrado) y
    la cantidad de registros (VIN x período) asociados."""
    columnas_vacio = ['CLIENTE', 'EJECUTIVO', 'REGISTROS']
    if df_filtrado.empty or 'CLIENTE' not in df_filtrado.columns:
        return pd.DataFrame(columns=columnas_vacio)

    agrupado = df_filtrado.groupby('CLIENTE', dropna=False)
    resumen = agrupado.size().reset_index(name='REGISTROS')

    if 'EJECUTIVO' in df_filtrado.columns:
        ejecutivo_por_cliente = agrupado['EJECUTIVO'].first().reset_index()
        resumen = resumen.merge(ejecutivo_por_cliente, on='CLIENTE', how='left')
        resumen = resumen[['CLIENTE', 'EJECUTIVO', 'REGISTROS']]

    return resumen.sort_values('CLIENTE', kind='mergesort').reset_index(drop=True)


def obtener_periodos_disponibles(df, columna='AÑO - MES'):
    """Valores únicos de 'AÑO - MES' (ej. '2026 - Agosto'), ordenados de más
    reciente a más antiguo -- mismo criterio y orden que ya usa combo_fecha
    en 'Vista Completa' (_ProvisionesModuleLegacy.load_data()). Reutilizado
    por el combo de período de la pestaña 'Provisión' (src/ui/provisiones.py)
    para que ambas pestañas ofrezcan exactamente el mismo filtro."""
    if df.empty or columna not in df.columns:
        return []
    valores = [str(v).strip() for v in df[columna].astype(str).unique() if str(v).strip() and str(v).strip().lower() != 'nan']
    return sorted(valores, key=_partes_periodo, reverse=True)


def obtener_provisiones_cliente(df_filtrado, cliente):
    """Filas de un solo CLIENTE, ordenadas por período descendente (año más
    reciente primero y, dentro del año, mes más reciente primero) -- mismo
    criterio que ya usaba ProvisionesModule.load_data() para ordenar
    combo_fecha. Conserva el índice original de df_filtrado, para que quien
    llama pueda seguir ubicando la posición real de cada fila."""
    if df_filtrado.empty or 'CLIENTE' not in df_filtrado.columns:
        return df_filtrado.iloc[0:0]

    df_cliente = df_filtrado[df_filtrado['CLIENTE'] == cliente]
    if df_cliente.empty or 'AÑO - MES' not in df_cliente.columns:
        return df_cliente

    orden = df_cliente['AÑO - MES'].apply(_partes_periodo)
    return df_cliente.loc[orden.sort_values(ascending=False).index]
