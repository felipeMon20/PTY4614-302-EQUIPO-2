"""Logica de negocio y preparacion de correos: agrupacion de destinatarios,
validaciones, y configuracion centralizada de plantillas (asunto + cuerpo
HTML + imagenes CID). No depende de PyQt ni de widgets: se puede probar con
unittest sin levantar la UI."""

import os

import pandas as pd

from src.services.mail_templates import (
    construir_cuerpo_conoce_volvo_connect,
    construir_cuerpo_reactivacion,
    construir_cuerpo_continuidad_cm,
    construir_cuerpo_bienvenida,
    construir_cuerpo_activacion,
    construir_cuerpo_capacitacion,
    construir_cuerpo_seguimiento_uso,
    construir_cuerpo_revision_periodica,
    construir_cuerpo_vencimiento,
    construir_cuerpo_seguimiento_renovacion,
    construir_cuerpo_renovacion_confirmada,
    construir_cuerpo_comunicado,
    construir_cuerpo_baja,
    construir_cuerpo_cambio_nivel,
)

# Nombre de la plantilla que Comercial preselecciona en "Gestionar CM" (ver
# ComercialModule._on_accion_cm_enviar_correo_clicked): unica fuente de
# verdad para no repetir el literal en comercial.py.
PLANTILLA_AVISO_VENCIMIENTO = "Aviso de Vencimiento"
# Plantillas que Comercial preselecciona en "Recuperar clientes" y en "Nuevas
# oportunidades".
PLANTILLA_REACTIVACION = "Reactivación"
PLANTILLA_CONOCE_VOLVO_CONNECT = "Conoce Volvo Connect"

# Configuracion unica de cada plantilla predefinida (todo lo que antes estaba
# repartido entre el dict "asuntos" de MailDialog._on_plantilla_changed y el
# if/elif de OutlookSenderThread.run()). "constructor" recibe el dict de
# destinatario ya agrupado (con 'flota', 'chasis_list', 'grupos_plan') y
# devuelve el HTML. "imagenes" es la lista (filename, cid) a incrustar, en
# el mismo orden que se adjuntaba antes.
def _imagenes(hero=None):
    """Logo blanco de la barra (todas) y, de Conoce Volvo Connect a Revisión
    Periódica, la imagen principal."""
    return ([hero] if hero else []) + [("logo_volvo_blanco.png", "logo_volvo_blanco")]


_FOTO_CAMION_TABLET = ("foto_camion_tablet.jpg", "foto_camion_tablet")
_FOTO_APP_CELULAR = ("foto_app_celular.jpg", "foto_app_celular")
_FOTO_HOMBRE_COMPUTADOR = ("foto_hombre_computador.jpg", "foto_hombre_computador")
_FOTO_MUJER_PANTALLAS = ("foto_mujer_pantallas.jpg", "foto_mujer_pantallas")
_FOTO_CAMION_PUENTE = ("foto_camion_puente.jpg", "foto_camion_puente")
_FOTO_EQUIPO_APOYO = ("foto_equipo_apoyo.jpg", "foto_equipo_apoyo")

