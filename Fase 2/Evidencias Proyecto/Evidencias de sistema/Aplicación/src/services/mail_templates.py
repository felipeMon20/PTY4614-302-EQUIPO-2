import html
from urllib.parse import quote

PLANES_CONFIG = {
    "BASICO": {"nombre": "Básico", "incluye": ["Posicionamiento", "Consumo de Combustible"]},
    "MEDIO": {"nombre": "Medio", "incluye": ["Posicionamiento", "Consumo de Combustible", "Datos del Motor"]},
    "FULL": {"nombre": "Full", "incluye": ["Posicionamiento", "Consumo de Combustible", "Datos del Motor", "Comportamiento del Conductor"]},
    "MEDIO + CIV": {"nombre": "Medio + CIV", "incluye": ["Posicionamiento", "Consumo", "Motor", "CIV"]},
    "FULL + CIV": {"nombre": "Full + CIV", "incluye": ["Posicionamiento", "Consumo", "Motor", "Conductor", "CIV"]}
}

URL_PLATAFORMA = "https://volvoconnect.com/login"
URL_CAPACITACION = "https://bookings.cloud.microsoft/book/VC@volvogroup.com/?ismsaljsauthenabled"

def _mailto(correo, asunto, cuerpo):
    """Enlace de los botones comerciales: abre un correo nuevo hacia el equipo
    para que el cliente lo redacte."""
    return f"mailto:{correo}?subject={quote(asunto)}&body={quote(cuerpo)}"

_AZUL = "#003057"
# Una sola fuente y tamaño para todo el cuerpo; Outlook no hereda estilos de
# <body> en las celdas, por eso se repite en cada una. Volvo Novum es la fuente
# corporativa: si el equipo del lector no la tiene, usa la más parecida.
_FUENTE = "font-family:'Volvo Novum 3.1', 'Volvo Novum', 'Segoe UI', Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6;"
_TEXTO_RESPUESTA = "Si tienes alguna consulta, puedes responder directamente a este correo. Estaremos encantados de ayudarte."
_TEXTO_RESPUESTA_AYUDA = "Si tienes alguna consulta o necesitas ayuda, responde a este correo y estaremos encantados de ayudarte."


def _p(texto):
    return f'<p style="margin:0 0 14px 0;">{texto}</p>'


def _titulo_seccion(texto):
    return f'<p style="margin:6px 0 12px 0; font-size:16px; font-weight:bold; color:{_AZUL};">{texto}</p>'


def _hero(cid):
    """Foto de cabecera a todo el ancho, justo bajo la barra azul."""
    return f"""
                    <tr><td style="padding:0; line-height:0; font-size:0;">
                        <img src="cid:{cid}" width="720" style="display:block; width:100%; max-width:720px; height:auto; border:0;" alt="Volvo Connect">
                    </td></tr>"""


def _fila_texto(contenido):
    return f"""
                    <tr><td style="padding:16px 32px 0 32px; {_FUENTE} color:#222222;">
                        {contenido}
                    </td></tr>"""


def _boton(texto, url):
    url = html.escape(url, quote=True)
    return f"""
                    <tr><td align="center" style="padding:12px 32px 18px 32px;">
                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                            <tr><td align="center" bgcolor="{_AZUL}" style="background-color:{_AZUL}; border-radius:10px; padding:14px 32px; {_FUENTE}">
                                <a href="{url}" target="_blank" style="font-weight:bold; color:#ffffff !important; text-decoration:none !important; display:inline-block;">{texto}</a>
                            </td></tr>
                        </table>
                    </td></tr>"""


def _caja(contenido):
    return f"""
                    <tr><td align="center" style="padding:8px 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px dashed #bfc7d8; background-color:#f7f9fc;">
                            <tr><td align="center" style="padding:18px 28px; {_FUENTE} color:#4b5563;">
                                {contenido}
                            </td></tr>
                        </table>
                    </td></tr>"""


