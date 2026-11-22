"""Datos de la pantalla General (clientes, flotas, unidades, historial y avisos) sin interfaz: lo que arma las tablas y fichas."""
import functools
import unicodedata
import pandas as pd
from src.core.constants import COL_RAZON_SOCIAL, COL_RUT, COL_INDUSTRIA, COL_CDB, COL_CDB_FLOTA, COL_VIN, COL_CHASIS, COL_FLOTA_VC, COL_TIPO_SERVICIO, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION, COL_FORMA_CONTRATO, COL_ESTADO_COMERCIAL, COL_INICIO_CONTRATO, COL_TERMINO_CONTRATO, COL_PERIODO_INTERNO, COL_TIPO_FACTURACION, COL_FECHA_BAJA, COL_ESTADO_ENTREGA
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import comercial_services


COLUMNAS_CLIENTES = ['Razón Social', 'RUT', 'Industria/s', 'CDB', 'Total unidades', 'Total flotas', 'Clave', 'Busqueda']


COLUMNAS_FLOTAS = ['Flota', 'Cliente', 'RUT', 'CDB Flota', 'Total unidades', 'Total clientes', 'Clave', 'Busqueda']


COLUMNAS_UNIDADES = ['VIN', 'CHASIS', 'Razón Social', 'CDB', 'RUT', 'Flota VC', 'Estado Activación',
                      'Industria/s', 'ETAPA GESTIÓN', 'Estado Comercial', 'Forma de Contrato',
                      'Tipo de Facturación', 'Inicio Contrato', 'Término Contrato', 'Periodo Interno',
                      'Tipo de Servicio', 'CDB Flota', 'Fecha de Baja', 'Fecha de Entrega', 'Clave']


COLUMNAS_HISTORIAL = ["FECHA Y HORA", "MÓDULO", "IDENTIFICADOR", "CAMPO MODIFICADO", "VALOR ANTERIOR", "NUEVO VALOR"]


ESTADO_ACTIVACION_CONECTADO = "CONECTADO"  # único valor que cuenta para el KPI "Volvo Connect"


FLOTA_VC_SIN_FLOTA = ('sin flota', 'no existe en vc')


def flota_valida(valor):
    return str(valor).strip().lower() not in ('', '-', 'nan', 'none', 'n/a', '<na>') + FLOTA_VC_SIN_FLOTA


@functools.lru_cache(maxsize=60000)
def _clave_texto(nombre):
    texto = unicodedata.normalize('NFKD', " ".join(nombre.split()))
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def clave_flota_texto(nombre):
    """Clave para comparar textos (flotas, valores de filtro): sin distinguir
    mayúsculas, tildes ni espacios repetidos. Los resultados se recuerdan: se pide la misma clave miles de veces."""
    return _clave_texto(str(nombre))


def texto_duracion(dias):
    dias = abs(int(dias))
    if dias >= 60:
        return f"{dias // 30} meses"
    return f"{dias} día" if dias == 1 else f"{dias} días"


def calcular_vigencia(inicio, termino, hoy=None, baja=None, finalizado=False):
    """Estado de un contrato para la tarjeta de la ficha. Devuelve inicio y
    termino (DD-MM-YYYY o '-'), estado ('vencido', 'vigente', 'baja',
    'baja_prog' o 'sin'), progreso (0-100 o None), la leyenda a mostrar y
    `baja` (fecha, solo si cae antes del término; None si no). Con
    `finalizado` un contrato pasado de término se informa como 'finalizado'
    en vez de 'vencido'."""
    hoy = (hoy or pd.Timestamp.now()).normalize()
    f_ini = DataFrameFormatter.parsear_fecha_segura(inicio) if flota_valida(inicio) else pd.NaT
    f_ter = DataFrameFormatter.parsear_fecha_segura(termino) if flota_valida(termino) else pd.NaT
    f_baja = DataFrameFormatter.parsear_fecha_segura(baja) if flota_valida(baja) else pd.NaT
    res = {
        'inicio': f_ini.strftime('%d-%m-%Y') if pd.notna(f_ini) else '-',
        'termino': f_ter.strftime('%d-%m-%Y') if pd.notna(f_ter) else '-',
        'estado': 'sin', 'progreso': None, 'texto': '', 'baja': None,
    }
    if pd.isna(f_ter):
        return res
    f_ter = f_ter.normalize()
    ini_valido = pd.notna(f_ini) and f_ter > f_ini.normalize()

    def porcentaje(fecha):
        total = (f_ter - f_ini.normalize()).days
        return max(0, min(100, int(round((fecha.normalize() - f_ini.normalize()).days / total * 100))))

    if pd.notna(f_baja) and f_baja.normalize() < f_ter:
        f_baja = f_baja.normalize()
        res['baja'] = f_baja.strftime('%d-%m-%Y')
        if finalizado and hoy > f_ter:
            res.update(estado='finalizado', texto=f"Contrato finalizado hace {texto_duracion((hoy - f_ter).days)}",
                       progreso=porcentaje(f_baja) if ini_valido else 100)
        elif hoy >= f_baja:
            res.update(estado='baja', texto=f"De baja hace {texto_duracion((hoy - f_baja).days)}",
                       progreso=porcentaje(f_baja) if ini_valido else 100)
        else:
            res.update(estado='baja_prog', texto=f"Baja en {texto_duracion((f_baja - hoy).days)}",
                       progreso=porcentaje(hoy) if ini_valido else None)
        return res
    if hoy > f_ter:
        if finalizado:
            res.update(estado='finalizado', progreso=100,
                       texto=f"Contrato finalizado hace {texto_duracion((hoy - f_ter).days)}")
        else:
            res.update(estado='vencido', progreso=100, texto=f"Vencido hace {texto_duracion((hoy - f_ter).days)}")
    else:
        res.update(estado='vigente', texto=f"Vigente · vence en {texto_duracion((f_ter - hoy).days)}")
        if ini_valido:
            res['progreso'] = porcentaje(hoy)
    return res


