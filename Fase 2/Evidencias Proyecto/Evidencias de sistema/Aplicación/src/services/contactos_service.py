"""Logica de negocio de Contactos extraida de src/ui/contactos.py (ver
auditoria previa). Python/pandas puro: no depende de PyQt6, QThread,
QWidget, QMessageBox ni ningun widget.

Incluye tambien formatear_telefono_chile(), que unifica una duplicacion
literal exacta que existia entre ContactosModule.on_item_edited() y
ContactosAddDialog._validate_and_accept() (src/ui/contactos_agregar.py)."""

import os
import json
import re

import pandas as pd


def normalizar_id_contacto(val):
    """Extraccion literal de ContactosModule._normalize_id(): normalizacion
    robusta y absoluta de IDs (soporta int, float, str, con o sin '.0')."""
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    if s.isdigit():
        return str(int(s))
    return s


def cargar_favoritos(filepath):
    """Extraccion literal de ContactosModule.load_pinned()."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def guardar_favoritos(filepath, pinned_contacts):
    """Extraccion literal de ContactosModule.save_pinned()."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(pinned_contacts, f)
    except Exception:
        pass


def migrar_favoritos_legacy(pinned_contacts, df_plataforma):
    """Extraccion literal de la parte de calculo puro de
    ContactosModule._migrate_pinned_contacts(): convierte favoritos antiguos
    (clave compuesta 'CDB_Nombre_Correo') a IDs fisicos permanentes.
    contactos.py sigue siendo responsable de decidir si persistir el
    resultado (guardar_favoritos) y de mutar self.pinned_contacts.

    Devuelve None si no hace falta migrar nada (mismas guardas que el
    original: sin favoritos, tabla vacia, sin columna ID, o ningun favorito
    con formato antiguo), o la lista nueva de favoritos si migro algo."""
    if not pinned_contacts or df_plataforma.empty or 'ID' not in df_plataforma.columns:
        return None

    needs_migration = any("_" in str(pin) for pin in pinned_contacts)
    if not needs_migration:
        return None

    new_pins = []
    for pin in pinned_contacts:
        pin_str = str(pin)
        if "_" in pin_str:
            try:
                parts = pin_str.split("_")
                if len(parts) >= 3:
                    cdb_p = parts[0]
                    nombre_p = parts[1]
                    correo_p = "_".join(parts[2:])

                    mask = (df_plataforma['CDB'].astype(str).str.strip() == cdb_p) & \
                           (df_plataforma['Nombre'].astype(str).str.strip() == nombre_p) & \
                           (df_plataforma['Correo electrónico'].astype(str).str.strip() == correo_p)

                    match_df = df_plataforma[mask]
                    if len(match_df) == 1:
                        nuevo_id = normalizar_id_contacto(match_df.iloc[0]['ID'])
                        if nuevo_id not in new_pins:
                            new_pins.append(nuevo_id)
            except Exception:
                pass
        else:
            if pin_str not in new_pins:
                new_pins.append(pin_str)

    return new_pins


def generar_nuevo_id_contacto(df_plataforma):
    """Extraccion literal del calculo de nuevo ID en
    ContactosModule._open_add_dialog(): maximo ID existente + 1, o 1 si la
    tabla esta vacia o no tiene columna ID. Devuelve un string."""
    if not df_plataforma.empty and 'ID' in df_plataforma.columns:
        try:
            max_id = pd.to_numeric(df_plataforma['ID'], errors='coerce').max()
            new_id = int(max_id) + 1 if pd.notna(max_id) else 1
        except Exception:
            new_id = 1
    else:
        new_id = 1
    return str(new_id)


COLUMNAS_EXCEL_BOT = ['CDB', 'Flota', 'Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil', 'Rol', 'Fecha de extracción']


def leer_administradores_bot(ruta):
    """Hoja "Administradores" del Excel que genera el bot de Servicios Conectados.
    Lanza ValueError con un mensaje legible si el archivo no es ese Excel."""
    try:
        df = pd.read_excel(ruta, sheet_name='Administradores', dtype=object, keep_default_na=False)
    except ValueError:
        raise ValueError('El Excel no tiene la hoja "Administradores" del bot de Servicios Conectados.')
    df.columns = [str(c).strip() for c in df.columns]
    faltantes = [c for c in COLUMNAS_EXCEL_BOT if c not in df.columns]
    if faltantes:
        raise ValueError("Faltan columnas en la hoja Administradores: " + ", ".join(faltantes))
    return df[COLUMNAS_EXCEL_BOT].copy()