def _pasos(items):
    filas = "".join(f"""
                            <tr><td width="36" valign="top" style="padding:10px 0 10px 16px;">
                                <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
                                    <td align="center" width="26" height="26" bgcolor="{_AZUL}" style="background-color:{_AZUL}; border-radius:13px; color:#ffffff; {_FUENTE} font-weight:bold;">{i}</td>
                                </tr></table>
                            </td>
                            <td style="padding:10px 16px 10px 8px; {_FUENTE} color:#222222;"><b>{titulo}</b><br>{detalle}</td></tr>"""
                    for i, (titulo, detalle) in enumerate(items, 1))
    return f"""
                    <tr><td style="padding:0 32px 12px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #d7dde5; background-color:#f8fafc; border-radius:8px;">{filas}
                        </table>
                    </td></tr>"""


def _etiqueta_plan(plan):
    key = str(plan).strip().upper()
    return PLANES_CONFIG.get(key, {"nombre": str(plan).strip()})["nombre"]


def _tabla_unidades(unidades, columnas):
    """columnas: lista de (titulo, clave); cada unidad es un dict con
    'chasis', 'plan' y 'vence' (ver mail_service.agrupar_destinatarios)."""
    encabezado = "".join(
        f'<th align="left" style="padding:10px 14px; {_FUENTE} font-weight:bold;">{titulo}</th>'
        for titulo, _ in columnas
    )
    filas = []
    for i, u in enumerate(unidades):
        fondo = "#ffffff" if i % 2 == 0 else "#f8fafc"
        celdas = ""
        for _, clave in columnas:
            bruto = u.get(clave)
            valor = _etiqueta_plan(bruto) if clave in ("plan", "anterior") and bruto else (bruto or "—")
            celdas += f'<td style="padding:10px 14px; {_FUENTE} color:#222222; border-top:1px solid #e5e9f0;">{html.escape(str(valor))}</td>'
        filas.append(f'<tr style="background-color:{fondo};">{celdas}</tr>')
    return f"""
                    <tr><td style="padding:0 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate; border:1px solid #d7dde5; border-radius:8px; overflow:hidden;">
                            <tr style="background-color:{_AZUL}; color:#ffffff;">{encabezado}</tr>
                            {"".join(filas)}
                        </table>
                    </td></tr>"""


def _barra(titulo):
    """Barra azul: la frase de apertura del correo a la izquierda y el logo
    Volvo en blanco a la derecha."""
    return f"""
                    <tr><td style="background-color:{_AZUL}; padding:20px 22px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td valign="middle" style="{_FUENTE} font-size:20px; line-height:1.35; font-weight:bold; color:#ffffff;">{titulo}</td>
                                <td valign="middle" align="right" width="96" style="padding-left:16px;">
                                    <img src="cid:logo_volvo_blanco" width="88" style="display:block; width:88px; height:auto; border:0;" alt="Volvo">
                                </td>
                            </tr>
                        </table>
                    </td></tr>"""


def _titulo_sin_barra(titulo):
    return f"""
                    <tr><td style="padding:24px 32px 0 32px; {_FUENTE} font-size:20px; line-height:1.35; font-weight:bold; color:{_AZUL};">{titulo}</td></tr>"""


