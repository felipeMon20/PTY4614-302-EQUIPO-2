"""
Archivo de Constantes Globales.
Centraliza los nombres de las columnas del Excel y otros textos críticos.
"""
from src.theme.colors import MODULE_COLORS

# ==========================================
# NOMBRES DE COLUMNAS DEL EXCEL PRINCIPAL
# ==========================================
COL_ID = "ID"
COL_VIN = "VIN"
COL_CHASIS = "CHASIS"
COL_MODELO = "MODELO"
COL_FLOTA_VC = "FLOTA VC"
COL_FLOTA_VC_2 = "FLOTA VC 2"
COL_EJECUTIVO = "EJECUTIVO"
COL_RAZON_SOCIAL = "RAZÓN SOCIAL"
COL_RUT = "RUT"
COL_CDB = "CDB"
COL_CDB_FLOTA = "CDB FLOTA"
COL_FORMA_CONTRATO = "FORMA DE CONTRATO"
COL_TIPO_SERVICIO = "TIPO DE SERVICIO"
COL_ESTADO_COMERCIAL = "ESTADO COMERCIAL"
COL_ESTADO_ACTIVACION = "ESTADO DE ACTIVACIÓN ACTUAL"
COL_INICIO_CONTRATO = "INICIO CONTRATO"
COL_DURACION_MESES = "DURACIÓN (MESES)"
COL_TERMINO_CONTRATO = "TÉRMINO CONTRATO"
COL_ESTADO_CM = "ESTADO DEL CM"
COL_PERIODO_INTERNO = "PERIODO INTERNO"
COL_INDUSTRIA = "INDUSTRIA"
COL_ESTADO_ENTREGA = "ESTADO DE ENTREGA"
COL_FECHA_BAJA = "FECHA DE BAJA"
COL_ETAPA_GESTION = "ETAPA GESTIÓN"
COL_TIPO_FACTURACION = "TIPO DE FACTURACION"
COL_TIPO_CM = "TIPO DE CM"
COL_N_CONTRATO_3PC = "N CONTRATO 3PC"
COL_FECHA_INICIO_CM = "FECHA INICIO CM"
COL_FECHA_TERMINO_CM = "FECHA TERMINO CM"
COL_PAGO_CM = "PAGO CM"

# ==========================================
# VALORES ESTÁNDAR Y ESTADOS ESPERADOS
# ==========================================
VALOR_MENSUAL = "MENSUAL"
ESTADO_ACTIVO = "Activo"
ESTADO_VENCIDO = "Vencido"
ESTADO_CONECTADO = "CONECTADO"
ESTADO_DESCONECTADO = "DESCONECTADO"
ESTADO_ACTIVANDO = "ACTIVANDO"
ESTADO_NO_ENTREGADO = "NO ENTREGADO"
ESTADO_SIN_FLOTA = "SIN FLOTA"
VALOR_ESTADO_COMERCIAL_VIGENTE = "VIGENTE"
VALOR_ESTADO_COMERCIAL_BAJA = "BAJA"
VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA = "BAJA SOLICITADA"
VALOR_ESTADO_COMERCIAL_VENCIDO = "VENCIDO"
VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE = "ACTIVACIÓN PENDIENTE"
VALOR_ESTADO_COMERCIAL_REVISAR = "REVISAR"
VALOR_ESTADO_COMERCIAL_RENOVADO = "RENOVADO"

# Estados de ESTADO COMERCIAL que "Marcar como Vencido" (Comercial ->
# Vencidos, 23-09-2026) puede corregir automaticamente a Vencido: solo los
# que representan "todavia no se reviso" (Vigente/Activación Pendiente
# quedaron asi por no actualizarse). BAJA, BAJA SOLICITADA y REVISAR quedan
# fuera a proposito (decision confirmada con el usuario): ya representan una
# decision de negocio tomada, no un olvido, aunque la fecha ya haya pasado.
ESTADOS_COMERCIAL_CORREGIBLES_A_VENCIDO = {
    VALOR_ESTADO_COMERCIAL_VIGENTE,
    VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE,
}
VALOR_ETAPA_GESTION_OPERACIONES = "OPERACIONES"
COL_CONTRATO_JUSTTIME = "CONTRATO CREADO EN JUSTTIME"
COL_FECHA_INICIO_FACT = "INICIO"
COL_FECHA_TERMINO_FACT = "TERMINO"