def _texto_contacto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ''
    texto = str(valor).strip()
    return '' if texto.lower() in ('nan', 'nat', 'none') else texto


def _llave_contacto(cdb, nombre, apellidos, correo):
    """Identidad de un contacto: CDB + correo; sin correo, CDB + nombre completo."""
    cdb = re.sub(r'\.0$', '', _texto_contacto(cdb))
    correo = _texto_contacto(correo).lower()
    if correo and correo != '-':
        return (cdb, correo)
    return (cdb, f"{_texto_contacto(nombre)} {_texto_contacto(apellidos)}".lower().strip())


def construir_contactos_nuevos(df_bot, df_actual):
    """Contactos del Excel del bot que aún no están en contactos.xlsx, ya con
    ID nuevo y listos para escribir. Los que ya existen (mismo CDB y correo)
    no se tocan. Devuelve {'registros', 'existentes', 'repetidos',
    'incompletos', 'por_revisar'}."""
    existentes_llaves = set()
    if df_actual is not None and not df_actual.empty and 'CDB' in df_actual.columns:
        for _, f in df_actual.iterrows():
            existentes_llaves.add(_llave_contacto(f.get('CDB'), f.get('Nombre'), f.get('Apellidos'), f.get('Correo electrónico')))
    siguiente = int(generar_nuevo_id_contacto(df_actual if df_actual is not None else pd.DataFrame()))
    resultado = {'registros': [], 'existentes': 0, 'repetidos': 0, 'incompletos': 0, 'por_revisar': 0}
    vistos = set()
    for _, f in df_bot.iterrows():
        cdb = re.sub(r'\.0$', '', _texto_contacto(f['CDB']))
        nombre, correo = _texto_contacto(f['Nombre']), _texto_contacto(f['Correo electrónico'])
        if not cdb or (not nombre and not correo):
            resultado['incompletos'] += 1
            continue
        llave = _llave_contacto(cdb, nombre, f['Apellidos'], correo)
        if llave in existentes_llaves:
            resultado['existentes'] += 1
            continue
        if llave in vistos:
            resultado['repetidos'] += 1
            continue
        vistos.add(llave)
        movil = _texto_contacto(f['Número móvil']) or '-'
        if not es_telefono_vacio(movil):
            movil = formatear_telefono_internacional(normalizar_telefono_ingresado(movil))
        fecha = f['Fecha de extracción']
        if hasattr(fecha, 'to_pydatetime'):
            fecha = fecha.to_pydatetime()
        registro = {
            'ID': siguiente, 'CDB': cdb, 'Flota': _texto_contacto(f['Flota']), 'Nombre': nombre,
            'Apellidos': _texto_contacto(f['Apellidos']), 'Correo electrónico': correo, 'Número móvil': movil,
            'Rol': _texto_contacto(f['Rol']), 'Fecha de extracción': fecha,
        }
        if any(motivo_dato_invalido(c, registro[c]) for c in _COLUMNAS_A_REVISAR):
            resultado['por_revisar'] += 1
        resultado['registros'].append(registro)
        siguiente += 1
    return resultado


_COLUMNAS_A_REVISAR = ('Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil')


def formatear_telefono_chile(texto):
    """Extraccion y unificacion del formateo de telefono al estandar
    corporativo chileno (+56 9 XXXX XXXX), que estaba duplicado de forma
    identica en ContactosModule.on_item_edited() (src/ui/contactos.py) y en
    ContactosAddDialog._validate_and_accept() (src/ui/contactos_agregar.py).

    Devuelve el texto formateado, o None si `texto` no contiene ningun
    digito: en ese caso el llamador no debe modificar el valor original,
    igual que hacian ambos duplicados (uno dejaba `new_value` intacto, el
    otro no llamaba a `setText`)."""
    phone_text = str(texto).strip()
    digits = ''.join(c for c in phone_text if c.isdigit())
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith('56'):
        return f"+{digits[:2]} {digits[2:3]} {digits[3:7]} {digits[7:]}"
    if len(digits) == 9 and digits.startswith('9'):
        return f"+56 {digits[:1]} {digits[1:5]} {digits[5:]}"
    if len(digits) == 8:
        return f"+56 9 {digits[:4]} {digits[4:]}"
    return f"+{digits}"