def _pagina(titulo, filas, hero=None, firma=True, barra=True):
    """Marco común de todos los correos: barra azul con la frase de apertura
    y el logo, imagen opcional, contenido y firma. Con barra=False la imagen
    va primero y la frase de apertura pasa a ser un título azul bajo ella."""
    bloque_firma = f"""
                    <tr><td style="padding:24px 32px 28px 32px; {_FUENTE} color:#6b7280;">
                        <p style="margin:0 0 10px 0;">Saludos cordiales,</p>
                        <p style="margin:0 0 10px 0;"><b>Equipo Volvo Connect Chile</b></p>
                        <p style="margin:0;"><b>Volvo Chile</b> | Servicios Conectados<br>Av. Pdte Eduardo Frei Montalva 8691 | Quilicura, Santiago | Chile<br>www.volvochile.cl</p>
                    </td></tr>""" if firma else ""
    return f"""
    <html>
    <body style="margin:0; padding:0; background-color:#eef2f7; {_FUENTE} color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7; margin:0; padding:24px 0;">
            <tr><td align="center">
                <table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px; max-width:720px; background-color:#ffffff; border-radius:14px; overflow:hidden;">{_barra(titulo) if barra else ""}{_hero(hero) if hero else ""}{"" if barra else _titulo_sin_barra(titulo)}{"".join(filas)}{bloque_firma}
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """


def construir_cuerpo_conoce_volvo_connect(razon_social, correo_equipo=""):
    beneficios = "".join(
        f"<li style='margin-bottom:8px;'><b>{titulo}:</b> {detalle}</li>"
        for titulo, detalle in [
            ("Conocer mejor tu flota", "accede a información sobre el desempeño y funcionamiento de tus camiones."),
            ("Identificar oportunidades de mejora", "utiliza indicadores que te ayudan a comprender tu operación y detectar dónde actuar."),
            ("Contar con el respaldo de Volvo", "conecta la tecnología con el conocimiento de nuestros especialistas, capacitaciones y servicios complementarios."),
        ])
    return _pagina("¿Sabías que tus camiones Volvo generan información que puede ayudarte a mejorar la gestión de tu flota?", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Queremos presentarte <b>Volvo Connect</b>, nuestra plataforma digital de gestión de flotas, diseñada para ayudarte a conocer mejor tus camiones Volvo y tomar decisiones más informadas sobre tu operación.")
            + _p("Con Volvo Connect puedes ir más allá del posicionamiento de tus vehículos y aprovechar la información que generan directamente para:")
            + f'<ul style="margin:0 0 14px 20px; padding:0;">{beneficios}</ul>'
            + _p("<b>¡Descubre todo lo que Volvo Connect puede aportar a tu operación!</b>")
            + _p("Contamos con distintos niveles de servicio que se adaptan a las necesidades de tu flota.")
        ),
        _boton("Conoce las opciones para tu flota", _mailto(correo_equipo,
            "Solicitud de información Volvo Connect",
            "Hola, quisiera recibir información sobre Volvo Connect para mi flota.")),
        _caja("Si tienes alguna consulta, responde a este correo. Nuestro equipo estará encantado de ayudarte."),
    ], hero="foto_camion_tablet")


def construir_cuerpo_reactivacion(razon_social, correo_equipo=""):
    return _pagina("Tu flota tiene mucho más que contar. Descúbrelo con Volvo Connect.", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Actualmente, algunas unidades de tu flota no cuentan con una membresía activa de Volvo Connect.")
            + _p("<b>¿Sabías que tus camiones Volvo generan información valiosa que puede ayudarte a comprender mejor su desempeño e identificar oportunidades de mejora?</b>")
            + _p("Volvo Connect es más que una plataforma de gestión de flota. Es parte de un ecosistema que conecta la información de tus vehículos con herramientas digitales, capacitación y el conocimiento de profesionales especializados de Volvo para apoyar tu operación.")
            + _p("Al reactivar tu servicio, podrás acceder a las funcionalidades disponibles según tu membresía y contar con el respaldo de nuestro equipo para aprovechar mejor la plataforma.")
            + _p("<b>¡Descubre todo lo que Volvo Connect puede aportar a tu operación!</b>")
        ),
        _boton("Quiero reactivar mi membresía", _mailto(correo_equipo,
            "Reactivación Volvo Connect",
            "Hola, quisiera conocer las alternativas para reactivar Volvo Connect en mi flota.")),
        _caja("¿Tienes dudas o quieres conocer las alternativas disponibles?<br>Responde a este correo y estaremos encantados de ayudarte."),
    ], hero="foto_hombre_computador")