# Valores reales de TIPO DE FACTURACION confirmados contra PruebasFM.xlsx
# real (16-09-2026, lectura directa del Excel de producción -- no son datos
# de mock ni de tests). "PROVISION + CLIENTE"/"PROVISION + INTERNO" que
# aparecian en tests antiguos NO son valores reales de catalogo, son solo
# ejemplos ilustrativos de ese test; se descartan como catalogo.
VALOR_TIPO_FACT_SIN_REGISTRO = "SIN REGISTRO"
VALOR_TIPO_FACT_FACTURACION_MANUAL = "FACTURACIÓN MANUAL"
VALOR_TIPO_FACT_CLIENTE = "CLIENTE"
VALOR_TIPO_FACT_INTERNO = "INTERNO"
VALOR_TIPO_FACT_PROVISION_MAS = "PROVISION +"
VALOR_TIPO_FACT_CM = "CM"

# ==========================================
# MAPA DE TRADUCCIÓN ETL: INDUSTRIA
# ==========================================
INDUSTRIA_MAP = {
    'MINING': 'Minería',
    'MINERIA': 'Minería',
    'MINERÍA': 'Minería',
    'LARGA DISTANCIA': 'Larga Distancia',
    'FORESTAL': 'Forestal',
    'FOREST & PAPER': 'Forestal',
    'INDUSTRIAL': 'Industrial',
    'DISTRIBUCION': 'Distribución',
    'DISTRIBUCIÓN': 'Distribución',
    'BUILDING & CONSTRUCTION': 'Construcción',
    'CONSTRUCCION': 'Construcción',
    'CONSTRUCCIÓN': 'Construcción',
    'COMBUSTIBLES': 'Combustibles',
    'PETROLEUM & CHEMICAL': 'Combustibles',
    'MIXED CARGO': 'Carga Mixta',
    'SERVICIO': 'Servicio',
    'DAILY COMMODITIES': 'Bienes de Consumo Diario',
    'AGRICULTURE': 'Agricultura',
    'WASTE & RECYCLING': 'Residuos y Reciclaje',
    'PUBLIC SERVICE': 'Servicio Público'
}

# ==========================================
# MAPAS DE TRADUCCIÓN ETL: CATÁLOGOS COMERCIAL
# (mismo patrón que INDUSTRIA_MAP: solo se traducen
# los valores explícitamente listados; lo que no está
# mapeado se conserva sin modificar)
# ==========================================
TIPO_SERVICIO_MAP = {
    'BASICO': 'Basico',
    'FULL': 'Full',
    'FULL + CIV': 'Full + CIV',
    'MEDIO': 'Medio',
    'MEDIO + CIV': 'Medio + CIV',
}

FORMA_CONTRATO_MAP = {
    'CONVERSION': 'Conversion',
    'DEMO': 'Demo',
    'PROVISION': 'Provision',
    'PROVISION +': 'Provision +',
    'SIN CONTRATO': 'Sin Contrato',
    'TEST': 'Test',
    'VENTA': 'Venta',
    # Agregado 24-09-2026 junto con FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ:
    # "Revisar" es una fila real de la matriz entregada por Javiera pero no
    # tenía normalización propia (a diferencia del resto de valores de este
    # mapa) -- mismo criterio que ESTADO_COMERCIAL_MAP para "Revisar".
    'REVISAR': 'Revisar',
}

ESTADO_COMERCIAL_MAP = {
    'VIGENTE': 'Vigente',
    'VENCIDO': 'Vencido',
    'BAJA': 'Baja',
    'BAJA SOLICITADA': 'Baja Solicitada',
    'REVISAR': 'Revisar',
    # 20-10-2026: contrato reemplazado por uno nuevo (renovación); queda como historial
    'RENOVADO': 'Renovado',
    # 19-10-2026: "-" son unidades que nunca tuvieron el servicio (casi todas
    # Sin Contrato + No aplica). Fuera de la matriz de etapas, igual que antes.
    '-': 'Sin Servicio',
}