# Código de país -> (ISO, nombre, mín. y máx. dígitos del número nacional)
PAISES_TELEFONO = {
    '1': ('US', 'EE.UU. / Canadá', 10, 10),
    '33': ('FR', 'Francia', 9, 9),
    '34': ('ES', 'España', 9, 9),
    '39': ('IT', 'Italia', 9, 11),
    '44': ('GB', 'Reino Unido', 10, 10),
    '46': ('SE', 'Suecia', 7, 10),
    '49': ('DE', 'Alemania', 7, 12),
    '51': ('PE', 'Perú', 8, 9),
    '52': ('MX', 'México', 10, 10),
    '54': ('AR', 'Argentina', 10, 11),
    '55': ('BR', 'Brasil', 10, 11),
    '56': ('CL', 'Chile', 9, 9),
    '57': ('CO', 'Colombia', 10, 10),
    '58': ('VE', 'Venezuela', 10, 10),
    '86': ('CN', 'China', 11, 11),
    '591': ('BO', 'Bolivia', 8, 8),
    '593': ('EC', 'Ecuador', 8, 9),
    '595': ('PY', 'Paraguay', 9, 9),
    '598': ('UY', 'Uruguay', 8, 8),
}
# Límite E.164 para códigos no reconocidos (código + número)
TELEFONO_MIN_DIGITOS = 8
TELEFONO_MAX_DIGITOS = 15

# Separadores aceptados: espacio, guion y apóstrofo (', ´ o ’)
_RE_NOMBRE = re.compile(r"^[^\W\d_]+(?:[ '´’\-][^\W\d_]+)*$")
_RE_CORREO = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def detectar_pais_telefono(texto):
    """Devuelve (codigo, iso, nombre, min, max) del prefijo más largo que
    calce con los dígitos de `texto`, o None si no se reconoce."""
    digitos = ''.join(c for c in str(texto) if c.isdigit())
    for largo in (3, 2, 1):
        codigo = digitos[:largo]
        if len(digitos) >= largo and codigo in PAISES_TELEFONO:
            return (codigo,) + PAISES_TELEFONO[codigo]
    return None


def validar_telefono(texto):
    """Teléfono opcional: vacío es válido. Si viene, debe ser '+' seguido
    solo de dígitos (se toleran espacios) con el largo del país detectado.
    Devuelve (es_valido, mensaje_error)."""
    texto = str(texto).strip()
    if not texto:
        return True, ""
    if not texto.startswith('+'):
        return False, "El número móvil debe comenzar con + y el código de país (ej: +56 9 1234 5678)."
    if not all(c.isdigit() or c == ' ' for c in texto[1:]):
        return False, "El número móvil solo puede tener dígitos después del +."
    digitos = ''.join(c for c in texto if c.isdigit())
    pais = detectar_pais_telefono(digitos)
    if pais is None:
        if not TELEFONO_MIN_DIGITOS <= len(digitos) <= TELEFONO_MAX_DIGITOS:
            return False, f"El número debe tener entre {TELEFONO_MIN_DIGITOS} y {TELEFONO_MAX_DIGITOS} dígitos."
        return True, ""
    codigo, _iso, nombre, minimo, maximo = pais
    largo = len(digitos) - len(codigo)
    if not minimo <= largo <= maximo:
        rango = f"{minimo}" if minimo == maximo else f"entre {minimo} y {maximo}"
        return False, f"Un número de {nombre} (+{codigo}) debe tener {rango} dígitos después del código."
    return True, ""


def formatear_telefono_internacional(texto):
    """Chile mantiene el estándar +56 9 XXXX XXXX; el resto queda como
    '+código número'. Si `texto` no es un teléfono válido lo devuelve tal cual."""
    texto = str(texto).strip()
    if not texto or not validar_telefono(texto)[0]:
        return texto
    digitos = ''.join(c for c in texto if c.isdigit())
    pais = detectar_pais_telefono(digitos)
    if pais is None:
        return f"+{digitos}"
    codigo = pais[0]
    if codigo == '56':
        return formatear_telefono_chile(digitos)
    return f"+{codigo} {digitos[len(codigo):]}"


def normalizar_telefono_ingresado(texto):
    """Si viene sin +, se asume formato chileno (criterio histórico de la
    app); con + se respeta el código de país escrito."""
    texto = str(texto).strip()
    if texto and not texto.startswith('+'):
        return formatear_telefono_chile(texto) or texto
    return texto


def es_telefono_vacio(texto):
    return str(texto).strip() in ('', '-', 'nan')


def corregir_telefono(texto):
    """Versión corregida de un teléfono guardado inválido, o None si ya es
    válido, está vacío o no se puede corregir sin intervención humana."""
    if es_telefono_vacio(texto) or validar_telefono(texto)[0]:
        return None
    candidato = normalizar_telefono_ingresado(texto)
    if not candidato.startswith('+') or not validar_telefono(candidato)[0]:
        return None
    return formatear_telefono_internacional(candidato)


