import html

PLANES_CONFIG = {
    "BASICO": {"nombre": "Básico", "incluye": ["Posicionamiento", "Consumo de Combustible"]},
    "MEDIO": {"nombre": "Medio", "incluye": ["Posicionamiento", "Consumo de Combustible", "Datos del Motor"]},
    "FULL": {"nombre": "Full", "incluye": ["Posicionamiento", "Consumo de Combustible", "Datos del Motor", "Comportamiento del Conductor"]},
    "MEDIO + CIV": {"nombre": "Medio + CIV", "incluye": ["Posicionamiento", "Consumo", "Motor", "CIV"]},
    "FULL + CIV": {"nombre": "Full + CIV", "incluye": ["Posicionamiento", "Consumo", "Motor", "Conductor", "CIV"]}
}

def construir_cuerpo_bienvenida(razon_social):
    url_plataforma = "https://example.com/login"
    capacitacion_url = "https://example.com/capacitacion"

    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">
                        Bienvenido a Servicios Conectados 🚚
                    </td></tr>
                    <tr><td align="center" style="padding:28px 28px 8px 28px;">
                        <img src="cid:camiones-demo" width="620" style="display:block; width:100%; max-width:620px; border:0; border-radius:10px;" alt="Servicios Conectados">
                    </td></tr>
                    <tr><td style="padding:10px 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;"><b>Estimado,</b></p>
                        <p style="margin:0 0 16px 0;">Esperamos que usted y su equipo se encuentren muy bien.</p>
                        <p style="margin:0 0 16px 0;">En nombre de todo el equipo de <b>Servicios Conectados</b>, le damos la más cordial bienvenida.</p>
                        <p style="margin:0 0 16px 0;">Su confianza en nosotros es invaluable. Queremos que sepa que nuestro <b>compromiso va más allá de un servicio</b>, por eso nos enfocamos en acompañarlo en cada momento y en aportar valor real a sus operaciones.</p>
                        <p style="margin:0 0 16px 0;">Nuestro objetivo es que obtenga la mejor experiencia posible con la plataforma, maximizando los beneficios y logrando los resultados que espera.</p>
                        <p style="margin:0 0 16px 0;">Para ello, hemos dispuesto un espacio para brindarle una <b>capacitación técnica personalizada</b>, en la que nos enfocaremos en:</p>
                        <p style="margin:0 0 12px 0;">• <b>Dominio de herramientas:</b> Profundizaremos en las funciones que más utilizas.</p>
                        <p style="margin:0 0 12px 0;">• <b>Configuración avanzada:</b> Ajustaremos la plataforma según tus necesidades actuales.</p>
                        <p style="margin:0 0 12px 0;">• <b>Resolución de dudas:</b> Espacio para despejar consultas surgidas en estos meses.</p>
                        <p style="margin:0 0 18px 0;">• <b>Mejores prácticas:</b> Consejos clave para sacar el máximo provecho.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:20px 32px 8px 32px;">
                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                            <tr><td bgcolor="#003057" style="background-color:#003057; border-radius:10px; padding:14px 28px;">
                                <a href="{url_plataforma}" target="_blank" style="font-size:15px; font-weight:bold; color:#ffffff !important; text-decoration:none !important; display:inline-block; background-color:#003057;">
                                    Ingresar a Servicios Conectados
                                </a>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 20px 32px; font-size:13px; line-height:1.6; color:#4b5563;">
                        Si al presionar el botón no carga, <a href="{url_plataforma}" target="_blank" style="color:#005b96; font-weight:bold; text-decoration:none;">haga clic aquí</a>.
                    </td></tr>
                    <tr><td align="center" style="padding:8px 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 20px 6px 20px; font-size:28px; line-height:28px;">📅</td></tr>
                            <tr><td align="center" style="padding:4px 28px 0 28px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.4; font-weight:bold; color:#1f2937;">
                                ¿Qué día y hora le resultarían convenientes para realizar esta sesión?
                            </td></tr>
                            <tr><td align="center" style="padding:6px 28px 18px 28px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#4b5563;">
                                En la página, en el botón <b>Inscríbete aquí</b>, podrá agendar su capacitación.<br><br>
                                <a href="{capacitacion_url}" target="_blank" style="color:#005b96; font-weight:bold; text-decoration:none;">Ver fechas disponibles</a>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td style="padding:8px 32px 0 32px; font-size:14px; line-height:1.7; color:#222222;">
                        <p style="margin:0 0 16px 0;">Si requiere apoyo para comenzar a utilizar la plataforma o tiene dudas sobre sus funcionalidades, nuestro equipo estará disponible para asistirle.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 20px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requiere orientación sobre el uso de Servicios Conectados, puede responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:10px 32px 0 32px;">
                        <img src="cid:image002" width="560" style="display:block; width:100%; max-width:560px; border:0;" alt="Servicios Conectados">
                    </td></tr>
                    <tr><td style="padding:24px 32px 18px 32px; font-size:11px; line-height:1.6; color:#6b7280;">
                        <p style="margin:0 0 10px 0;">Saludos,</p>
                        <p style="margin:0 0 10px 0;"><b>Equipo Servicios Conectados Chile</b></p>
                        <p style="margin:0;"><b>Empresa Demo</b><br>Servicios Conectados | Optimización de Costos de Transporte &amp; Productividad | Soluciones de Transporte de Carga<br>T. +56 9 0000 0000<br>Av. Ejemplo 1234 | Ciudad Ejemplo | Chile<br>contacto@example.com<br>www.example.com</p>
                    </td></tr>
                    <tr><td style="padding:0 32px 28px 32px;">
                        <img src="cid:logo_empresa" width="120" style="display:block; border:0;" alt="Empresa Demo Logo">
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def _bloque_plan_activacion(plan_excel: str, chasis_list: list[str]) -> str:
    key = str(plan_excel).strip().upper()
    plan_info = PLANES_CONFIG.get(key, {"nombre": plan_excel, "incluye": []})

    lista_chasis_html = "".join(f"<li style='margin-bottom:6px;'>{html.escape(str(chasis).strip())}</li>" for chasis in chasis_list if str(chasis).strip())
    lista_datos_html = "".join(f"<li style='margin-bottom:4px;'>{html.escape(str(item))}</li>" for item in plan_info["incluye"])
    
    return f"""
    <tr><td style="padding:0 32px 18px 32px; font-size:14px; line-height:1.75; color:#222222;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #d7dde5; background-color:#f8fafc; border-radius:8px;">
            <tr><td style="padding:16px 18px;">
                <p style="margin:0 0 10px 0;"><b>Plan {html.escape(str(plan_info['nombre']))}</b></p>
                <p style="margin:0 0 10px 0;">Unidades activadas en este plan:</p>
                <ul style="margin:0 0 14px 20px; padding:0;">{lista_chasis_html}</ul>
                <p style="margin:0 0 8px 0;">Este plan permite visualizar información de:</p>
                <ul style="margin:0 0 0 20px; padding:0;">{lista_datos_html}</ul>
            </td></tr>
        </table>
    </td></tr>
    """