# Normaliza el formato de ESTADO DEL CM (contrato de mantenimiento) a un
# unico estandar en todo el sistema (PruebasFM/RM, Comercial y Contratos
# CM), sin importar si el dato llego en mayusculas (import 3PC) o mezclado
# a mano ('Running', 'RUNNING', etc.). No es el mismo campo que ESTADO_CASO
# de cm_bajas_service.py (ver ese modulo): este es el estado real del
# contrato, ese es el estado del caso de revision.
ESTADO_DEL_CM_MAP = {
    'RUNNING': 'Running',
    'EXPIRED': 'Expired',
    'TERMINATED': 'Terminated',
    'PENDIENTE': 'Pendiente',
    # Dato real detectado en PruebasFM (12 filas, 11-09-2026): alguien
    # escribio "Expirado" directamente en Excel, fuera del desplegable de
    # la app (que nunca ofrecio ese valor). Sin este alias, esas filas
    # quedaban "intactas" (ver clean()) y por lo tanto invisibles para
    # cm_bajas_service.detectar_casos_expired_actuales(), que compara
    # exactamente contra 'EXPIRED'.
    'EXPIRADO': 'Expired',
}

# Catalogo de CONTRATO CREADO EN JUSTTIME (30-09-2026, definido con el
# usuario): "Crear en JustTime" se unifica en "Pendiente" (ambos esperan que
# se agregue a JustTime) y las dos variantes de "Revisar pago" en una sola.
JUSTTIME_ESTADO_PENDIENTE = "Pendiente"
JUSTTIME_ESTADO_SI = "Si"
JUSTTIME_ESTADO_ELIMINAR = "Eliminar"
JUSTTIME_ESTADO_REVISAR_PAGO = "Revisar pago"
JUSTTIME_ESTADO_NO_APLICA = "-"
JUSTTIME_ESTADO_OPCIONES = [
    JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_ELIMINAR,
    JUSTTIME_ESTADO_REVISAR_PAGO, JUSTTIME_ESTADO_NO_APLICA,
]

# Variantes antiguas (texto libre del RM) -> estado del catalogo que se
# sugiere. NO se aplica sola: los datos se muestran tal como vienen y
# Javiera los corrige desde la pantalla JustTime (a pedido del usuario).
CONTRATO_JUSTTIME_MAP = {
    'CREAR EN JUSTTIME': JUSTTIME_ESTADO_PENDIENTE,
    'CREAR JUSTTIME': JUSTTIME_ESTADO_PENDIENTE,
    'ELIMINAR DE JUSTTIME': JUSTTIME_ESTADO_ELIMINAR,
    'ELIMINAR EN JUSTTIME': JUSTTIME_ESTADO_ELIMINAR,
    'REVISAR EL PAGO Y ELIMINAR DE JUSTTIME': JUSTTIME_ESTADO_REVISAR_PAGO,
    'REVISAR PAGO Y ELIMINAR DE JUSTTIME': JUSTTIME_ESTADO_REVISAR_PAGO,
    'REVISAR EL PAGO PROVISION Y LUEGO SACARLA DE JUSTTIME PARA COBRAR A CM': JUSTTIME_ESTADO_REVISAR_PAGO,
}

# ==========================================
# TIPO DE FACTURACION: presentación en ComboBox del nuevo formulario
# (ComercialAgregarDialog, pestaña "JustTime & CM") vs. valor real que se
# guarda en PruebasFM. Confirmado contra el Excel real (ver constantes
# VALOR_TIPO_FACT_* arriba): NO agregar valores que no esten en esta lista,
# el catalogo real no tiene mas variantes que estas.
# ==========================================
TIPO_FACTURACION_DISPLAY_MAP = {
    VALOR_TIPO_FACT_CLIENTE: 'Cliente',
    VALOR_TIPO_FACT_INTERNO: 'Interno',
    VALOR_TIPO_FACT_PROVISION_MAS: 'Provision +',
    VALOR_TIPO_FACT_CM: 'CM',
    VALOR_TIPO_FACT_SIN_REGISTRO: 'Sin registro',
    VALOR_TIPO_FACT_FACTURACION_MANUAL: 'Facturación Manual',
    '-': '-',
}
# Reverso del mapa anterior: texto amigable del combo -> valor real a guardar.
TIPO_FACTURACION_DISPLAY_A_REAL = {v: k for k, v in TIPO_FACTURACION_DISPLAY_MAP.items()}