def proponer_correcciones_telefono(df):
    """Lista de dicts {ID, Nombre, antes, despues} para los teléfonos del
    directorio que se pueden corregir automáticamente."""
    if df.empty or 'Número móvil' not in df.columns or 'ID' not in df.columns:
        return []
    propuestas = []
    for _, fila in df.iterrows():
        antes = '' if pd.isna(fila['Número móvil']) else str(fila['Número móvil']).strip()
        despues = corregir_telefono(antes)
        if despues and despues != antes:
            nombre = f"{fila.get('Nombre', '')} {fila.get('Apellidos', '')}".strip()
            propuestas.append({'ID': normalizar_id_contacto(fila['ID']), 'Nombre': nombre,
                               'antes': antes, 'despues': despues})
    return propuestas


def motivo_dato_invalido(columna, valor):
    """Mensaje de por qué `valor` no es válido para `columna`, o '' si está
    bien. Solo valida columnas editables de Contactos."""
    valor = '' if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor).strip()
    if columna in ('Nombre', 'Apellidos'):
        return "" if validar_nombre(valor) else "Solo se permiten letras (con acentos), espacios, guion y apóstrofo."
    if columna == 'Correo electrónico':
        return "" if validar_correo(valor) else "El correo no tiene un formato válido."
    if columna == 'Número móvil':
        if es_telefono_vacio(valor):
            return ""
        return validar_telefono(valor)[1]
    return ""


def validar_nombre(texto):
    """Solo letras (con acentos y ñ), separadas por espacio, guion o apóstrofo."""
    texto = str(texto).strip()
    return not texto or bool(_RE_NOMBRE.match(texto))


def validar_correo(texto):
    """Valida solo el formato; no confirma que el buzón exista."""
    texto = str(texto).strip()
    return not texto or bool(_RE_CORREO.match(texto))


DOMINIO_OK = 'ok'
DOMINIO_NO_EXISTE = 'no_existe'
DOMINIO_SIN_CORREO = 'sin_correo'
DOMINIO_DESCONOCIDO = 'desconocido'
_cache_dominios = {}


def verificar_dominio_correo(correo, timeout=4.0):
    """Consulta DNS si el dominio del correo puede recibir correo (registro
    MX, o A como respaldo). No confirma que el buzón exista. Sin conexión o
    sin dnspython devuelve DOMINIO_DESCONOCIDO para no bloquear al usuario."""
    correo = str(correo).strip()
    if '@' not in correo:
        return DOMINIO_DESCONOCIDO
    dominio = correo.rsplit('@', 1)[1].lower()
    if dominio in _cache_dominios:
        return _cache_dominios[dominio]
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        return DOMINIO_DESCONOCIDO
    resultado = DOMINIO_DESCONOCIDO
    try:
        dns.resolver.resolve(dominio, 'MX', lifetime=timeout)
        resultado = DOMINIO_OK
    except dns.resolver.NXDOMAIN:
        resultado = DOMINIO_NO_EXISTE
    except dns.resolver.NoAnswer:
        try:
            dns.resolver.resolve(dominio, 'A', lifetime=timeout)
            resultado = DOMINIO_OK
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            resultado = DOMINIO_SIN_CORREO
        except dns.exception.DNSException:
            pass
    except dns.exception.DNSException:
        pass
    # Lo desconocido no se guarda: puede ser una caída momentánea de red
    if resultado != DOMINIO_DESCONOCIDO:
        _cache_dominios[dominio] = resultado
    return resultado


def aplicar_cambios_pendientes_contactos(df, pending_changes):
    """Extraccion y unificacion de la superposicion de pending_changes sobre
    un DataFrame de contactos. Estaba duplicada con una diferencia menor
    entre ContactosModule.filter_tables() (comparaba el ID normalizado en
    mayusculas) y ContactosModule._on_save_finished() (comparaba el ID
    normalizado sin pasar a mayusculas, y sin castear la columna a `object`
    antes de asignar). Se unifica al criterio mas seguro de los dos: IDs en
    mayusculas + cast a `object` antes de cada asignacion. Para el dominio
    real de IDs de Contactos (siempre numericos) ambas versiones eran
    equivalentes, asi que unificarlas no cambia ningun resultado observado
    hoy.

    Si `id_key` no existe en `df`, se ignora silenciosamente (mismo
    comportamiento que ambos duplicados). Muta `df` in-place y lo retorna,
    igual que comercial_services.aplicar_cambios_pendientes."""
    if not pending_changes or 'ID' not in df.columns:
        return df

    ids_normalizados = df['ID'].apply(normalizar_id_contacto).str.upper()
    for id_key, data in pending_changes.items():
        id_key_clean = normalizar_id_contacto(id_key).upper()
        mask = (ids_normalizados == id_key_clean)
        if mask.any():
            for col, val in data.get('cambios', {}).items():
                if col in df.columns:
                    df[col] = df[col].astype(object)
                    df.loc[mask, col] = val
    return df