def construir_cuerpo_continuidad_cm(razon_social, correo_equipo=""):
    return _pagina("Tu contrato finaliza, pero tu flota puede seguir conectada.", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("La cobertura de Volvo Connect asociada al contrato de mantenimiento de tu flota no fue renovada.")
            + _p("Queremos invitarte a mantener la continuidad del servicio para que sigas aprovechando la información que generan tus camiones Volvo y las herramientas que te ayudan a comprender mejor tu operación y tomar decisiones informadas.")
            + _p("Con Volvo Connect, sigues contando con mucho más que una plataforma: un ecosistema que integra información de tus vehículos, herramientas digitales, capacitación y el conocimiento de profesionales especializados de Volvo para apoyar la gestión de tu flota.")
            + _p("<b>¡Continúa aprovechando el potencial de tus camiones Volvo!</b>")
            + _p("Conoce las alternativas de membresía disponibles y elige la que mejor se adapte a las necesidades de tu operación.")
        ),
        _boton("Quiero continuar con mi membresía", _mailto(correo_equipo,
            "Continuidad Volvo Connect",
            "Hola, quisiera conocer las alternativas de membresía para mantener Volvo Connect en mi flota.")),
        _caja("¿Tienes alguna consulta?<br>Responde a este correo y nuestro equipo estará encantado de ayudarte."),
    ], hero="foto_mujer_pantallas")


def construir_cuerpo_bienvenida(razon_social):
    return _pagina("¡Bienvenido a Volvo Connect!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("¡Nos alegra darte la bienvenida a <b>Volvo Connect</b>!")
            + _p("Desde ahora podrás comenzar a explorar nuestra plataforma digital de gestión de flota, diseñada para ayudarte a conocer mejor tus camiones Volvo y aprovechar la información que generan para apoyar tu operación.")
            + _titulo_seccion("¿Cómo comenzar?")
        ),
        _pasos([
            ("Crea tu contraseña", "Recibirás un correo automático de Volvo Connect con las instrucciones para establecer tu contraseña. Si no lo encuentras, revisa tu carpeta de correo no deseado."),
            ("Ingresa a la plataforma", "Una vez creada tu contraseña, accede con tu correo electrónico registrado."),
            ("Explora tu flota", "Conoce las herramientas e información disponibles según tu nivel de servicio contratado."),
        ]),
        _fila_texto(
            _titulo_seccion("¿Necesitas ayuda con tu primer ingreso?")
            + _p("Adjuntamos una cápsula de aprendizaje que te guiará paso a paso para crear tu contraseña y comenzar a utilizar Volvo Connect.")
        ),
        _boton("Ingresar a Volvo Connect", URL_PLATAFORMA),
        _caja("¿Tienes dudas o necesitas ayuda para comenzar?<br>Responde a este correo y estaremos encantados de ayudarte."),
    ], hero="foto_camion_puente", barra=False)


def _tabla_niveles(grupos_plan: dict[str, list[str]]) -> str:
    """Una sola tabla con la información que incluye cada nivel presente,
    en vez de repetir el detalle del plan por cada grupo de unidades."""
    filas = []
    for i, plan in enumerate(grupos_plan):
        info = PLANES_CONFIG.get(str(plan).strip().upper(), {"nombre": str(plan).strip(), "incluye": []})
        fondo = "#ffffff" if i % 2 == 0 else "#f8fafc"
        filas.append(
            f'<tr style="background-color:{fondo};">'
            f'<td valign="top" style="padding:10px 14px; {_FUENTE} font-weight:bold; color:#222222; border-top:1px solid #e5e9f0;">{html.escape(info["nombre"])}</td>'
            f'<td style="padding:10px 14px; {_FUENTE} color:#222222; border-top:1px solid #e5e9f0;">{html.escape(" · ".join(info["incluye"]))}</td></tr>')
    return f"""
                    <tr><td style="padding:0 32px 18px 32px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate; border:1px solid #d7dde5; border-radius:8px; overflow:hidden;">
                            <tr style="background-color:{_AZUL}; color:#ffffff;"><th align="left" style="padding:10px 14px; {_FUENTE} font-weight:bold;">Nivel de servicio</th><th align="left" style="padding:10px 14px; {_FUENTE} font-weight:bold;">Información disponible</th></tr>
                            {"".join(filas)}
                        </table>
                    </td></tr>"""