# Catálogo de los combos del formulario de unidad (comercial_agregar.py),
# compartido por Comercial y las pantallas que abren ese mismo formulario.
# "Revisar" en FORMA DE CONTRATO (24-09-2026): fila real de
# FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.
DROPDOWN_OPTIONS_UNIDAD = {
    'MODELO': ["-", "FH", "FHE", "FHL", "FM", "FME", "FML", "FMX", "FL", "FE", "VM", "N/A"],
    'FORMA DE CONTRATO': ["-", "CMB", "CMG", "CMS", "Conversion", "Demo", "Provision", "Provision +", "Revisar", "Sin Contrato", "Test", "Venta"],
    'TIPO DE SERVICIO': ["-", "Basico", "Full", "Full + CIV", "Medio", "Medio + CIV"],
    'ESTADO DE ACTIVACIÓN ACTUAL': ["Activando", "Conectado", "Desconectado", "No aplica", "No entregado", "Sin flota"],
    'ESTADO COMERCIAL': ["Vigente", "Vencido", "Baja", "Baja Solicitada", "Revisar", "Activación Pendiente"],
    'ESTADO DEL CM': ["Running", "Expired", "Pendiente", "Terminated", "-"],
}

# Valores de TIPO DE FACTURACION que van a JustTime: habilitan el bloque
# JustTime en ComercialAgregarDialog y definen las inconsistencias de la
# pantalla JustTime. Actualizado 05-10-2026 con la confirmación de Javiera:
# Facturación Manual NO va a JustTime (el 30-09-2026 se había asumido que sí);
# Provisión + tampoco.
TIPO_FACTURACION_HABILITA_JUSTTIME = {
    VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_INTERNO,
}
# Valor de TIPO DE FACTURACION que habilita el bloque de Contrato de
# Mantenimiento (CM) en ComercialAgregarDialog.
TIPO_FACTURACION_HABILITA_CM = {VALOR_TIPO_FACT_CM}

# ==========================================
# CONTRATO DE MANTENIMIENTO (CM): catalogos compartidos entre Contratos CM
# (src/ui/contratos.py) y ComercialAgregarDialog (src/ui/comercial_agregar.py)
# -- centralizados aqui para no duplicar el catalogo en dos pantallas.
# ==========================================
TIPO_CM_OPCIONES = ["Gold", "Blue", "Silver", "Current Contract Type", "-"]
ESTADO_CM_OPCIONES = ["Running", "Expired", "Pendiente", "Terminated", "-"]
# Estado interno (no viene del 3PC): el cliente no pagó y se espera la respuesta de quien administra el CM
ESTADO_CM_PENDIENTE = "Pendiente"
# Estados que mantienen abierto el caso de Oportunidades CM (ver cm_bajas_service)
ESTADOS_CM_SIN_PAGO = ("EXPIRED", "PENDIENTE")

# Relacion FORMA DE CONTRATO -> TIPO DE CM (nueva regla de negocio,
# 16-09-2026, definida con Javiera para ComercialAgregarDialog): cuando
# FORMA DE CONTRATO es uno de estos codigos de contrato de mantenimiento,
# TIPO DE CM se autocompleta al tipo correspondiente. No reemplaza la
# posibilidad de elegir TIPO DE CM manualmente despues.
FORMA_CONTRATO_TIPO_CM_MAP = {
    'CMG': 'Gold',
    'CMB': 'Blue',
    'CMS': 'Silver',
}

# Inversa de FORMA_CONTRATO_TIPO_CM_MAP (30-09-2026, a pedido explícito para
# contratos.py::importar_excel_javiera): a partir del TIPO DE CM que trae el
# Excel de Javiera (Gold/Blue/Silver), la FORMA DE CONTRATO correspondiente.
# Un TIPO DE CM que no esté aquí (ej. "-" o "Current Contract Type") no
# fuerza ningún cambio de FORMA DE CONTRATO.
TIPO_CM_FORMA_CONTRATO_MAP = {v: k for k, v in FORMA_CONTRATO_TIPO_CM_MAP.items()}