# El orden de este dict es el del selector de plantillas de MailDialog.
PLANTILLAS = {
    PLANTILLA_CONOCE_VOLVO_CONNECT: {
        "asunto": "Conoce Volvo Connect | Aprovecha la información de tu flota",
        "constructor": lambda dest: construir_cuerpo_conoce_volvo_connect(dest['flota'], correo_equipo=dest.get('correo_equipo', '')),
        "imagenes": _imagenes(_FOTO_CAMION_TABLET),
    },
    PLANTILLA_REACTIVACION: {
        "asunto": "Reactiva Volvo Connect | Más que información para tu flota",
        "constructor": lambda dest: construir_cuerpo_reactivacion(dest['flota'], correo_equipo=dest.get('correo_equipo', '')),
        "imagenes": _imagenes(_FOTO_HOMBRE_COMPUTADOR),
    },
    "Continuidad post CM": {
        "asunto": "Mantén tu flota conectada | Continuidad Volvo Connect",
        "constructor": lambda dest: construir_cuerpo_continuidad_cm(dest['flota'], correo_equipo=dest.get('correo_equipo', '')),
        "imagenes": _imagenes(_FOTO_MUJER_PANTALLAS),
    },
    "Bienvenida": {
        "asunto": "¡Bienvenido a Volvo Connect! Comienza a gestionar tu flota",
        "constructor": lambda dest: construir_cuerpo_bienvenida(dest['flota']),
        "imagenes": [_FOTO_CAMION_PUENTE],
        "adjuntos": "bienvenida",
    },
    "Activación": {
        "asunto": "¡Tu unidad fue incorporada a Volvo Connect!",
        "constructor": lambda dest: construir_cuerpo_activacion(dest['flota'], dest['grupos_plan'], dest.get('unidades')),
        "imagenes": _imagenes(_FOTO_APP_CELULAR),
    },
    "Capacitación": {
        "asunto": "¡Aprende a aprovechar al máximo Volvo Connect!",
        "constructor": lambda dest: construir_cuerpo_capacitacion(dest['flota']),
        "imagenes": _imagenes(_FOTO_EQUIPO_APOYO),
        "adjuntos": "capacitacion",
    },
    "Seguimiento de Uso": {
        "asunto": "¿Cómo ha sido tu experiencia con Volvo Connect?",
        "constructor": lambda dest: construir_cuerpo_seguimiento_uso(dest['flota']),
        "imagenes": _imagenes(_FOTO_EQUIPO_APOYO),
    },
    "Revisión Periódica": {
        "asunto": "Revisión periódica de unidades en Volvo Connect",
        "constructor": lambda dest: construir_cuerpo_revision_periodica(dest['flota']),
        "imagenes": _imagenes(_FOTO_HOMBRE_COMPUTADOR),
    },
    PLANTILLA_AVISO_VENCIMIENTO: {
        "asunto": "Tu membresía Volvo Connect está próxima a vencer",
        "constructor": lambda dest: construir_cuerpo_vencimiento(dest['flota'], dest['unidades'], correo_equipo=dest.get('correo_equipo', '')),
        "imagenes": _imagenes(),
    },
    "Seguimiento de Renovación": {
        "asunto": "¡Tu flota puede seguir conectada con Volvo Connect!",
        "constructor": lambda dest: construir_cuerpo_seguimiento_renovacion(dest['flota'], dest['unidades'], correo_equipo=dest.get('correo_equipo', '')),
        "imagenes": _imagenes(),
    },
    "Renovación Confirmada": {
        "asunto": "¡Tu renovación de Volvo Connect está confirmada!",
        "constructor": lambda dest: construir_cuerpo_renovacion_confirmada(dest['flota'], dest['unidades']),
        "imagenes": _imagenes(),
    },
    "Confirmación de Baja": {
        "asunto": "Confirmación de baja de servicio",
        "constructor": lambda dest: construir_cuerpo_baja(dest['flota'], dest['unidades']),
        "imagenes": _imagenes(),
    },
    "Cambio de Nivel": {
        "asunto": "¡Tu nivel de servicio Volvo Connect ha sido actualizado!",
        "constructor": lambda dest: construir_cuerpo_cambio_nivel(dest['flota'], dest['unidades']),
        "imagenes": _imagenes(),
    },
}


IMAGENES_PERSONALIZADO = _imagenes()


def cuerpo_personalizado(asunto, mensaje):
    """HTML del correo "Personalizado": el mensaje escrito a mano dentro de la
    barra azul con el logo (imágenes en IMAGENES_PERSONALIZADO)."""
    return construir_cuerpo_comunicado(asunto, mensaje)


def formatear_fecha(valor):
    """Fecha como dd-mm-aaaa para mostrar en un correo; '' si no hay dato."""
    if valor is None or valor != valor:
        return ''
    if hasattr(valor, 'strftime'):
        return valor.strftime('%d-%m-%Y')
    texto = str(valor).strip()
    return '' if texto.lower() in ('nan', 'nat', 'none') else texto


def nivel_anterior(vin, plan_actual, df_logs, df_comercial):
    """Nivel de servicio que tenía la unidad antes del actual; '' si no se
    sabe. Primero el último cambio de TIPO DE SERVICIO de ese VIN en el
    historial de modificaciones (LogApp.csv, columnas por posición: fecha,
    módulo, VIN, campo, valor anterior, valor nuevo); si no hay, el
    TIPO DE SERVICIO del contrato previo del mismo VIN (cambio hecho con un
    contrato nuevo, que no deja cambio de campo en el log)."""
    vin = str(vin).strip().upper()
    actual = str(plan_actual).strip().upper()

    if df_logs is not None and not df_logs.empty and df_logs.shape[1] >= 6:
        c = df_logs.columns
        coincide = df_logs[
            (df_logs[c[3]].astype(str).str.strip().str.upper() == 'TIPO DE SERVICIO')
            & (df_logs[c[2]].astype(str).str.strip().str.upper() == vin)
            & (df_logs[c[5]].astype(str).str.strip().str.upper() == actual)
        ]
        if not coincide.empty:
            anterior = str(coincide.sort_values(c[0]).iloc[-1][c[4]]).strip()
            if anterior and anterior.upper() not in ('-', 'NAN', actual):
                return anterior

    if df_comercial is not None and not df_comercial.empty and {'VIN', 'ID', 'TIPO DE SERVICIO'} <= set(df_comercial.columns):
        contratos = df_comercial[df_comercial['VIN'].astype(str).str.strip().str.upper() == vin]
        if len(contratos) >= 2:
            contratos = contratos.assign(_orden=pd.to_numeric(contratos['ID'], errors='coerce')).sort_values('_orden')
            previo = str(contratos.iloc[-2]['TIPO DE SERVICIO']).strip()
            if previo and previo.upper() not in ('-', 'NAN', actual):
                return previo
    return ''


def archivos_adjuntos(carpeta, assets_dir):
    """Rutas de los archivos que hay en assets/adjuntos/<carpeta> (ej. la
    cápsula de aprendizaje), en orden alfabético. Lista vacía si la plantilla
    no lleva adjuntos o la carpeta no existe o está vacía."""
    if not carpeta:
        return []
    base = os.path.join(assets_dir, "adjuntos", carpeta)
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, f) for f in sorted(os.listdir(base)) if os.path.isfile(os.path.join(base, f))]


def obtener_configuracion_plantilla(nombre_plantilla):
    """Config (asunto, constructor, imagenes) de una plantilla por nombre
    exacto (el mismo texto del combo de MailDialog), o None si no es una de
    las plantillas predefinidas (ej. "Personalizado (Escribir desde cero)")."""
    return PLANTILLAS.get(nombre_plantilla)


def agrupar_destinatarios(filas):
    """Agrupa filas simples (vin, flota, plan, correo) por flota+correo,
    acumulando chasis y planes. Produce la estructura ('chasis_list',
    'grupos_plan', 'unidades') que consumen los constructores de PLANTILLAS.
    No recibe widgets ni depende de PyQt: filas es una lista de dicts con
    esas cuatro claves (y 'vence' opcional), ya validadas por quien las llama
    (ver validar_destinatarios)."""
    dest_dict = {}
    for fila in filas:
        vin = fila['vin']
        flota = fila['flota']
        plan = fila['plan']
        correo = fila['correo']
        chasis = vin[-7:]

        key = f"{flota}_{correo}"
        if key not in dest_dict:
            dest_dict[key] = {
                'flota': flota, 'nombre': flota, 'correo': correo,
                'chasis_list': [], 'grupos_plan': {}, 'unidades': []
            }

        dest_dict[key]['chasis_list'].append(chasis)
        dest_dict[key]['unidades'].append({
            'chasis': chasis, 'plan': plan, 'vence': fila.get('vence', ''),
            'baja': fila.get('baja', ''), 'anterior': fila.get('anterior', ''),
        })
        if plan not in dest_dict[key]['grupos_plan']:
            dest_dict[key]['grupos_plan'][plan] = []
        dest_dict[key]['grupos_plan'][plan].append(chasis)

    return list(dest_dict.values())


def validar_destinatarios(filas):
    """Devuelve el VIN del primer camion sin correo asignado, o None si
    todas las filas son validas. Como mostrar el aviso (QMessageBox) es
    responsabilidad de MailDialog, no de este servicio."""
    for fila in filas:
        if not fila['correo']:
            return fila['vin']
    return None