def construir_cuerpo_activacion(razon_social: str, grupos_plan: dict[str, list[str]], unidades: list[dict] | None = None) -> str:
    if unidades is None:
        unidades = [{"chasis": str(c).strip(), "plan": plan} for plan, chasis_list in grupos_plan.items() for c in chasis_list if str(c).strip()]
    return _pagina("¡Tu flota sigue creciendo en Volvo Connect!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("¡Tenemos buenas noticias!")
            + _p("Te confirmamos que hemos incorporado nuevas unidades de tu flota a Volvo Connect, para que puedas comenzar a aprovechar las herramientas de gestión e información disponibles según tu nivel de servicio.")
            + _titulo_seccion("Unidades incorporadas")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel de servicio", "plan"), ("Vencimiento", "vence")]),
        _fila_texto(_titulo_seccion("¿Qué información podrás ver?")),
        _tabla_niveles(grupos_plan),
        _fila_texto(
            _titulo_seccion("¿Cuándo podrás visualizar la información?")
            + _p("La activación y reportabilidad de los servicios puede tomar hasta 72 horas, dependiendo de la actividad reciente de cada camión. Si la unidad ha estado en movimiento durante los últimos días, es posible que comience a reportar antes.")
        ),
        _boton("Ver mi flota en Volvo Connect", URL_PLATAFORMA),
        _caja(_TEXTO_RESPUESTA_AYUDA),
    ], hero="foto_app_celular")


def construir_cuerpo_capacitacion(razon_social: str) -> str:
    return _pagina("Descubre todo lo que puedes hacer con Volvo Connect", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Queremos ayudarte a aprovechar al máximo las herramientas de Volvo Connect y la información que generan tus camiones.")
            + _p("¿Sabías que la plataforma cuenta con guías y tutoriales que te permiten aprender a utilizar sus funcionalidades a tu propio ritmo?")
            + _p("Adjuntamos una cápsula de aprendizaje que te guiará paso a paso para utilizar la guía oficial que se encuentra en Volvo Connect.")
        ),
        _fila_texto(
            _titulo_seccion("¿Necesitas apoyo adicional?")
            + _p("También puedes agendar una capacitación personalizada con nuestros especialistas Volvo, quienes te ayudarán a resolver tus dudas y conocer mejor las herramientas disponibles para tu operación.")
            + _p("<b>¡Estamos aquí para ayudarte a aprovechar todo el potencial de tu flota!</b>")
        ),
        _boton("Agendar mi capacitación", URL_CAPACITACION),
        _caja("Si tienes alguna consulta, responde a este correo. Estaremos encantados de ayudarte."),
    ], hero="foto_equipo_apoyo")


def construir_cuerpo_seguimiento_uso(razon_social: str) -> str:
    return _pagina("Queremos conocer tu experiencia con Volvo Connect", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Esperamos que estés aprovechando las herramientas de Volvo Connect para conocer mejor tu flota y apoyar la gestión de tu operación.")
            + _p("Nos gustaría saber cómo ha sido tu experiencia con la plataforma y si has podido utilizar las funcionalidades disponibles según tu nivel de servicio.")
            + _p("¿Hay alguna herramienta que te gustaría conocer mejor o alguna duda que podamos ayudarte a resolver?")
            + _p("Nuestro equipo está disponible para acompañarte y ayudarte a aprovechar mejor la información que generan tus camiones Volvo.")
            + _p("Si necesitas apoyo, puedes coordinar una capacitación personalizada con nuestros especialistas.")
        ),
        _boton("Agendar mi capacitación", URL_CAPACITACION),
        _caja("También puedes responder directamente a este correo y contarnos cómo ha sido tu experiencia.<br><b>¡Queremos que Volvo Connect sea una herramienta útil para tu operación!</b>"),
    ], hero="foto_equipo_apoyo")