def formatear_fecha_contrato(valor, con_vencimiento=False):
    """Fecha DD-MM-YYYY (o '' si no hay). Con `con_vencimiento` devuelve
    (texto, vencido); sin él, (texto,) en una tupla de un elemento."""
    texto, vencido = "", False
    if flota_valida(valor):
        fecha = DataFrameFormatter.parsear_fecha_segura(valor)
        if pd.notna(fecha):
            texto = fecha.strftime('%d-%m-%Y')
            vencido = fecha.normalize() < pd.Timestamp.now().normalize()
        else:
            texto = str(valor).strip()
    return (texto, vencido) if con_vencimiento else (texto,)


def mes_anio(valor):
    """'26-12-2025' -> '12-2025'; lo que no es una fecha (MENSUAL, '-') queda igual."""
    fecha = DataFrameFormatter.parsear_fecha_segura(valor) if flota_valida(valor) else pd.NaT
    return fecha.strftime('%m-%Y') if pd.notna(fecha) else str(valor).strip()


def formatear_fecha_historial(valor):
    """'2026-09-15 17:15:00' -> '15-09-2026 17:15'. Mismo criterio
    robusto (format='mixed' + dayfirst=True) que ya usa HistorialModule
    (historial.py) para tolerar registros migrados desde el .xlsx legado
    con otro formato. Si no se puede parsear, se muestra el valor tal
    cual en vez de esconderlo. Función pura."""
    texto = str(valor).strip()
    if not texto:
        return "-"
    parsed = pd.to_datetime(texto, format='mixed', dayfirst=True, errors='coerce')
    if pd.isna(parsed):
        return texto
    return parsed.strftime('%d-%m-%Y %H:%M')


def valor_ficha(fila, col_name):
    """Valor de una columna de la fila de df_comercial_raw ya listo para
    mostrar en la ficha: '-' para vacío/NaN/None, texto tal cual en caso
    contrario. Función pura (no usa self.*)."""
    valor = fila.get(col_name, '') if hasattr(fila, 'get') else ''
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return '-'
    texto = str(valor).strip()
    return texto if texto and texto.lower() not in ('nan', 'none', '<na>') else '-'


def _clave_id_contrato(valor):
    """'12864', '12864.0' y ' 12864 ' son el mismo ID de contrato."""
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith('.0') and texto[:-2].isdigit() else texto


def ids_contrato_de_vin(df_master, vin):
    """IDs de todos los contratos de un VIN. Comercial guarda sus altas y ediciones en LogApp con el ID del
    contrato en vez del VIN, así que el historial de la unidad los necesita para no perder esos registros."""
    if df_master is None or df_master.empty or COL_VIN not in df_master.columns or 'ID' not in df_master.columns:
        return []
    mascara = df_master[COL_VIN].astype(str).str.strip().str.upper() == str(vin).strip().upper()
    return [_clave_id_contrato(i) for i in df_master.loc[mascara, 'ID'] if _clave_id_contrato(i) not in ('', 'nan')]


def filtrar_historial_por_vin(df_logs, vin, ids_contrato=()):
    """LogApp.csv (self.data_manager.get_logs_df(), ver
    config.settings.LOG_CSV_PATH) filtrado por la columna identificadora
    == VIN, más reciente primero. Misma fuente que ya usa HistorialModule
    (src/ui/historial.py) -- no crea ninguna fuente de historial nueva
    ni toca excel_writer.py.

    La columna identificadora se llama 'IDENTIFICADOR' en cualquier
    LogApp.csv creado desde cero (ver _HEADER_LOG_DEFAULT en
    excel_writer.py), pero en instalaciones migradas desde el LogApp.xlsx
    legado se llama literalmente 'VIN': migrar_historial_legacy() copia
    el encabezado ORIGINAL del archivo legado tal cual venía (no lo
    normaliza a 'IDENTIFICADOR'), así que en producción esa columna
    puede tener cualquiera de los dos nombres. Bug reportado 15-09-2026:
    con un LogApp.csv migrado (columna 'VIN'), este filtro buscaba solo
    'IDENTIFICADOR' y nunca encontraba nada -- por eso historial.py
    (que no depende del nombre exacto de la columna) sí mostraba los
    cambios y el historial por VIN de esta pantalla no. Función pura (no
    usa self.*)."""
    vacio = pd.DataFrame(columns=COLUMNAS_HISTORIAL)
    if df_logs is None or df_logs.empty or not vin:
        return vacio

    columna_id = 'IDENTIFICADOR' if 'IDENTIFICADOR' in df_logs.columns else (
        'VIN' if 'VIN' in df_logs.columns else None)
    if columna_id is None:
        return vacio

    vin_str = str(vin).strip().upper()
    claves = {vin_str} | {_clave_id_contrato(i).upper() for i in ids_contrato}
    df_f = df_logs[df_logs[columna_id].astype(str).str.strip().str.upper().isin(claves)].copy()
    if df_f.empty:
        return df_f

    if 'FECHA Y HORA' in df_f.columns:
        df_f['_fecha_parsed'] = pd.to_datetime(df_f['FECHA Y HORA'], format='mixed', dayfirst=True, errors='coerce')
        df_f = df_f.sort_values('_fecha_parsed', ascending=False, na_position='last').drop(columns=['_fecha_parsed'])

    return df_f.reset_index(drop=True)