def aplicar_filtro_checkbox(df, columna, elementos_marcados, todos_marcados, ninguno_marcado):
    """Extraccion y unificacion del filtro por lista de checkboxes de
    ContactosModule.filter_tables(), duplicado de forma identica para
    'Flota' (tabla Administradores de flotas) y para 'Nombre' (tabla
    Director de empresas). El llamador sigue siendo responsable de verificar
    que `columna` exista en `df` antes de invocar esta funcion, igual que el
    original."""
    if ninguno_marcado:
        return df.iloc[0:0]
    if not todos_marcados:
        return df[df[columna].astype(str).str.strip().isin(elementos_marcados)]
    return df


def buscar_texto_global(df, columnas, search_text):
    """Busqueda global multi-columna de ContactosModule.filter_tables(),
    usada tanto para 'Administradores de flotas' (lista fija de columnas)
    como para 'Director de empresas' (todas las columnas del DataFrame).

    Corregido (25-09-2026): la version anterior partia `search_text` solo
    por espacios y combinaba TODOS los terminos con OR (`mask |= t_mask` por
    cada palabra suelta) -- buscar una razon social completa como "SERVICIO
    Y MANUFACTURAS DEMO SPA" se partia en 5 terminos sueltos y bastaba con
    que CUALQUIERA apareciera en cualquier columna para que la fila
    quedara; "SPA" (sufijo legal de sociedad, comun a cientos de empresas
    chilenas) o hasta "y" hacian que devolviera decenas de razones sociales
    sin relacion. Ahora sigue el mismo contrato que ya usa
    comercial_services.construir_mascara_busqueda para la misma barra
    global (MultiSearchLineEdit): las comas separan terminos independientes
    combinados con OR (pegar una lista de VINs/CDB/RUT sigue funcionando
    igual, ya que MultiSearchLineEdit convierte cada salto de linea pegado
    en una coma), y dentro de un mismo termino separado por comas, las
    palabras se combinan con AND (deben aparecer todas, en cualquier
    columna, para esa fila) -- asi "juan perez" encuentra a Juan Perez y no
    cualquier fila que solo contenga "juan" O "perez" por separado.
    Columnas de `columnas` que no existan en `df` se ignoran silenciosamente."""
    if not search_text:
        return df

    columnas_presentes = [c for c in columnas if c in df.columns]
    if not columnas_presentes:
        return df.iloc[0:0]

    or_terms = [t.strip() for t in str(search_text).split(',') if t.strip()]
    if not or_terms:
        return df

    mask = pd.Series(False, index=df.index)
    for or_term in or_terms:
        and_terms = [t for t in or_term.split() if t]
        if not and_terms:
            continue
        and_mask = pd.Series(True, index=df.index)
        for a_term in and_terms:
            col_mask = pd.Series(False, index=df.index)
            for col in columnas_presentes:
                col_mask |= df[col].astype(str).str.lower().str.contains(re.escape(a_term), na=False, regex=True)
            and_mask &= col_mask
        mask |= and_mask
    return df[mask]


def ordenar_por_favoritos_e_id(df, pinned_contacts):
    """Extraccion literal del paso de ordenamiento de
    ContactosModule.filter_tables(): favoritos primero, luego por ID
    ascendente (orden 'original' de la pantalla de Administradores de
    flota). Requiere que `df` ya tenga la columna 'ID' normalizada (string,
    sin '.0'); el orden numerico auxiliar se calcula en el momento en vez de
    depender de una columna creada antes del filtrado."""
    if df.empty or 'ID' not in df.columns:
        return df

    id_sort = pd.to_numeric(df['ID'], errors='coerce').fillna(0)
    is_pinned = df.apply(
        lambda row: 1 if normalizar_id_contacto(row.get('ID', '')) in pinned_contacts else 0,
        axis=1,
    )
    df = df.assign(_is_pinned=is_pinned, _id_sort=id_sort)
    df = df.sort_values(by=['_is_pinned', '_id_sort'], ascending=[False, True]).drop(columns=['_is_pinned', '_id_sort'])
    return df