def construir_cuerpo_activacion(razon_social: str, grupos_plan: dict[str, list[str]]) -> str:
    razon_social_html = html.escape(str(razon_social).strip())
    bloques_planes = "".join(_bloque_plan_activacion(plan, chasis_list) for plan, chasis_list in grupos_plan.items())

    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">
                        Activación de unidades en Servicios Conectados
                    </td></tr>
                    <tr><td align="center" style="padding:24px 32px 8px 32px;">
                        <img src="cid:imagen_activacion" width="520" style="display:block; width:100%; max-width:520px; height:auto; border:0; border-radius:10px;" alt="Activación Servicios Conectados">
                    </td></tr>
                    <tr><td style="padding:20px 32px 10px 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;">Estimados {razon_social_html},</p>
                        <p style="margin:0 0 16px 0;">Junto con saludar, informamos que las siguientes unidades ya se encuentran activadas en su cuenta de Servicios Conectados.</p>
                        <p style="margin:0 0 16px 0;">A continuación, detallamos las unidades agrupadas por plan, junto con el tipo de información y reportería disponible en cada caso:</p>
                    </td></tr>
                    {bloques_planes}
                    <tr><td style="padding:0 32px 10px 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;">Si requieren apoyo para revisar la información o resolver dudas sobre el uso de Servicios Conectados, quedamos a su disposición.</p>
                        <p style="margin:24px 0 0 0;">Saludos cordiales,</p>
                        <p style="margin:8px 0 0 0;"><b>Equipo Servicios Conectados Chile</b></p>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 24px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requieren asistencia adicional, pueden responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def construir_cuerpo_cancelacion(razon_social: str, chasis_list: list[str]) -> str:
    razon_social_html = html.escape(str(razon_social).strip())
    lista_chasis_html = "".join(f"<li style='margin-bottom:6px;'>{html.escape(str(chasis).strip())}</li>" for chasis in chasis_list if str(chasis).strip())

    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">
                        Cancelacion de contrato de servicios Servicios Conectados
                    </td></tr>
                    <tr><td style="padding:28px 32px 12px 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;">Estimados {razon_social_html},</p>
                        <p style="margin:0 0 16px 0;">Junto con saludar, por medio del presente informamos la cancelación del contrato de servicios Servicios Conectados para las siguientes unidades.</p>
                        <ul style="margin:0 0 18px 20px; padding:0;">{lista_chasis_html}</ul>
                        <p style="margin:0 0 16px 0;">La presente cancelación se efectúa por acuerdo entre ambas partes o bien por vencimiento del periodo de servicio sin respuesta, respecto de unidades con planes activos.</p>
                        <p style="margin:24px 0 0 0;">Saludos cordiales,</p>
                        <p style="margin:8px 0 0 0;"><b>Equipo Servicios Conectados Chile</b></p>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 24px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requieren asistencia adicional, pueden responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def _crear_tabla_plan_vencimiento(plan_excel: str) -> str:
    key = str(plan_excel).strip().upper()
    if key not in PLANES_CONFIG:
        plan = {"nombre": plan_excel, "incluye": [], "valor": "Consultar"}
    else:
        plan = PLANES_CONFIG[key]
        
    items = "".join(f"<li style='margin-bottom:4px;'>{i}</li>" for i in plan["incluye"])
    return f"""
    <table align="center" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; border:1px solid #d0d0d0; font-size:13px; margin-top:15px; table-layout: fixed;">
        <tr style="background-color:#003057; color:#FFFFFF;">
            <th align="left" width="30%" style="padding: 12px; font-weight: bold;">Plan actual</th>
            <th align="center" width="45%" style="padding: 12px; font-weight: bold;">Incluye</th>
        </tr>
        <tr>
            <td align="left" style="padding: 15px; vertical-align: top;"><b style="font-size: 14px;">{plan['nombre']}</b></td>
            <td align="left" style="padding: 15px; vertical-align: top;"><ul style="margin:0; padding-left:18px; list-style-type: disc;">{items}</ul></td>
        </tr>
    </table>
    """

