"""Logica de negocio y preparacion de correos: agrupacion de destinatarios,
validaciones, y configuracion centralizada de plantillas (asunto + cuerpo
HTML + imagenes CID). No depende de PyQt ni de widgets: se puede probar con
unittest sin levantar la UI."""

from src.services.mail_templates import (
    construir_cuerpo_bienvenida,
    construir_cuerpo_activacion,
    construir_cuerpo_cancelacion,
    construir_cuerpo_vencimiento,
    construir_cuerpo_crear_cuenta,
    construir_cuerpo_capacitacion,
    construir_cuerpo_revision_periodica,
)

# Nombre de la plantilla que Comercial preselecciona en "Gestionar CM" (ver
# ComercialModule._on_accion_cm_enviar_correo_clicked): unica fuente de
# verdad para no repetir el literal en comercial.py.
PLANTILLA_AVISO_VENCIMIENTO = "Aviso de Vencimiento"

# Configuracion unica de cada plantilla predefinida (todo lo que antes estaba
# repartido entre el dict "asuntos" de MailDialog._on_plantilla_changed y el
# if/elif de OutlookSenderThread.run()). "constructor" recibe el dict de
# destinatario ya agrupado (con 'flota', 'chasis_list', 'grupos_plan') y
# devuelve el HTML. "imagenes" es la lista (filename, cid) a incrustar, en
# el mismo orden que se adjuntaba antes.
PLANTILLAS = {
    "Bienvenida": {
        "asunto": "Bienvenido a la comunidad Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_bienvenida(dest['flota']),
        "imagenes": [
            ("logo_empresa.png", "logo_empresa"),
            ("camiones-demo.png", "camiones-demo"),
            ("image002.gif", "image002"),
        ],
    },
    "Crear Cuenta": {
        "asunto": "Activación de cuenta Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_crear_cuenta(dest['flota']),
        "imagenes": [
            ("logo_empresa.png", "logo_empresa"),
            ("image002.gif", "image002"),
        ],
    },
    "Capacitación": {
        "asunto": "Capacitación personalizada: Optimiza tu uso de Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_capacitacion(dest['flota']),
        "imagenes": [
            ("logo_empresa.png", "logo_empresa"),
            ("camiones-demo.png", "camiones-demo"),
            ("image002.gif", "image002"),
        ],
    },
    "Activación": {
        "asunto": "Activación de unidades en Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_activacion(dest['flota'], dest['grupos_plan']),
        "imagenes": [
            ("imagen_Activacion.png", "imagen_activacion"),
        ],
    },
    "Revisión Periódica": {
        "asunto": "Revisión periódica de unidades en Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_revision_periodica(dest['flota']),
        "imagenes": [
            ("Imagen_revision.jpg", "imagen_revision"),
        ],
    },
    PLANTILLA_AVISO_VENCIMIENTO: {
        "asunto": "Información sobre la renovación de servicios Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_vencimiento(dest['flota'], dest['grupos_plan']),
        "imagenes": [
            ("logo_empresa.png", "logo_empresa"),
            ("image002.gif", "image002"),
        ],
    },
    "Cancelación": {
        "asunto": "Cancelación de contrato de servicios Servicios Conectados",
        "constructor": lambda dest: construir_cuerpo_cancelacion(dest['flota'], dest['chasis_list']),
        "imagenes": [],
    },
}


def obtener_configuracion_plantilla(nombre_plantilla):
    """Config (asunto, constructor, imagenes) de una plantilla por nombre
    exacto (el mismo texto del combo de MailDialog), o None si no es una de
    las plantillas predefinidas (ej. "Personalizado (Escribir desde cero)")."""
    return PLANTILLAS.get(nombre_plantilla)


def agrupar_destinatarios(filas):
    """Agrupa filas simples (vin, flota, plan, correo) por flota+correo,
    acumulando chasis y planes. Produce la estructura ('chasis_list',
    'grupos_plan') que consumen los constructores de PLANTILLAS. No recibe
    widgets ni depende de PyQt: filas es una lista de dicts con esas cuatro
    claves, ya validadas por quien las llama (ver validar_destinatarios)."""
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
                'chasis_list': [], 'grupos_plan': {}
            }

        dest_dict[key]['chasis_list'].append(chasis)
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