def _chasis_texto(unidades: list[dict]) -> str:
    return ", ".join(str(u.get("chasis", "")).strip() for u in unidades if str(u.get("chasis", "")).strip())


def construir_cuerpo_vencimiento(razon_social: str, unidades: list[dict], correo_equipo: str = "") -> str:
    return _pagina("¡Mantén tu flota conectada con Volvo Connect!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p(f'Queremos informarte que <b style="color:{_AZUL};">la membresía de Volvo Connect de algunas unidades de tu flota está próxima a vencer.</b>')
            + _p("Para que puedas seguir aprovechando la información que generan tus camiones Volvo y las herramientas que te ayudan a comprender mejor tu operación, te invitamos a gestionar oportunamente la renovación de tu servicio.")
            + _titulo_seccion("Detalle de las membresías próximas a vencer")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel de servicio", "plan"), ("Vencimiento", "vence")]),
        _fila_texto(
            _titulo_seccion("¡Continúa aprovechando todo el potencial de tu flota!")
            + _p("Renueva tu membresía y mantén el acceso a las funcionalidades contratadas, junto con el respaldo del ecosistema de servicios y conocimiento Volvo.")
        ),
        _boton("Quiero renovar mi membresía", _mailto(correo_equipo,
            "Renovación Volvo Connect",
            f"Hola, quisiera renovar la membresía de Volvo Connect de las unidades: {_chasis_texto(unidades)}.")),
        _caja("¿Tienes dudas o quieres revisar las alternativas disponibles?<br>Responde a este correo y nuestro equipo estará encantado de ayudarte."),
    ])


def construir_cuerpo_seguimiento_renovacion(razon_social: str, unidades: list[dict], correo_equipo: str = "") -> str:
    return _pagina("¡Tu flota puede seguir conectada con Volvo Connect!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Hace unos días te compartimos información sobre el próximo vencimiento de tus membresías de Volvo Connect.")
            + _p("Queremos ayudarte a mantener la continuidad del servicio, para que sigas aprovechando la información que generan tus camiones Volvo y las herramientas que apoyan la gestión de tu operación.")
            + _titulo_seccion("Unidades pendientes de renovación")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel de servicio", "plan"), ("Vencimiento", "vence")]),
        _fila_texto(
            _titulo_seccion("¿Continuamos conectados?")
            + _p("Confirma tu interés en renovar y nuestro equipo se pondrá en contacto contigo para revisar las condiciones de continuidad de tus membresías.")
        ),
        _boton("Quiero renovar mi membresía", _mailto(correo_equipo,
            "Interés en renovar Volvo Connect",
            f"Hola, confirmo mi interés en renovar la membresía de Volvo Connect de las unidades: {_chasis_texto(unidades)}.")),
        _caja("Si tienes alguna consulta o necesitas más información, responde a este correo. Estaremos encantados de ayudarte."),
    ])


def construir_cuerpo_renovacion_confirmada(razon_social: str, unidades: list[dict]) -> str:
    return _pagina("¡Tu renovación de Volvo Connect está confirmada!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Te confirmamos que la renovación de las membresías de Volvo Connect de tu flota ha sido procesada exitosamente.")
            + _p("Gracias por seguir confiando en nosotros. Tus unidades continúan conectadas y podrás seguir aprovechando la información que generan tus camiones Volvo para apoyar la gestión de tu operación.")
            + _titulo_seccion("Detalle de las membresías renovadas")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel de servicio", "plan"), ("Vigente hasta", "vence")]),
        _fila_texto(
            _titulo_seccion("¡Sigue aprovechando todo el potencial de tu flota!")
            + _p("Recuerda que nuestro equipo está disponible para ayudarte a conocer y aprovechar las herramientas de tu membresía.")
        ),
        _boton("Ingresar a Volvo Connect", URL_PLATAFORMA),
        _caja(_TEXTO_RESPUESTA_AYUDA),
    ])