def _construir_bloques_planes_vencimiento(grupos_plan: dict[str, list[str]]) -> str:
    bloques = []
    for plan, vins in grupos_plan.items():
        lista_vins_html = "".join(f"<li>{vin}</li>" for vin in vins)
        bloques.append(f"""
        <tr><td style="padding:0 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
            <p style="margin:0 0 12px 0;"><b>Unidades asociadas al plan {plan}:</b></p>
            <ul style="margin:0 0 16px 20px; padding:0;">{lista_vins_html}</ul>
        </td></tr>
        <tr><td style="padding:0 32px 18px 32px;">{_crear_tabla_plan_vencimiento(plan)}</td></tr>
        """)
    return "".join(bloques)

def construir_cuerpo_vencimiento(razon_social: str, grupos_plan: dict[str, list[str]]) -> str:
    bloques_planes = _construir_bloques_planes_vencimiento(grupos_plan)

    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">
                        Vencimiento de servicios Servicios Conectados
                    </td></tr>
                    <tr><td align="center" style="padding:24px 32px 12px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                            <tr><td style="background-color:#FFF3CD; border:1px solid #FFECB5; border-radius:8px; padding:16px 20px; font-size:14px; color:#664D03; line-height:1.5;">
                                ⚠️ <b>Estas unidades están próximas a vencer.</b>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td style="padding:0 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;">Estimados,</p>
                        <p style="margin:0 0 16px 0;">Junto con saludar, esperamos que se encuentren muy bien.</p>
                        <p style="margin:0 0 16px 0;">Mediante el presente, informamos que las siguientes unidades asociadas a <b>{razon_social}</b> se encuentran próximas a finalizar el período de suscripción gratuita.</p>
                    </td></tr>
                    {bloques_planes}
                    <tr><td align="center" style="padding:0 32px 20px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 0 28px; font-size:16px; line-height:1.4; font-weight:bold; color:#1f2937;">
                                ¿Desea revisar la renovación?
                            </td></tr>
                            <tr><td align="center" style="padding:6px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si lo estima conveniente, puede responder directamente a este mismo correo para revisar alternativas para estas unidades.
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:10px 32px 0 32px;">
                        <img src="cid:image002" width="560" style="display:block; width:100%; max-width:560px; border:0;" alt="Servicios Conectados">
                    </td></tr>
                    <tr><td style="padding:24px 32px 18px 32px; font-size:11px; line-height:1.6; color:#6b7280;">
                        <p style="margin:0 0 10px 0;">Saludos,</p>
                        <p style="margin:0 0 10px 0;"><b>Equipo Servicios Conectados Chile</b></p>
                        <p style="margin:0;"><b>Empresa Demo</b><br>Av. Ejemplo 1234 | Ciudad Ejemplo | Chile</p>
                    </td></tr>
                    <tr><td style="padding:0 32px 28px 32px;">
                        <img src="cid:logo_empresa" width="120" style="display:block; border:0;" alt="Empresa Demo Logo">
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def construir_cuerpo_crear_cuenta(razon_social: str) -> str:
    url_plataforma = "https://example.com/login"
    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">Activación de cuenta Servicios Conectados</td></tr>
                    <tr><td style="padding:28px 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;"><b>Estimado,</b></p>
                        <p style="margin:0 0 16px 0;">Informamos que se ha enviado un correo oficial desde el sistema central para que pueda <b>crear su contraseña y habilitar su cuenta en la plataforma Servicios Conectados</b>.</p>
                        <p style="margin:0 0 16px 0;">El enlace tiene una vigencia de <b>72 hours</b>. Pasado este plazo, expirará y deberá solicitar uno nuevo.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:8px 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #FFECB5; background-color:#FFF3CD; border-radius:10px;">
                            <tr><td style="padding:16px 20px; font-size:14px; line-height:1.6; color:#664D03;">
                                ⚠️ <b>Importante:</b> recuerde aceptar la invitación a <b>Servicios Conectados</b> enviada a su correo electrónico.<br><br>
                                ✅ Este paso es obligatorio para completar la activación de su cuenta.
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:20px 32px 8px 32px;">
                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                            <tr><td bgcolor="#003057" style="background-color:#003057; border-radius:10px; padding:14px 28px;">
                                <a href="{url_plataforma}" target="_blank" style="font-size:15px; font-weight:bold; color:#ffffff !important; text-decoration:none !important; display:inline-block;">Crear mi cuenta en Servicios Conectados</a>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 20px 32px; font-size:13px; line-height:1.6; color:#4b5563;">
                        Si al presionar el botón no carga, <a href="{url_plataforma}" target="_blank" style="color:#005b96; font-weight:bold; text-decoration:none;">haga clic aquí</a>.
                    </td></tr>
                    <tr><td style="padding:8px 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;">Desde el área de <b>Servicios Conectados de Empresa Demo</b>, estaremos disponibles para acompañarlo en todo momento y apoyarlo en cada proyecto.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 20px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requiere apoyo con la habilitación de su cuenta o con el acceso a la plataforma, puede responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:10px 32px 0 32px;"><img src="cid:image002" width="560" style="display:block; width:100%; max-width:560px; border:0;" alt="Servicios Conectados"></td></tr>
                    <tr><td style="padding:24px 32px 18px 32px; font-size:11px; line-height:1.6; color:#6b7280;">
                        <p style="margin:0 0 10px 0;">Saludos,</p>
                        <p style="margin:0 0 10px 0;"><b>Equipo Servicios Conectados Chile</b></p>
                        <p style="margin:0;"><b>Empresa Demo</b><br>Servicios Conectados | Optimización de Costos de Transporte &amp; Productividad | Soluciones de Transporte de Carga<br>T. +56 9 0000 0000<br>Av. Ejemplo 1234 | Ciudad Ejemplo | Chile<br>contacto@example.com<br>www.example.com</p>
                    </td></tr>
                    <tr><td style="padding:0 32px 28px 32px;"><img src="cid:logo_empresa" width="120" style="display:block; border:0;" alt="Empresa Demo Logo"></td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def construir_cuerpo_capacitacion(razon_social: str) -> str:
    url_plataforma = "https://example.com/login"
    capacitacion_url = "https://example.com/capacitacion"
    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">Capacitación Servicios Conectados</td></tr>
                    <tr><td align="center" style="padding:28px 28px 8px 28px;"><img src="cid:camiones-demo" width="620" style="display:block; width:100%; max-width:620px; border:0; border-radius:10px;" alt="Servicios Conectados"></td></tr>
                    <tr><td style="padding:10px 32px 0 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p style="margin:0 0 16px 0;"><b>Estimado,</b></p>
                        <p style="margin:0 0 16px 0;">Esperamos que usted y su equipo se encuentren muy bien.</p>
                        <p style="margin:0 0 16px 0;">Han transcurrido algunos meses desde que comenzó a utilizar <b>Servicios Conectados</b>, y en este tiempo probablemente ya ha identificado diversas funciones que apoyan su operación.</p>
                        <p style="margin:0 0 16px 0;">Queremos invitarle a una <b>capacitación técnica personalizada</b> para ayudarle a obtener un mayor provecho de la plataforma.</p>
                        <p style="margin:0 0 16px 0;">En esta sesión nos enfocaremos en:</p>
                        <p style="margin:0 0 12px 0;">• <b>Dominio de herramientas:</b> profundizaremos en las funciones que más utilizas.</p>
                        <p style="margin:0 0 12px 0;">• <b>Configuración avanzada:</b> ajustaremos la plataforma según tus necesidades actuales.</p>
                        <p style="margin:0 0 12px 0;">• <b>Resolución de dudas:</b> espacio para despejar consultas surgidas en estos meses.</p>
                        <p style="margin:0 0 18px 0;">• <b>Mejores prácticas:</b> consejos clave para sacar el máximo provecho.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:8px 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 20px 6px 20px; font-size:28px; line-height:28px;">📅</td></tr>
                            <tr><td align="center" style="padding:4px 28px 0 28px; font-size:16px; line-height:1.4; font-weight:bold; color:#1f2937;">¿Qué día y hora le resultarían convenientes para realizar esta sesión?</td></tr>
                            <tr><td align="center" style="padding:6px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Haciendo clic en el calendario podrás ver las fechas y horas disponibles.<br>En la página, en el botón <b>Inscríbete aquí</b>, puede agendar su capacitación.<br><br>
                                <a href="{capacitacion_url}" target="_blank" style="color:#005b96; font-weight:bold; text-decoration:none;">Ver fechas disponibles</a>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 20px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requiere apoyo adicional o desea resolver dudas antes de la sesión, puede responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td align="center" style="padding:10px 32px 0 32px;"><img src="cid:image002" width="560" style="display:block; width:100%; max-width:560px; border:0;" alt="Servicios Conectados"></td></tr>
                    <tr><td style="padding:24px 32px 18px 32px; font-size:11px; line-height:1.6; color:#6b7280;">
                        <p style="margin:0 0 10px 0;">Saludos,</p>
                        <p style="margin:0 0 10px 0;"><b>Equipo Servicios Conectados Chile</b></p>
                        <p style="margin:0;"><b>Empresa Demo</b><br>Servicios Conectados | Optimización de Costos de Transporte &amp; Productividad | Soluciones de Transporte de Carga<br>T. +56 9 0000 0000<br>Av. Ejemplo 1234 | Ciudad Ejemplo | Chile<br>contacto@example.com<br>www.example.com</p>
                    </td></tr>
                    <tr><td style="padding:0 32px 28px 32px;"><img src="cid:logo_empresa" width="120" style="display:block; border:0;" alt="Empresa Demo Logo"></td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def construir_cuerpo_revision_periodica(razon_social: str) -> str:
    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">
                    <tr><td style="background-color:#003057; padding:18px 22px; color:#ffffff; font-size:24px; font-weight:bold;">Revisión periódica de unidades en Servicios Conectados</td></tr>
                    <tr><td align="center" style="padding:24px 32px;"><img src="cid:imagen_revision" width="620" style="display:block; width:100%; max-width:620px; border:0; border-radius:10px;" alt="Revisión Empresa Demo"></td></tr>
                    <tr><td style="padding:20px 32px 10px 32px; font-size:14px; line-height:1.75; color:#222222;">
                        <p>Estimados <b>{html.escape(str(razon_social).strip())}</b>,</p>
                        <p>En el marco de las revisiones periódicas realizadas a la telemetría de sus unidades, se han detectado observaciones que nos gustaría revisar en conjunto para optimizar su rendimiento.</p>
                        <p>Saludos cordiales,<br><b>Equipo Servicios Conectados Chile</b></p>
                    </td></tr>
                    <tr><td align="center" style="padding:0 32px 24px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px 18px 28px; font-size:14px; line-height:1.6; color:#4b5563;">
                                Si requiere asistencia adicional, puede responder directamente a este mismo correo.
                            </td></tr>
                        </table>
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """