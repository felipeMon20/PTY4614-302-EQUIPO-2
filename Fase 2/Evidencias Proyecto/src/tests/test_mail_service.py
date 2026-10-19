import inspect
import unittest

from src.services.mail_service import (
    PLANTILLAS,
    agrupar_destinatarios,
    obtener_configuracion_plantilla,
    validar_destinatarios,
)
from src.ui import mail_dialog


NOMBRES_PLANTILLAS = [
    "Bienvenida", "Crear Cuenta", "Capacitación", "Activación",
    "Revisión Periódica", "Aviso de Vencimiento", "Cancelación",
]

# Asuntos que antes vivian hardcodeados en MailDialog._on_plantilla_changed:
# sirven para verificar que la centralizacion en mail_service no los alteró.
ASUNTOS_ORIGINALES = {
    "Bienvenida": "Bienvenido a la comunidad Servicios Conectados",
    "Crear Cuenta": "Activación de cuenta Servicios Conectados",
    "Capacitación": "Capacitación personalizada: Optimiza tu uso de Servicios Conectados",
    "Activación": "Activación de unidades en Servicios Conectados",
    "Revisión Periódica": "Revisión periódica de unidades en Servicios Conectados",
    "Aviso de Vencimiento": "Información sobre la renovación de servicios Servicios Conectados",
    "Cancelación": "Cancelación de contrato de servicios Servicios Conectados",
}

# Imagenes CID que antes se adjuntaban a mano en OutlookSenderThread.run():
# mismas listas, mismo orden.
# Las plantillas ya no incluyen el ícono de WhatsApp (whatsapp_icon.png).
IMAGENES_ORIGINALES = {
    "Bienvenida": [
        ("logo_empresa.png", "logo_empresa"), ("camiones-demo.png", "camiones-demo"),
        ("image002.gif", "image002"),
    ],
    "Activación": [
        ("imagen_Activacion.png", "imagen_activacion"),
    ],
    "Cancelación": [],
    "Aviso de Vencimiento": [
        ("logo_empresa.png", "logo_empresa"), ("image002.gif", "image002"),
    ],
    "Crear Cuenta": [
        ("logo_empresa.png", "logo_empresa"), ("image002.gif", "image002"),
    ],
    "Capacitación": [
        ("logo_empresa.png", "logo_empresa"), ("camiones-demo.png", "camiones-demo"),
        ("image002.gif", "image002"),
    ],
    "Revisión Periódica": [
        ("Imagen_revision.jpg", "imagen_revision"),
    ],
}


class TestAgruparDestinatarios(unittest.TestCase):
    """Funcion pura movida desde mail_templates.py: agrupa filas simples
    (vin, flota, plan, correo) por flota+correo, acumulando chasis y
    planes, sin depender de PyQt ni de la tabla."""

    def _fila(self, vin, flota, plan, correo):
        return {'vin': vin, 'flota': flota, 'plan': plan, 'correo': correo}

    def test_una_empresa_un_correo_un_plan_varios_chasis(self):
        filas = [
            self._fila("9BWZZZ377VT0040011", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040022", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040033", "TRANSPORTES ACME", "FULL", "acme@test.example"),
        ]
        resultado = agrupar_destinatarios(filas)

        self.assertEqual(len(resultado), 1)
        dest = resultado[0]
        self.assertEqual(dest['flota'], "TRANSPORTES ACME")
        self.assertEqual(dest['nombre'], "TRANSPORTES ACME")
        self.assertEqual(dest['correo'], "acme@test.example")
        self.assertEqual(dest['chasis_list'], ["0040011", "0040022", "0040033"])
        self.assertEqual(dest['grupos_plan'], {"FULL": ["0040011", "0040022", "0040033"]})

    def test_una_empresa_un_correo_varios_planes(self):
        filas = [
            self._fila("9BWZZZ377VT0040011", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040022", "TRANSPORTES ACME", "BASICO", "acme@test.example"),
        ]
        resultado = agrupar_destinatarios(filas)

        self.assertEqual(len(resultado), 1)
        dest = resultado[0]
        self.assertEqual(dest['chasis_list'], ["0040011", "0040022"])
        self.assertEqual(dest['grupos_plan'], {
            "FULL": ["0040011"],
            "BASICO": ["0040022"],
        })

    def test_varias_empresas_y_correos(self):
        filas = [
            self._fila("9BWZZZ377VT0040011", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040099", "LOGISTICA SUR", "MEDIO", "sur@test.example"),
        ]
        resultado = agrupar_destinatarios(filas)

        self.assertEqual(len(resultado), 2)
        correos = {dest['correo'] for dest in resultado}
        self.assertEqual(correos, {"acme@test.example", "sur@test.example"})

    def test_destinatarios_repetidos_quedan_agrupados_no_duplicados(self):
        filas = [
            self._fila("9BWZZZ377VT0040011", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040022", "TRANSPORTES ACME", "FULL", "acme@test.example"),
            self._fila("9BWZZZ377VT0040033", "LOGISTICA SUR", "MEDIO", "sur@test.example"),
        ]
        resultado = agrupar_destinatarios(filas)

        self.assertEqual(len(resultado), 2)
        acme = next(d for d in resultado if d['correo'] == "acme@test.example")
        self.assertEqual(len(acme['chasis_list']), 2)

    def test_estructura_resultante_es_compatible_con_outlook_sender_thread(self):
        filas = [self._fila("9BWZZZ377VT0040011", "TRANSPORTES ACME", "FULL", "acme@test.example")]
        resultado = agrupar_destinatarios(filas)

        self.assertIsInstance(resultado, list)
        dest = resultado[0]
        for clave in ('correo', 'flota', 'nombre', 'chasis_list', 'grupos_plan'):
            self.assertIn(clave, dest)
        self.assertIsInstance(dest['chasis_list'], list)
        self.assertIsInstance(dest['grupos_plan'], dict)


class TestValidarDestinatarios(unittest.TestCase):
    """Regla de negocio extraida de MailDialog.enviar_correos(): un
    destinatario sin correo asignado es invalido. El modo prueba (que antes
    desactivaba esta validacion) fue eliminado junto con el boton "Prueba"."""

    def test_detecta_correo_faltante_y_devuelve_el_vin(self):
        filas = [
            {'vin': 'VIN1', 'flota': 'ACME', 'plan': 'FULL', 'correo': 'acme@test.example'},
            {'vin': 'VIN2', 'flota': 'ACME', 'plan': 'FULL', 'correo': ''},
        ]
        self.assertEqual(validar_destinatarios(filas), 'VIN2')

    def test_todas_con_correo_devuelve_none(self):
        filas = [
            {'vin': 'VIN1', 'flota': 'ACME', 'plan': 'FULL', 'correo': 'acme@test.example'},
            {'vin': 'VIN2', 'flota': 'ACME', 'plan': 'FULL', 'correo': 'acme2@test.example'},
        ]
        self.assertIsNone(validar_destinatarios(filas))

    def test_devuelve_el_primer_vin_sin_correo_en_orden_de_aparicion(self):
        filas = [
            {'vin': 'VIN1', 'flota': 'ACME', 'plan': 'FULL', 'correo': ''},
            {'vin': 'VIN2', 'flota': 'ACME', 'plan': 'FULL', 'correo': ''},
        ]
        self.assertEqual(validar_destinatarios(filas), 'VIN1')


class TestObtenerConfiguracionPlantilla(unittest.TestCase):
    """Configuracion centralizada (asunto + constructor HTML + imagenes CID)
    que reemplaza lo que antes estaba repartido entre el dict "asuntos" de
    MailDialog._on_plantilla_changed y el if/elif de OutlookSenderThread.run()."""

    def test_cubre_las_siete_plantillas_actuales(self):
        self.assertEqual(set(PLANTILLAS.keys()), set(NOMBRES_PLANTILLAS))

    def test_cada_plantilla_tiene_asunto_constructor_e_imagenes(self):
        for nombre in NOMBRES_PLANTILLAS:
            config = obtener_configuracion_plantilla(nombre)
            self.assertIsNotNone(config, f"Falta configuracion para {nombre}")
            self.assertIn('asunto', config)
            self.assertIn('constructor', config)
            self.assertIn('imagenes', config)
            self.assertTrue(callable(config['constructor']))

    def test_asuntos_no_cambiaron(self):
        for nombre, asunto_esperado in ASUNTOS_ORIGINALES.items():
            config = obtener_configuracion_plantilla(nombre)
            self.assertEqual(config['asunto'], asunto_esperado)

    def test_imagenes_cid_no_cambiaron(self):
        for nombre, imagenes_esperadas in IMAGENES_ORIGINALES.items():
            config = obtener_configuracion_plantilla(nombre)
            self.assertEqual(config['imagenes'], imagenes_esperadas)

    def test_constructor_produce_html(self):
        dest_ejemplo = {
            'flota': 'TRANSPORTES ACME', 'nombre': 'TRANSPORTES ACME', 'correo': 'acme@test.example',
            'chasis_list': ['0040011'], 'grupos_plan': {'FULL': ['0040011']},
        }
        for nombre in NOMBRES_PLANTILLAS:
            config = obtener_configuracion_plantilla(nombre)
            html = config['constructor'](dest_ejemplo)
            self.assertIsInstance(html, str)
            self.assertIn('<html>', html)

    def test_nombre_no_reconocido_devuelve_none(self):
        self.assertIsNone(obtener_configuracion_plantilla("Personalizado (Escribir desde cero)"))
        self.assertIsNone(obtener_configuracion_plantilla("Personalizado"))
        self.assertIsNone(obtener_configuracion_plantilla("Plantilla que no existe"))


class TestSinCorreoPersonalHardcodeado(unittest.TestCase):
    """El correo personal usado antes para el boton Prueba, y la cuenta
    compartida que ya no existe, no deben quedar hardcodeados en ningun
    lado del sistema de correos."""

    def test_mail_dialog_no_contiene_correo_personal_ni_cuenta_antigua(self):
        codigo_fuente = inspect.getsource(mail_dialog)
        self.assertNotIn("usuario@example.com", codigo_fuente)
        self.assertNotIn("contacto@example.com", codigo_fuente)
        self.assertNotIn("CORREO_PRUEBA", codigo_fuente)
        self.assertNotIn("CUENTA_EMPRESA", codigo_fuente)

    def test_mail_service_no_contiene_correo_personal_ni_cuenta_antigua(self):
        import src.services.mail_service as mail_service_module
        codigo_fuente = inspect.getsource(mail_service_module)
        self.assertNotIn("usuario@example.com", codigo_fuente)
        self.assertNotIn("contacto@example.com", codigo_fuente)


class TestSinReferenciasAlModoPrueba(unittest.TestCase):
    """El boton "Prueba" fue eliminado por completo (Outlook lo bloqueaba/
    rechazaba). No debe quedar ningun rastro de esa logica ni del parametro
    modo_prueba/forzar_prueba en el codigo del modulo de Correos."""

    def test_mail_dialog_no_contiene_referencias_al_modo_prueba(self):
        codigo_fuente = inspect.getsource(mail_dialog)
        for termino in ("btn_prueba", "forzar_prueba", "modo_prueba", "PruebaMio"):
            self.assertNotIn(termino, codigo_fuente, f"'{termino}' no deberia seguir en mail_dialog.py")

    def test_mail_service_no_contiene_referencias_al_modo_prueba(self):
        import src.services.mail_service as mail_service_module
        codigo_fuente = inspect.getsource(mail_service_module)
        for termino in ("forzar_prueba", "modo_prueba"):
            self.assertNotIn(termino, codigo_fuente, f"'{termino}' no deberia seguir en mail_service.py")


if __name__ == '__main__':
    unittest.main(verbosity=2)