def construir_cuerpo_comunicado(titulo, mensaje):
    """Correo "Personalizado": el texto que escribe el usuario dentro de la
    barra azul con el logo. Sin firma, el mensaje ya trae la suya."""
    texto = html.escape(str(mensaje).strip()).replace("\r\n", "\n").replace("\n", "<br>")
    return _pagina(html.escape(str(titulo).strip()), [_fila_texto(f'<p style="margin:0 0 14px 0;">{texto}</p>')], firma=False)


def construir_cuerpo_baja(razon_social: str, unidades: list[dict]) -> str:
    return _pagina("Confirmación de baja de Volvo Connect", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Te informamos que la baja de las membresías de Volvo Connect asociadas a tu flota ha sido procesada exitosamente.")
            + _titulo_seccion("Detalle de las unidades dadas de baja")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel de servicio", "plan"), ("Fecha de baja", "baja")]),
        _fila_texto(
            _p("A partir de las fechas indicadas, estas unidades dejarán de contar con las funcionalidades correspondientes a sus membresías, por lo que ya no estarán disponibles para su gestión bajo esos servicios en la plataforma.")
            + _p("Agradecemos la confianza depositada en nuestros servicios. Si en el futuro deseas volver a conectar tu flota, estaremos encantados de ayudarte.")
        ),
        _caja("¿Tienes alguna consulta?<br>Puedes responder directamente a este correo y nuestro equipo te ayudará a resolverla."),
    ])


def construir_cuerpo_cambio_nivel(razon_social: str, unidades: list[dict]) -> str:
    return _pagina("¡Tu experiencia Volvo Connect se ha actualizado!", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("Te confirmamos que hemos realizado exitosamente el cambio de nivel de servicio de Volvo Connect solicitado para tu flota.")
            + _p("Con esta actualización, podrás acceder a las funcionalidades correspondientes a tu nueva membresía y seguir aprovechando la información que generan tus camiones Volvo para apoyar la gestión de tu operación.")
            + _titulo_seccion("Detalle de las unidades actualizadas")
        ),
        _tabla_unidades(unidades, [("Chasis", "chasis"), ("Nivel anterior", "anterior"), ("Nuevo nivel contratado", "plan")]),
        _fila_texto(
            _titulo_seccion("¡Descubre las herramientas disponibles en tu nuevo nivel de servicio!")
            + _p("Te invitamos a ingresar a Volvo Connect y explorar las funcionalidades que ahora tienes disponibles para tu flota.")
            + _p("Recuerda que nuestro equipo está disponible para ayudarte a conocer y aprovechar las herramientas de tu membresía.")
        ),
        _boton("Explorar mi flota en Volvo Connect", URL_PLATAFORMA),
        _caja("Si tienes alguna consulta, responde a este correo. Estaremos encantados de ayudarte."),
    ])


def construir_cuerpo_revision_periodica(razon_social: str) -> str:
    return _pagina("Revisamos la información de tus unidades en Volvo Connect", [
        _fila_texto(
            _p("Estimado/a cliente:")
            + _p("En el marco de las revisiones periódicas que realizamos a la telemetría de tus unidades, detectamos algunas observaciones que nos gustaría revisar contigo para optimizar su rendimiento.")
            + _p("Nuestro equipo está disponible para acompañarte y ayudarte a aprovechar mejor la información que generan tus camiones Volvo.")
        ),
        _caja(_TEXTO_RESPUESTA_AYUDA),
    ], hero="foto_hombre_computador")