# ==========================================
# MATRIZ DE NEGOCIO: FORMA DE CONTRATO -> TIPO DE FACTURACION válidos
# (24-09-2026, matriz entregada por Javiera -- ver captura compartida con
# el usuario). Generaliza la regla anterior, que solo cubría CMB/CMG/CMS ->
# CM a mano en comercial_agregar.py (_sincronizar_tipo_facturacion_con_forma_contrato).
# Claves y valores en MAYÚSCULAS: el valor REAL que se guarda en PruebasFM
# (mismo criterio que VALOR_TIPO_FACT_*/VALOR_ESTADO_COMERCIAL_*), no el
# texto amigable que muestra el combo (TIPO_FACTURACION_DISPLAY_MAP). Una
# FORMA DE CONTRATO que no aparezca aquí (valor legado/no reconocido) no se
# restringe -- mismo criterio que el resto de las matrices de negocio del
# sistema (ver ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ).
# ==========================================
FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ = {
    'CMB': {VALOR_TIPO_FACT_CM},
    'CMG': {VALOR_TIPO_FACT_CM},
    'CMS': {VALOR_TIPO_FACT_CM},
    'CONVERSION': {VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_FACTURACION_MANUAL},
    'DEMO': {VALOR_TIPO_FACT_SIN_REGISTRO},
    'PROVISION': {VALOR_TIPO_FACT_INTERNO},
    'PROVISION +': {VALOR_TIPO_FACT_PROVISION_MAS},
    'REVISAR': {VALOR_TIPO_FACT_SIN_REGISTRO},
    'SIN CONTRATO': {VALOR_TIPO_FACT_SIN_REGISTRO},
    'TEST': {VALOR_TIPO_FACT_SIN_REGISTRO},
    'VENTA': {VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_FACTURACION_MANUAL},
}