CAMPOS_OCULTOS_HISTORIAL = (COL_ETAPA_GESTION,)   # la etapa de gestión es interna: el usuario no la ve
TONO_GESTION_VERDE, TONO_GESTION_ROJO, TONO_GESTION_AZUL, TONO_GESTION_GRIS = 'verde', 'rojo', 'azul', 'gris'


def duracion_texto(inicio, fin):
    """'3 min', '2 días', '7 meses', '3 años y 9 meses' entre dos fechas."""
    segundos = (fin - inicio).total_seconds()
    dias = int(segundos // 86400)
    if dias < 1:
        minutos = int(segundos // 60)
        return f"{minutos} min" if minutos < 60 else f"{minutos // 60} h"
    if dias < 31:
        return f"{dias} día" + ("s" if dias != 1 else "")
    meses = dias // 30
    if meses < 12:
        return f"{meses} mes" + ("es" if meses != 1 else "")
    anios, resto = divmod(meses, 12)
    texto = f"{anios} año" + ("s" if anios != 1 else "")
    return texto + (f" y {resto} mes" + ("es" if resto != 1 else "") if resto else "")


def _titulo_guardado(filas, id_contrato):
    """(título, tono) de los cambios guardados juntos, según lo más importante que ocurrió."""
    campos = {f['campo']: f for f in filas}
    if any(f['antes'] == 'NUEVO REGISTRO' for f in filas):
        id_alta = campos['ID']['ahora'] if 'ID' in campos else id_contrato
        return (f"Contrato N° {id_alta} creado" if id_alta not in ('', '-') else "Contrato creado"), TONO_GESTION_VERDE
    activacion = campos.get(COL_ESTADO_ACTIVACION)
    if activacion and activacion['ahora'].upper() == 'CONECTADO':
        return "Se conectó", TONO_GESTION_VERDE
    if activacion and activacion['ahora'].upper() == 'DESCONECTADO':
        return "Se desconectó", TONO_GESTION_ROJO
    baja = campos.get(COL_FECHA_BAJA)
    if baja and baja['ahora'] not in ('', '-'):
        return "Fecha de baja asignada", TONO_GESTION_ROJO
    comercial = campos.get(COL_ESTADO_COMERCIAL)
    if comercial:
        return f"Estado comercial: {comercial['ahora']}", TONO_GESTION_AZUL
    if len(filas) > 1:
        return f"{len(filas)} campos modificados", TONO_GESTION_GRIS
    return f"{filas[0]['campo'].capitalize()} modificado", TONO_GESTION_GRIS


def construir_historial_unidad(df_eventos, fila=None, hoy=None):
    """Historial de una unidad listo para mostrar. Devuelve:
    - hitos: pasó a activación, se conectó y se dio de baja. Cada uno sale del momento en que se guardó el cambio
      en la app (fuente 'historial') o, si el historial no lo tiene, de las fechas del contrato (fuente 'contrato':
      inicio, fecha de entrega y fecha de baja);
    - resumen_conexion: cuánto lleva (o estuvo) conectada;
    - dias: los cambios agrupados por día y, dentro de cada día, por guardado.
    Los campos de CAMPOS_OCULTOS_HISTORIAL no se incluyen. `fila` es el contrato actual (para las fechas de respaldo)."""
    from datetime import datetime
    hoy = hoy or datetime.now()
    eventos = []
    if df_eventos is not None and not df_eventos.empty and 'FECHA Y HORA' in df_eventos.columns:
        col_id = 'IDENTIFICADOR' if 'IDENTIFICADOR' in df_eventos.columns else ('VIN' if 'VIN' in df_eventos.columns else None)
        tiempos = pd.to_datetime(df_eventos['FECHA Y HORA'], format='mixed', dayfirst=True, errors='coerce')
        for (_, r), t in zip(df_eventos.iterrows(), tiempos):
            campo = str(r.get('CAMPO MODIFICADO', '')).strip()
            if campo in CAMPOS_OCULTOS_HISTORIAL or pd.isna(t):
                continue
            eventos.append({'t': t.to_pydatetime(), 'modulo': str(r.get('MÓDULO', '')).strip(),
                            'clave': str(r.get(col_id, '')).strip() if col_id else '', 'campo': campo,
                            'antes': str(r.get('VALOR ANTERIOR', '')).strip(), 'ahora': str(r.get('NUEVO VALOR', '')).strip()})
    eventos.sort(key=lambda e: e['t'])

    def ultimo(condicion):
        coinciden = [e for e in eventos if condicion(e)]
        return coinciden[-1] if coinciden else None

    activacion = ultimo(lambda e: (e['campo'] == COL_ESTADO_COMERCIAL and 'ACTIVACI' in e['ahora'].upper())
                        or (e['campo'] == COL_ESTADO_ACTIVACION and e['ahora'].upper() == 'ACTIVANDO'))
    conexion = ultimo(lambda e: e['campo'] == COL_ESTADO_ACTIVACION and e['ahora'].upper() == 'CONECTADO' and e['antes'] != 'NUEVO REGISTRO')
    desconexion = ultimo(lambda e: e['campo'] == COL_ESTADO_ACTIVACION and e['ahora'].upper() == 'DESCONECTADO')

    def fecha_de(campo):
        valor = fila.get(campo, '') if fila is not None and hasattr(fila, 'get') else ''
        if not flota_valida(valor):
            return None
        parseada = DataFrameFormatter.parsear_fecha_segura(valor)
        return parseada.to_pydatetime() if pd.notna(parseada) else None

    inicio, entrega, baja_contrato = fecha_de(COL_INICIO_CONTRATO), fecha_de(COL_ESTADO_ENTREGA), fecha_de(COL_FECHA_BAJA)
    estado = str(fila.get(COL_ESTADO_ACTIVACION, '')).strip().upper() if fila is not None and hasattr(fila, 'get') else ''

    h_act = {'clave': 'activacion', 'titulo': 'Pasó a activación', 't': None}
    if activacion:
        h_act.update(t=activacion['t'], fuente='historial', detalle=f"Registrado en {activacion['modulo']}" if activacion['modulo'] else '')
    elif inicio:
        h_act.update(titulo='Inicio del contrato', t=inicio, fuente='contrato', detalle='Fecha de inicio del contrato', sin_hora=True)
    h_con = {'clave': 'conexion', 'titulo': 'Se conectó', 't': None}
    if conexion:
        h_con.update(t=conexion['t'], fuente='historial', detalle=f"Registrado en {conexion['modulo']}" if conexion['modulo'] else '')
    elif entrega and estado in ('CONECTADO', 'DESCONECTADO'):
        h_con.update(t=entrega, fuente='contrato', detalle='Según la fecha de entrega', sin_hora=True)
    h_baja = {'clave': 'baja', 'titulo': 'Se dio de baja', 't': None, 'vigente': True}
    if baja_contrato or desconexion:
        detalle = f"Registrado en {desconexion['modulo']}" if desconexion and not baja_contrato else 'Según la fecha de baja del contrato'
        if desconexion and baja_contrato and desconexion['t'].date() != baja_contrato.date():
            detalle = f"Desconectada el {desconexion['t'].strftime('%d-%m-%Y %H:%M')}"
        h_baja.update(t=baja_contrato or desconexion['t'], fuente='contrato' if baja_contrato else 'historial',
                      detalle=detalle, sin_hora=bool(baja_contrato), vigente=False)
    hitos = [h_act, h_con, h_baja]
    for h in hitos:
        h['alcanzado'] = h['t'] is not None
        h['fecha'] = h['t'].strftime('%d-%m-%Y') if h['t'] else ''
        h['hora'] = '' if (h['t'] is None or h.get('sin_hora')) else h['t'].strftime('%H:%M')
    if h_act['alcanzado'] and h_con['alcanzado'] and h_con['t'] >= h_act['t']:
        espera = duracion_texto(h_act['t'], h_con['t'])
        h_con['tras'] = ("a los " if (h_con['t'] - h_act['t']).days < 1 else "tras ") + espera
    resumen = ''
    if h_con['alcanzado']:
        resumen = (f"Estuvo conectada {duracion_texto(h_con['t'], h_baja['t'])}" if h_baja['alcanzado'] and h_baja['t'] >= h_con['t']
                   else f"Lleva {duracion_texto(h_con['t'], hoy)} conectada" if not h_baja['alcanzado'] else '')
    for h in hitos:
        h.pop('t', None)
        h.pop('sin_hora', None)

    guardados = {}
    for e in eventos:
        guardados.setdefault((e['t'], e['modulo'], e['clave']), []).append(e)
    dias = {}
    for (t, modulo, clave), filas in sorted(guardados.items(), key=lambda kv: kv[0][0], reverse=True):
        titulo, tono = _titulo_guardado(filas, clave)
        creado = any(f['antes'] == 'NUEVO REGISTRO' for f in filas)
        valores = {f['campo']: f['ahora'] for f in filas}
        chips = [valores[c] for c in (COL_FORMA_CONTRATO, COL_TIPO_SERVICIO, COL_TIPO_FACTURACION, COL_ESTADO_COMERCIAL)
                 if valores.get(c) not in (None, '', '-')] if creado else []
        dias.setdefault(t.date(), []).append({
            'hora': t.strftime('%H:%M'), 'modulo': modulo, 'titulo': titulo, 'tono': tono, 'n': len(filas), 'creado': creado,
            'chips': chips,
            'filas': [{'campo': f['campo'], 'antes': '' if creado else (f['antes'] or '-'), 'ahora': f['ahora'] or '-'}
                      for f in filas if not (creado and f['ahora'] in ('-', ''))]})
    lista_dias = []
    for dia, grupo in dias.items():
        delta = (hoy.date() - dia).days
        lista_dias.append({'dia': dia.strftime('%d-%m-%Y'),
                           'rel': 'Hoy' if delta == 0 else 'Ayer' if delta == 1 else f"Hace {delta} días" if delta > 0 else '',
                           'guardados': grupo})
    return {'hitos': hitos, 'resumen_conexion': resumen, 'dias': lista_dias,
            'n_guardados': sum(len(d['guardados']) for d in lista_dias), 'n_cambios': len(eventos)}


def claves_con_varias_razones(df_comercial):
    """Claves de cliente (por RUT) que aparecen con más de una razón social distinta en sus filas."""
    if df_comercial.empty or COL_RUT not in df_comercial.columns or COL_RAZON_SOCIAL not in df_comercial.columns:
        return set()
    razon = df_comercial[COL_RAZON_SOCIAL].astype(str).str.strip()
    clave = comercial_services.clave_cliente_serie(df_comercial[COL_RUT], razon)
    con_rut = clave.str.startswith('RUT:')
    if not con_rut.any():
        return set()
    conteo = razon[con_rut].groupby(clave[con_rut]).nunique()
    return set(conteo[conteo > 1].index)


def preparar_extras_general(df_comercial):
    """Lo que Vista General calculaba en el hilo de la interfaz tras cargar: (df con las claves de cliente y
    de flota, claves con varias razones, avisos de flota, DataFrame de flotas). Sin widgets: corre en un hilo."""
    df = df_comercial
    if COL_RUT in df.columns and COL_RAZON_SOCIAL in df.columns:
        df = df.assign(_clave_cliente=comercial_services.clave_cliente_serie(df[COL_RUT], df[COL_RAZON_SOCIAL]))
    varias_razones = claves_con_varias_razones(df)
    avisos_flota = calcular_avisos_flota(df)
    if COL_FLOTA_VC in df.columns:
        df = df.assign(_clave_flota=claves_flota(df))
    return df, varias_razones, avisos_flota, build_flotas_df(df)


def claves_flota(df):
    """Clave de Flota VC de cada fila ('' si la fila no tiene una flota válida)."""
    if df.empty or COL_FLOTA_VC not in df.columns:
        return pd.Series('', index=df.index, dtype=object)
    flota = df[COL_FLOTA_VC].astype(str).str.strip()
    return comercial_services.aplicar_por_valor_unico(flota, lambda v: clave_flota_texto(v) if flota_valida(v) else '')


def build_flotas_df(df_comercial):
    """Una fila por Flota VC (mismo nombre escrito distinto cuenta como una). Trae su cliente más
    frecuente, cuántos clientes distintos tiene y un texto de búsqueda con flota, clientes, RUT, CDB,
    VIN y chasis."""
    vacio = pd.DataFrame(columns=COLUMNAS_FLOTAS)
    if df_comercial.empty or COL_FLOTA_VC not in df_comercial.columns:
        return vacio
    claves = df_comercial['_clave_flota'] if '_clave_flota' in df_comercial.columns \
        else claves_flota(df_comercial)
    validas = claves != ''
    if not validas.any():
        return vacio
    df = df_comercial[validas]
    claves = claves[validas]

    def texto(col):
        return df[col].astype(str).str.strip() if col in df.columns else pd.Series('', index=df.index)

    flota, razon, rut = texto(COL_FLOTA_VC), texto(COL_RAZON_SOCIAL), texto(COL_RUT)
    cdb, cdb_flota, vin, chasis = texto(COL_CDB), texto(COL_CDB_FLOTA), texto(COL_VIN), texto(COL_CHASIS)
    cdb_flota = cdb_flota.str.replace(r'\.0$', '', regex=True)
    invalidos = {'', '-', 'nan', 'none', '<na>', 'no encontrado'}
    cdb_flota = cdb_flota.where(~cdb_flota.str.lower().isin(invalidos), '')
    rut_ok = rut.where(~rut.str.lower().isin(invalidos), '')
    cliente = df['_clave_cliente'] if '_clave_cliente' in df.columns else comercial_services.clave_cliente_serie(rut, razon)

    rut_plano = rut.str.upper().str.replace(r'[\.\-\s]', '', regex=True)
    base = pd.DataFrame({
        'Clave': claves, 'Flota': flota, 'Razon': razon, 'RUT': rut_ok, 'CDBF': cdb_flota, 'Cli': cliente,
        'Busqueda': (flota + ' ' + razon + ' ' + rut_plano + ' ' + rut + ' ' + cdb + ' ' + cdb_flota + ' ' + vin + ' ' + chasis).str.lower(),
    })
    grupos = base.groupby('Clave', sort=False)
    res = pd.DataFrame({
        'Flota': grupos['Flota'].agg(lambda s: s.value_counts().index[0]),
        'Cliente': grupos['Razon'].agg(lambda s: s.value_counts().index[0]),
        'RUT': grupos['RUT'].agg(lambda s: next((v for v in s if v), '')),
        'CDB Flota': grupos['CDBF'].agg(lambda s: next((v for v in s if v), '')),
        'Total unidades': grupos.size(),
        'Total clientes': grupos['Cli'].nunique(),
        'Busqueda': grupos['Busqueda'].agg(lambda s: ' '.join(dict.fromkeys(s))),
    }).reset_index()
    return res[COLUMNAS_FLOTAS]


def valor_valido(serie):
    """Valores de texto de una columna, sin vacíos, '-' ni 'No encontrado' y sin el '.0' de los números."""
    limpios = []
    for v in serie.dropna().astype(str).str.strip():
        v = v[:-2] if v.endswith('.0') else v
        if v.lower() not in ('', '-', 'nan', 'none', '<na>', 'no encontrado'):
            limpios.append(v)
    return limpios


def clientes_de_flota(df_unidades):
    """[{nombre, rut, cdb, unidades}] de los clientes de una flota, el de más unidades primero."""
    if df_unidades.empty or '_clave_cliente' not in df_unidades.columns:
        return []
    clientes = []
    for _, grupo in df_unidades.groupby('_clave_cliente', sort=False):
        nombres = valor_valido(grupo[COL_RAZON_SOCIAL]) if COL_RAZON_SOCIAL in grupo.columns else []
        ruts = valor_valido(grupo[COL_RUT]) if COL_RUT in grupo.columns else []
        cdbs = valor_valido(grupo[COL_CDB]) if COL_CDB in grupo.columns else []
        clientes.append({
            'nombre': pd.Series(nombres).value_counts().index[0] if nombres else '',
            'rut': ruts[0] if ruts else '', 'cdb': cdbs[0] if cdbs else '', 'unidades': len(grupo)})
    return sorted(clientes, key=lambda c: (-c['unidades'], c['nombre'].lower()))


def estados_de_flota(df_u):
    """Unidades Conectadas, Activando y Desconectadas (en ese orden). Una unidad con estado comercial
    VENCIDO cuenta como Conectada; el resto, según su estado de activación."""
    if df_u.empty:
        return [0, 0, 0]
    sin_contrato = (df_u[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper() == 'VENCIDO'
                    if COL_ESTADO_COMERCIAL in df_u.columns else pd.Series(False, index=df_u.index))
    activacion = (df_u[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
                  if COL_ESTADO_ACTIVACION in df_u.columns else pd.Series('', index=df_u.index))
    con_contrato = activacion[~sin_contrato]
    return [int((con_contrato == ESTADO_ACTIVACION_CONECTADO).sum()) + int(sin_contrato.sum()),
            int((con_contrato == 'ACTIVANDO').sum()), int((con_contrato == 'DESCONECTADO').sum())]


def flotas_de_unidades(df_unidades, columna=None):
    """[(flota, cantidad de unidades)] de un cliente, de mayor a menor,
    sin contar vacíos ni '-'."""
    columna = columna or COL_FLOTA_VC
    if df_unidades is None or df_unidades.empty or columna not in df_unidades.columns:
        return []
    nombres = df_unidades[columna].dropna().astype(str).str.strip()
    nombres = nombres[[flota_valida(n) for n in nombres]]
    # Mismo nombre escrito distinto (mayúsculas/espacios) cuenta como una
    # sola flota; se muestra la escritura más frecuente.
    grupos = {}
    for n in nombres:
        grupos.setdefault(clave_flota_texto(n), []).append(n)
    flotas = []
    for variantes in grupos.values():
        conteo = pd.Series(variantes).value_counts()
        flotas.append((conteo.index[0], len(variantes)))
    return sorted(flotas, key=lambda x: (-x[1], x[0].lower()))


def construir_mapa_director_empresa_pbi(df_pbi):
    """CDB -> {'correo', 'telefono', 'direccion', 'comuna'} del
    "Director de empresas", leído desde BBDD CLIENTES CM.xlsx (Power BI,
    mismas columnas 'Correo electrónico'/'Teléfono'/'Dirección'/'Comuna'
    que usa PowerBiSyncWorker en contactos.py para la pestaña "Director
    de empresas (Power BI)" de ContactosModule). Es un dato de la
    EMPRESA (un registro por CDB en Power BI), no de cada contacto
    individual -- por eso se muestra aparte en una tarjeta resaltada
    (_create_director_empresa_card) en vez de pisar el correo propio de
    cada contacto de contactos.xlsx; Dirección/Comuna se muestran en la
    caja "Información del cliente" (_render_info_cliente). CDB
    normalizado con str().strip() (mismo criterio que el resto de
    General). Si un CDB aparece en varias filas, se conserva el primer
    valor no vacío de cada campo. Función pura (no usa self.*), fuente
    de solo lectura -- nunca se escribe en ese Excel."""
    mapa = {}
    if df_pbi.empty or 'CDB' not in df_pbi.columns:
        return mapa

    columnas_pbi = {
        'correo': 'Correo electrónico',
        'telefono': 'Teléfono',
        'direccion': 'Dirección',
        'comuna': 'Comuna',
    }
    columnas_presentes = {k: v for k, v in columnas_pbi.items() if v in df_pbi.columns}
    if not columnas_presentes:
        return mapa

    # Vectorizado (antes iterrows): corre en un hilo, pero un bucle Python
    # largo le quitaba el GIL a la UI mientras el usuario abría otro módulo
    def _normalizar(serie):
        v = serie.astype(str).str.strip().fillna('')
        return v.mask(v.str.lower().isin(('nan', 'none', '<na>')), '')

    datos = pd.DataFrame({k: _normalizar(df_pbi[col]).values for k, col in columnas_presentes.items()})
    datos = datos.mask(datos == '')
    datos['_cdb'] = _normalizar(df_pbi['CDB']).values
    datos = datos[datos['_cdb'] != '']

    # Por CDB, el primer valor no vacío de cada campo, en orden de aparición
    primeros = datos.groupby('_cdb', sort=False).first()
    for cdb, fila in zip(primeros.index, primeros.to_dict('records')):
        registro = {'correo': '', 'telefono': '', 'direccion': '', 'comuna': ''}
        registro.update({k: ('' if pd.isna(v) else v) for k, v in fila.items()})
        mapa[cdb] = registro

    return mapa


def build_clientes_df(df_comercial):
    """Un cliente por RUT (sin RUT utilizable, por razón social). Su razón
    social es la más frecuente entre sus filas."""
    if df_comercial.empty or COL_RAZON_SOCIAL not in df_comercial.columns:
        return pd.DataFrame(columns=COLUMNAS_CLIENTES)

    df = df_comercial.copy()
    df[COL_RAZON_SOCIAL] = df[COL_RAZON_SOCIAL].astype(str).str.strip()
    df = df[df[COL_RAZON_SOCIAL] != '']
    if df.empty:
        return pd.DataFrame(columns=COLUMNAS_CLIENTES)

    rut_serie = df[COL_RUT] if COL_RUT in df.columns else pd.Series('', index=df.index)
    df['_clave'] = comercial_services.clave_cliente_serie(rut_serie, df[COL_RAZON_SOCIAL])

    agg_dict = {COL_RAZON_SOCIAL: lambda s: s.value_counts().index[0]}
    if COL_RUT in df.columns: agg_dict[COL_RUT] = 'first'
    if COL_INDUSTRIA in df.columns: agg_dict[COL_INDUSTRIA] = 'first'
    if COL_CDB in df.columns: agg_dict[COL_CDB] = 'first'
    if COL_VIN in df.columns: agg_dict[COL_VIN] = 'count'

    grouped = df.groupby('_clave', as_index=False, sort=False).agg(agg_dict)
    grouped = grouped.rename(columns={
        '_clave': 'Clave', COL_RAZON_SOCIAL: 'Razón Social', COL_RUT: 'RUT',
        COL_INDUSTRIA: 'Industria/s', COL_CDB: 'CDB', COL_VIN: 'Total unidades',
    })

    # Texto de búsqueda: todas las razones sociales, el RUT sin formato y
    # el CDB de las filas del cliente
    rut_plano = rut_serie.astype(str).str.upper().str.replace(r'[\.\-\s]', '', regex=True)
    cdb_serie = df[COL_CDB].astype(str).str.strip() if COL_CDB in df.columns else pd.Series('', index=df.index)
    texto = (df[COL_RAZON_SOCIAL] + ' ' + rut_plano + ' ' + rut_serie.astype(str) + ' ' + cdb_serie).str.lower()
    busqueda = texto.groupby(df['_clave']).agg(lambda s: ' '.join(dict.fromkeys(s)))
    grouped['Busqueda'] = grouped['Clave'].map(busqueda).fillna('')

    # Flotas distintas por cliente (sin vacíos ni '-')
    if COL_FLOTA_VC in df.columns:
        flota = df[COL_FLOTA_VC].astype(str).str.strip()
        validas = ~flota.str.lower().isin(['', '-', 'nan', 'none', '<na>', *FLOTA_VC_SIN_FLOTA])
        clave_flota = flota[validas].map(clave_flota_texto)
        conteo = clave_flota.groupby(df.loc[validas, '_clave']).nunique()
        grouped['Total flotas'] = grouped['Clave'].map(conteo).fillna(0).astype(int)

    for col in COLUMNAS_CLIENTES:
        if col not in grouped.columns:
            grouped[col] = 0 if col in ('Total unidades', 'Total flotas') else ""

    return grouped[COLUMNAS_CLIENTES]


def calcular_avisos_flota(df):
    """{clave de cliente: texto} de los clientes con datos de flota
    incoherentes: un CDB flota con varias Flota VC, una Flota VC con varios
    CDB flota, o unidades con solo uno de los dos datos."""
    if df.empty or '_clave_cliente' not in df.columns or COL_FLOTA_VC not in df.columns \
            or COL_CDB_FLOTA not in df.columns:
        return {}
    vacios = {'', 'NAN', 'NONE', '-', 'NAT', '<NA>'}
    cdb = df[COL_CDB_FLOTA].astype(str).str.strip().str.upper()
    flota = df[COL_FLOTA_VC].astype(str).str.strip().map(clave_flota_texto)
    flota_vacia = flota.isin(vacios)
    cdb_ok = ~cdb.isin(vacios)
    flota_ok = ~flota_vacia & ~flota.str.lower().isin(FLOTA_VC_SIN_FLOTA)
    clave = df['_clave_cliente']

    ambos = cdb_ok & flota_ok
    pares = pd.DataFrame({'clave': clave[ambos], 'cdb': cdb[ambos], 'flota': flota[ambos]})
    if pares.empty:
        cdb_varias = flota_varios = pd.Series(dtype=int)
    else:
        cdb_varias = (pares.groupby(['clave', 'cdb'])['flota'].nunique() > 1).groupby(level=0).sum()
        flota_varios = (pares.groupby(['clave', 'flota'])['cdb'].nunique() > 1).groupby(level=0).sum()
    incompletas = (cdb_ok ^ ~flota_vacia).groupby(clave).sum()

    avisos = {}
    for k in set(cdb_varias[cdb_varias > 0].index) | set(flota_varios[flota_varios > 0].index) \
            | set(incompletas[incompletas > 0].index):
        partes = []
        if cdb_varias.get(k, 0):
            partes.append(f"{int(cdb_varias[k])} CDB flota con varias Flota VC")
        if flota_varios.get(k, 0):
            partes.append(f"{int(flota_varios[k])} Flota VC con varios CDB flota")
        if incompletas.get(k, 0):
            partes.append(f"{int(incompletas[k])} unidad(es) con solo CDB flota o solo Flota VC")
        avisos[k] = "Revisar flotas: " + " · ".join(partes)
    return avisos


def filtrar_por_rango_fechas(df, columna, desde=None, hasta=None):
    """Filas cuya `columna` (texto DD-MM-YYYY) cae entre `desde` y `hasta`, ambos
    incluidos y opcionales (date o Timestamp). Sin ninguno no filtra; con alguno,
    una fecha vacía o '-' no coincide."""
    if (desde is None and hasta is None) or columna not in df.columns:
        return df
    fechas = pd.to_datetime(df[columna].astype(str).str.strip(), format='%d-%m-%Y', errors='coerce')
    mascara = fechas.notna()
    if desde is not None:
        mascara &= fechas >= pd.Timestamp(desde)
    if hasta is not None:
        mascara &= fechas <= pd.Timestamp(hasta)
    return df[mascara]


def build_unidades_df(df_comercial):
    """Listado general de unidades (caja izquierda, apartado "Unidades"):
    una fila por VIN, sin agrupar ni filtrar. Misma fuente que
    Cliente (df_comercial, ya procesado por
    comercial_services.procesar_df_comercial) -- no crea una fuente de
    datos nueva. Incluye Clave, CDB y Razón Social aunque no siempre se
    muestren, porque el detalle de la caja derecha reutiliza este mismo df."""
    if df_comercial.empty or COL_VIN not in df_comercial.columns:
        return pd.DataFrame(columns=COLUMNAS_UNIDADES)

    df = df_comercial.copy()

    def _normalizar_texto(val):
        if pd.isna(val):
            return ""
        v = str(val).strip()
        return "" if v.lower() in ['nan', 'none', '<na>'] else v

    rename_map = {
        COL_VIN: 'VIN', COL_CHASIS: 'CHASIS', COL_RAZON_SOCIAL: 'Razón Social',
        COL_CDB: 'CDB', COL_RUT: 'RUT', COL_FLOTA_VC: 'Flota VC', COL_ESTADO_ACTIVACION: 'Estado Activación',
        COL_INDUSTRIA: 'Industria/s', COL_ETAPA_GESTION: 'ETAPA GESTIÓN',
        COL_ESTADO_COMERCIAL: 'Estado Comercial', COL_FORMA_CONTRATO: 'Forma de Contrato',
        COL_TIPO_FACTURACION: 'Tipo de Facturación', COL_INICIO_CONTRATO: 'Inicio Contrato',
        COL_TERMINO_CONTRATO: 'Término Contrato', COL_PERIODO_INTERNO: 'Periodo Interno',
        COL_TIPO_SERVICIO: 'Tipo de Servicio', COL_CDB_FLOTA: 'CDB Flota', COL_FECHA_BAJA: 'Fecha de Baja',
        COL_ESTADO_ENTREGA: 'Fecha de Entrega',
    }
    cols_presentes = [c for c in rename_map if c in df.columns]
    df = df[cols_presentes].rename(columns=rename_map)
    for col in df.columns:
        df[col] = comercial_services.aplicar_por_valor_unico(df[col], _normalizar_texto)

    if 'RUT' in df.columns and 'Razón Social' in df.columns:
        df['Clave'] = comercial_services.clave_cliente_serie(df['RUT'], df['Razón Social'])

    for col in COLUMNAS_UNIDADES:
        if col not in df.columns:
            df[col] = ""

    return df[COLUMNAS_UNIDADES]