# ==========================================
# MATRIZ DE NEGOCIO: (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) -> ETAPA
# GESTIÓN (21-09-2026, reemplaza a ESTADO_COMERCIAL_ETAPA_MAP, que solo
# miraba ESTADO COMERCIAL). Tercera prioridad del cálculo de ETAPA GESTIÓN;
# la primera y segunda prioridad (TIPO DE FACTURACION = SIN REGISTRO o
# FACTURACIÓN MANUAL -> COMERCIAL) se resuelven en DataFrameFormatter antes
# de aplicar esta matriz y NO cambiaron (confirmado con el usuario). El
# valor CLIENTE queda retirado del catálogo: la matriz solo produce
# COMERCIAL u OPERACIONES.
# ==========================================
# NO APLICA -> COMERCIAL (28-09-2026, matriz corregida por el usuario junto
# con Javiera): antes era OPERACIONES, pero ACTIVACIÓN PENDIENTE (que
# comparte esta fila) ya venía como COMERCIAL, así que las dos filas
# quedaban inconsistentes entre sí sin razón de negocio. No cambia ninguna
# pantalla (filtrar_por_gestionar ya captura "No aplica" sin mirar ETAPA
# GESTIÓN), pero evita que "Vista Completa" marque como contradicción
# unidades VIGENTE + No aplica.
_FILA_OPERACIONES_SALVO_CONECTADO = {
    'ACTIVANDO': 'OPERACIONES', 'CONECTADO': 'COMERCIAL', 'DESCONECTADO': 'OPERACIONES',
    'NO APLICA': 'COMERCIAL', 'NO ENTREGADO': 'OPERACIONES', 'SIN FLOTA': 'OPERACIONES',
}
# BAJA/BAJA SOLICITADA (22-09-2026, matriz actualizada por el usuario): a
# diferencia de la version anterior (solo CONECTADO -> OPERACIONES, el resto
# COMERCIAL), ahora ACTIVANDO tambien -> OPERACIONES. Reemplaza a
# _FILA_COMERCIAL_SALVO_CONECTADO (ya no queda ninguna fila que sea
# "COMERCIAL salvo Conectado").
_FILA_OPERACIONES_ACTIVANDO_O_CONECTADO = {
    'ACTIVANDO': 'OPERACIONES', 'CONECTADO': 'OPERACIONES', 'DESCONECTADO': 'COMERCIAL',
    'NO APLICA': 'COMERCIAL', 'NO ENTREGADO': 'COMERCIAL', 'SIN FLOTA': 'COMERCIAL',
}
ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ = {
    'ACTIVACION PENDIENTE': _FILA_OPERACIONES_SALVO_CONECTADO,
    # Alias con tilde: .upper() no le quita el acento a "Activación", así que
    # el valor que ofrece el combo (Gestión de Unidades, 16-09-2026) no
    # calzaba con la clave sin tilde de arriba. Se agrega en vez de reemplazar
    # la clave existente por si algún dato histórico ya trae la variante sin
    # tilde (ej. digitado a mano en RM_JAVI).
    'ACTIVACIÓN PENDIENTE': _FILA_OPERACIONES_SALVO_CONECTADO,
    'BAJA': _FILA_OPERACIONES_ACTIVANDO_O_CONECTADO,
    'BAJA SOLICITADA': _FILA_OPERACIONES_ACTIVANDO_O_CONECTADO,
    # REVISAR (25-09-2026, matriz actualizada por el usuario): ACTIVANDO
    # pasó de OPERACIONES a COMERCIAL -- toda la fila es COMERCIAL ahora,
    # sin excepciones. Antes ACTIVANDO era la única celda OPERACIONES de
    # esta fila, lo que dejaba unidades REVISAR+ACTIVANDO visibles en
    # Comercial -> Vencidos en vez de Por gestionar (ver
    # comercial_services._mask_revisar_hacia_comercial, que lee esta misma
    # matriz para decidir esa exclusión/inclusión -- no requiere más cambios
    # de código, solo este dato).
    'REVISAR': {
        'ACTIVANDO': 'COMERCIAL', 'CONECTADO': 'COMERCIAL', 'DESCONECTADO': 'COMERCIAL',
        'NO APLICA': 'COMERCIAL', 'NO ENTREGADO': 'COMERCIAL', 'SIN FLOTA': 'COMERCIAL',
    },
    'VENCIDO': {
        'ACTIVANDO': 'COMERCIAL', 'CONECTADO': 'COMERCIAL', 'DESCONECTADO': 'COMERCIAL',
        'NO APLICA': 'COMERCIAL', 'NO ENTREGADO': 'COMERCIAL', 'SIN FLOTA': 'COMERCIAL',
    },
    'VIGENTE': _FILA_OPERACIONES_SALVO_CONECTADO,
}

# Version aplanada de la matriz de arriba, para el lookup vectorizado de
# pandas (ver comercial_services._calcular_etapa_gestion_esperada_vectorizado).
# Misma fuente de datos que ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ -- no se
# duplica el contenido, solo se aplana la estructura.
ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT = {
    f"{estado}||{activacion}": etapa
    for estado, fila in ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ.items()
    for activacion, etapa in fila.items()
}

# Color del texto (en negrita) de 'ETAPA GESTIÓN', usado en la tabla de
# Unidades (general.py) y en el indicador de ComercialAgregarDialog
# (comercial_agregar.py). Movido aquí desde general.py (16-09-2026) para que
# ambos lo reutilicen sin duplicar la paleta ni generar un import circular
# (general.py importa ComercialAgregarDialog). COMERCIAL/OPERACIONES
# reutilizan tal cual los colores que MODULE_COLORS (src/theme/colors.py) ya
# asigna a esas pantallas. CLIENTE retirado del catálogo (21-09-2026, ver
# matriz de arriba).
ETAPA_GESTION_COLORES = {
    'COMERCIAL': MODULE_COLORS['Comercial'],
    'OPERACIONES': MODULE_COLORS['Operaciones'],
}

# Último pago positivo del 3PC y su fecha. PAGO CM queda en 0 cuando la unidad no pagó
# en el mes del archivo; estas dos conservan el pago anterior como histórico. La
# columna se crea sola al guardar (ver core/columnas_opcionales.py).
COL_ULTIMO_PAGO_CM = "ULTIMO PAGO CM"
COL_FECHA_ULTIMO_PAGO_CM = "FECHA ULTIMO PAGO CM"
COLUMNAS_OPCIONALES_RM = [COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM]
