import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd
from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget

from src.ui.general import (COLUMNAS_BUSQUEDA_UNIDADES, COLUMNAS_CLIENTES, COLUMNAS_HISTORIAL, COLUMNAS_UNIDADES,
                             COLUMNAS_UNIDADES_VISIBLES, ESTADO_ACTIVACION_COLORES, ETAPA_GESTION_COLORES,
                             GeneralModule, PowerBiDirectorEmpresaLoaderThread, GeneralDataPrepThread,
                             _clave_flota_texto)
from src.core.constants import (COL_VIN, COL_FLOTA_VC, COL_RUT, COL_CDB, COL_CHASIS,
                                 COL_RAZON_SOCIAL, COL_ESTADO_ACTIVACION, COL_INDUSTRIA, COL_ETAPA_GESTION)
from src.core.data_manager import DataManager
from src.services import comercial_services
from src.theme.colors import MODULE_COLORS


def _esperar_prep_thread(module, timeout_ms=20000, interval_ms=20):
    """Espera a que GeneralDataPrepThread (disparado por
    GeneralModule.load_data(), ver auditoria de rendimiento fase 4,
    21-09-2026) termine de aplicar su resultado via _on_prep_finished.
    Antes load_data() era sincrono dentro de __init__/_on_data_ready; ahora
    dispara un QThread real, asi que los tests de integracion que construyen
    una instancia real de GeneralModule (o disparan un refresco real via
    data_ready.emit()) deben esperar esto en vez de asumir que
    df_clientes_base/df_flota_base/df_unidades_base ya estan poblados apenas
    termina la llamada. Mismo patron de espera (processEvents() en loop con
    timeout) que ya usa TestPowerBiDirectorEmpresaLoaderThread._wait_until
    para otro worker de este mismo archivo."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not module._prep_en_curso:
            QApplication.processEvents()
            return True
        time.sleep(interval_ms / 1000.0)
    return False


def _df_unidades_test(datos):
    """df_unidades_base de prueba con todas las columnas de COLUMNAS_UNIDADES
    (las que no se indican quedan vacías)."""
    n = len(next(iter(datos.values())))
    return pd.DataFrame({c: datos.get(c, [''] * n) for c in COLUMNAS_UNIDADES})


class TestBuildUnidadesDf(unittest.TestCase):
    """GeneralModule._build_unidades_df(): caja izquierda, apartado
    "Unidades" -- listado general de todas las VIN de Comercial, una fila
    por unidad, sin agrupar. Misma fuente que Cliente/Flota. Función pura
    (no usa self.*), se invoca sobre una instancia sin __init__."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def test_muestra_todas_las_vin_sin_agrupar(self):
        df = pd.DataFrame({
            COL_VIN: ['VIN001', 'VIN002', 'VIN003'],
            COL_CHASIS: ['CH1', 'CH2', 'CH3'],
            COL_RAZON_SOCIAL: ['Empresa A', 'Empresa A', 'Empresa B'],
            COL_CDB: ['CDB001', 'CDB001', 'CDB002'],
            COL_FLOTA_VC: ['FLOTA ABC', 'FLOTA XYZ', 'FLOTA ABC'],
            COL_ESTADO_ACTIVACION: ['CONECTADO', 'DESCONECTADO', 'CONECTADO'],
        })
        resultado = self.mod._build_unidades_df(df)
        self.assertEqual(len(resultado), 3, "Debe listar las 3 VIN, una fila por unidad, sin agrupar.")
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['VIN001', 'VIN002', 'VIN003'])

    def test_columnas_de_salida(self):
        df = pd.DataFrame({
            COL_VIN: ['VIN001'], COL_CHASIS: ['CH1'], COL_RAZON_SOCIAL: ['Empresa A'],
            COL_CDB: ['CDB001'], COL_FLOTA_VC: ['FLOTA ABC'], COL_ESTADO_ACTIVACION: ['CONECTADO'],
        })
        resultado = self.mod._build_unidades_df(df)
        self.assertEqual(list(resultado.columns), COLUMNAS_UNIDADES)

    def test_df_vacio_no_falla(self):
        resultado = self.mod._build_unidades_df(pd.DataFrame())
        self.assertTrue(resultado.empty)

    def test_sin_columna_vin_devuelve_vacio(self):
        resultado = self.mod._build_unidades_df(pd.DataFrame({COL_CDB: ['CDB001']}))
        self.assertTrue(resultado.empty)

    def test_conserva_industria_y_etapa_gestion(self):
        """'Industria/s' y 'ETAPA GESTIÓN' (agregadas a COLUMNAS_UNIDADES el
        10-09-2026) deben conservar el valor real de COL_INDUSTRIA/
        COL_ETAPA_GESTION, sin recalcularlo ni modificarlo -- este método
        solo renombra columnas, no toca la regla de negocio de ETAPA
        GESTIÓN (esa vive en DataFrameFormatter)."""
        df = pd.DataFrame({
            COL_VIN: ['VIN001'], COL_CHASIS: ['CH1'], COL_RAZON_SOCIAL: ['Empresa A'],
            COL_CDB: ['CDB001'], COL_FLOTA_VC: ['FLOTA ABC'], COL_ESTADO_ACTIVACION: ['CONECTADO'],
            COL_INDUSTRIA: ['Minería'], COL_ETAPA_GESTION: ['OPERACIONES'],
        })
        resultado = self.mod._build_unidades_df(df)
        self.assertEqual(resultado.iloc[0]['Industria/s'], 'Minería')
        self.assertEqual(resultado.iloc[0]['ETAPA GESTIÓN'], 'OPERACIONES')

    def test_sin_industria_ni_etapa_gestion_quedan_vacias_no_falla(self):
        df = pd.DataFrame({
            COL_VIN: ['VIN001'], COL_CHASIS: ['CH1'], COL_RAZON_SOCIAL: ['Empresa A'],
            COL_CDB: ['CDB001'], COL_FLOTA_VC: ['FLOTA ABC'], COL_ESTADO_ACTIVACION: ['CONECTADO'],
        })
        resultado = self.mod._build_unidades_df(df)
        self.assertEqual(resultado.iloc[0]['Industria/s'], '')
        self.assertEqual(resultado.iloc[0]['ETAPA GESTIÓN'], '')


class TestFiltrarContactosPorCdb(unittest.TestCase):
    """GeneralModule._filtrar_contactos_por_cdb(): caja derecha, apartado
    Contactos -- Razón Social seleccionada -> CDB -> Contactos asociados.
    Deben aparecer TODOS los contactos del CDB, sin límite, y ninguno de
    otro CDB. Función pura (no usa self.*)."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def _df_contactos(self):
        return pd.DataFrame({
            'CDB': ['CDB001', 'CDB001', 'CDB001', 'CDB002'],
            'Nombre': ['Pedro', 'Ana', 'Luis', 'Otro'],
            'Apellidos': ['Prueba', 'Test', 'Gomez', 'CDB'],
        })

    def test_muestra_todos_los_contactos_del_cdb(self):
        resultado = self.mod._filtrar_contactos_por_cdb(self._df_contactos(), 'CDB001')
        self.assertEqual(len(resultado), 3, "Deben aparecer los 3 contactos de CDB001, sin limitar a uno solo.")
        self.assertEqual(sorted(resultado['Nombre'].tolist()), ['Ana', 'Luis', 'Pedro'])

    def test_no_mezcla_contactos_de_otro_cdb(self):
        resultado = self.mod._filtrar_contactos_por_cdb(self._df_contactos(), 'CDB001')
        self.assertNotIn('Otro', resultado['Nombre'].tolist())

    def test_cdb_inexistente_devuelve_vacio(self):
        resultado = self.mod._filtrar_contactos_por_cdb(self._df_contactos(), 'CDB_NO_EXISTE')
        self.assertTrue(resultado.empty)

    def test_df_contactos_vacio_no_falla(self):
        resultado = self.mod._filtrar_contactos_por_cdb(pd.DataFrame(), 'CDB001')
        self.assertTrue(resultado.empty)

    def test_sin_columna_cdb_no_falla(self):
        resultado = self.mod._filtrar_contactos_por_cdb(pd.DataFrame({'Nombre': ['Pedro']}), 'CDB001')
        self.assertTrue(resultado.empty)


class TestConstruirMapaDirectorEmpresaPbi(unittest.TestCase):
    """GeneralModule._construir_mapa_director_empresa_pbi(): correo y
    teléfono del "Director de empresa" (caja derecha, tarjeta resaltada)
    leídos desde BBDD CLIENTES CM.xlsx (Power BI), CDB -> {'correo':...,
    'telefono':...}. Es un dato de la EMPRESA, no de cada contacto
    individual. Función pura estática, fuente de solo lectura."""

    def test_construye_mapa_cdb_correo_y_telefono(self):
        df_pbi = pd.DataFrame({
            'CDB': ['CDB001', 'CDB002'],
            'Nombre': ['Empresa A', 'Empresa B'],
            'Correo electrónico': ['contacto@empresaa.example', 'contacto@empresab.example'],
            'Teléfono': ['+56911111111', '+56922222222'],
        })
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertEqual(mapa, {
            'CDB001': {'correo': 'contacto@empresaa.example', 'telefono': '+56911111111', 'direccion': '', 'comuna': ''},
            'CDB002': {'correo': 'contacto@empresab.example', 'telefono': '+56922222222', 'direccion': '', 'comuna': ''},
        })

    def test_solo_correo_sin_columna_telefono_no_falla(self):
        df_pbi = pd.DataFrame({'CDB': ['CDB001'], 'Correo electrónico': ['a@a.example']})
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertEqual(mapa, {'CDB001': {'correo': 'a@a.example', 'telefono': '', 'direccion': '', 'comuna': ''}})

    def test_solo_telefono_sin_columna_correo_no_falla(self):
        df_pbi = pd.DataFrame({'CDB': ['CDB001'], 'Teléfono': ['+56911111111']})
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertEqual(mapa, {'CDB001': {'correo': '', 'telefono': '+56911111111', 'direccion': '', 'comuna': ''}})

    def test_cdb_sin_datos_no_provoca_errores(self):
        df_pbi = pd.DataFrame({'CDB': ['CDB001'], 'Correo electrónico': [float('nan')], 'Teléfono': [float('nan')]})
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertEqual(mapa, {'CDB001': {'correo': '', 'telefono': '', 'direccion': '', 'comuna': ''}})

    def test_cdb_no_encontrado_no_esta_en_el_mapa(self):
        df_pbi = pd.DataFrame({'CDB': ['CDB001'], 'Correo electrónico': ['a@a.example'], 'Teléfono': ['+56911111111']})
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertNotIn('CDB_NO_EXISTE', mapa)

    def test_df_vacio_devuelve_mapa_vacio(self):
        self.assertEqual(GeneralModule._construir_mapa_director_empresa_pbi(pd.DataFrame()), {})

    def test_sin_columnas_esperadas_devuelve_mapa_vacio(self):
        df_pbi = pd.DataFrame({'CDB': ['CDB001'], 'Nombre': ['Empresa A']})
        self.assertEqual(GeneralModule._construir_mapa_director_empresa_pbi(df_pbi), {})

    def test_cdb_duplicado_conserva_el_primer_valor_no_vacio_de_cada_campo(self):
        df_pbi = pd.DataFrame({
            'CDB': ['CDB001', 'CDB001'],
            'Correo electrónico': [float('nan'), 'segundo@empresaa.example'],
            'Teléfono': ['+56911111111', float('nan')],
        })
        mapa = GeneralModule._construir_mapa_director_empresa_pbi(df_pbi)
        self.assertEqual(mapa['CDB001'], {'correo': 'segundo@empresaa.example', 'telefono': '+56911111111', 'direccion': '', 'comuna': ''})


class TestPowerBiDirectorEmpresaLoaderThread(unittest.TestCase):
    """PowerBiDirectorEmpresaLoaderThread: lee CDB + Correo electrónico +
    Teléfono desde BBDD CLIENTES CM.xlsx (Power BI) en un hilo secundario
    sin bloquear la UI, mismo patrón que
    PowerBiFlotasLoaderThread/PowerBiSyncWorker. Nunca escribe en ese Excel
    (solo lectura)."""

    ASYNC_TIMEOUT_MS = 20000

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                QApplication.processEvents()
                return True
            time.sleep(interval_ms / 1000.0)
        return False

    def test_emite_el_mapa_de_correo_y_telefono_leido_del_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            powerbi_path = os.path.join(tmp, 'powerbi.xlsx')
            # Teléfono sin "+": Excel/openpyxl puede tratar un string que
            # empieza con "+" como si fuera el inicio de una fórmula y
            # descartarlo al guardar/leer -- irrelevante para lo que prueba
            # este test (que el hilo lee y arma el mapa correctamente).
            pd.DataFrame({
                'CDB': ['10001', '10002'],
                'Nombre': ['Empresa A', 'Empresa B'],
                'Correo electrónico': ['a@empresaa.example', 'b@empresab.example'],
                'Teléfono': ['56911111111', '56922222222'],
            }).to_excel(powerbi_path, index=False)

            resultado = {}
            thread = PowerBiDirectorEmpresaLoaderThread(powerbi_path)
            thread.data_loaded_signal.connect(lambda mapa: resultado.update(mapa=mapa))
            thread.start()

            cargado = self._wait_until(lambda: 'mapa' in resultado, timeout_ms=self.ASYNC_TIMEOUT_MS)
            self.assertTrue(cargado, "Fallo: PowerBiDirectorEmpresaLoaderThread no terminó dentro del timeout.")
            self.assertEqual(resultado['mapa'], {
                '10001': {'correo': 'a@empresaa.example', 'telefono': '56911111111', 'direccion': '', 'comuna': ''},
                '10002': {'correo': 'b@empresab.example', 'telefono': '56922222222', 'direccion': '', 'comuna': ''},
            })

    def test_archivo_inexistente_emite_mapa_vacio_sin_fallar(self):
        resultado = {}
        thread = PowerBiDirectorEmpresaLoaderThread(os.path.join(tempfile.gettempdir(), 'no_existe_powerbi.xlsx'))
        thread.data_loaded_signal.connect(lambda mapa: resultado.update(mapa=mapa))
        thread.start()

        cargado = self._wait_until(lambda: 'mapa' in resultado, timeout_ms=self.ASYNC_TIMEOUT_MS)
        self.assertTrue(cargado, "Fallo: PowerBiDirectorEmpresaLoaderThread no terminó dentro del timeout.")
        self.assertEqual(resultado['mapa'], {})


class TestAplicarFiltrosUnidades(unittest.TestCase):
    """GeneralModule._aplicar_filtros_unidades(): filtros de la vista Unidades.
    Cada columna recibe un conjunto de valores permitidos (comparados sin
    mayúsculas ni tildes, ver _clave_flota_texto); None no filtra y un
    conjunto vacío no deja nada. Función pura (no usa self.*)."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    @staticmethod
    def _claves(*valores):
        return {_clave_flota_texto(v) for v in valores}

    def _df_unidades(self):
        return pd.DataFrame({
            'VIN': ['VIN001', 'VIN002', 'VIN003', 'VIN004'],
            'CHASIS': ['CH1', 'CH2', 'CH3', 'CH4'],
            'Razón Social': ['Empresa A', 'Empresa A', 'Empresa B', 'Empresa B'],
            'CDB': ['CDB001', 'CDB001', 'CDB002', 'CDB002'],
            'Flota VC': ['FLOTA ABC', 'FLOTA XYZ', 'FLOTA ABC', 'FLOTA ABC'],
            'Estado Activación': ['CONECTADO', 'DESCONECTADO', 'Activando', 'Otro Estado Raro'],
            'Industria/s': ['Minería', 'Minería', 'Transporte', 'Construcción'],
        })

    def test_industria_filtra_correctamente_ignorando_tildes(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Industria/s': self._claves('mineria')})
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['VIN001', 'VIN002'])

    def test_industria_sin_seleccion_deja_vacio(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Industria/s': set()})
        self.assertTrue(resultado.empty)

    def test_sin_filtros_no_filtra(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {})
        self.assertEqual(len(resultado), 4)
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Razón Social': None})
        self.assertEqual(len(resultado), 4)

    def test_razon_social_filtra_correctamente(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Razón Social': self._claves('empresa a')})
        self.assertEqual(len(resultado), 2)
        self.assertTrue((resultado['Razón Social'] == 'Empresa A').all())

    def test_razon_social_sin_seleccion_deja_vacio(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Razón Social': set()})
        self.assertTrue(resultado.empty)

    def test_estado_activacion_filtra_correctamente(self):
        resultado = self.mod._aplicar_filtros_unidades(
            self._df_unidades(), {'Estado Activación': self._claves('Desconectado')})
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['VIN'], 'VIN002')

    def test_estado_activacion_sin_seleccion_deja_vacio(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {'Estado Activación': set()})
        self.assertTrue(resultado.empty)

    def test_combina_razon_social_y_estado_activacion(self):
        resultado = self.mod._aplicar_filtros_unidades(self._df_unidades(), {
            'Razón Social': self._claves('Empresa A'),
            'Estado Activación': self._claves('Desconectado', 'Activando'),
        })
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['VIN'], 'VIN002')

    def test_df_unidades_vacio_no_falla(self):
        resultado = self.mod._aplicar_filtros_unidades(pd.DataFrame(), {'Razón Social': set()})
        self.assertTrue(resultado.empty)


class TestEstadoActivacionColores(unittest.TestCase):
    """ESTADO_ACTIVACION_COLORES: colores llamativos del badge de 'Estado
    Activación' en la tabla de Unidades (caja izquierda), y
    COLUMNAS_UNIDADES_VISIBLES: CDB y Flota VC quedan fuera de esa tabla a
    pedido explícito (se siguen usando internamente para filtrar por CDB en
    la caja derecha). VIN también queda fuera
    de la vista desde el 10-09-2026 (a pedido de la contraparte comercial) pero se conserva en
    COLUMNAS_UNIDADES y COLUMNAS_BUSQUEDA_UNIDADES -- ver
    TestAplicarBusquedaUnidades para la búsqueda por VIN oculto."""

    def test_los_5_estados_tienen_color_propio_y_distinto(self):
        self.assertEqual(
            set(ESTADO_ACTIVACION_COLORES.keys()),
            {'CONECTADO', 'DESCONECTADO', 'ACTIVANDO', 'SIN FLOTA', 'NO APLICA'},
        )
        fondos = [c[0] for c in ESTADO_ACTIVACION_COLORES.values()]
        self.assertEqual(len(fondos), len(set(fondos)), "Cada estado debe tener un color de fondo distinto.")

    def test_no_aplica_es_naranja(self):
        """Color agregado a pedido explícito (20-09-2026) para la tarjeta de
        Unidades (caja izquierda): antes 'No aplica' no tenía badge propio."""
        self.assertEqual(ESTADO_ACTIVACION_COLORES['NO APLICA'], ('#FFEDD5', "#C2410C"))

    def test_columnas_visibles_no_incluyen_cdb_ni_flota_vc(self):
        self.assertNotIn('CDB', COLUMNAS_UNIDADES_VISIBLES)
        self.assertNotIn('Flota VC', COLUMNAS_UNIDADES_VISIBLES)
        self.assertIn('Estado Activación', COLUMNAS_UNIDADES_VISIBLES)

    def test_vin_no_esta_en_columnas_visibles_pero_si_en_base_y_busqueda(self):
        """VIN se oculta como columna visible en Unidades (10-09-2026, a
        pedido de la contraparte comercial) pero debe seguir existiendo en el DataFrame base
        y en las columnas de búsqueda, para que el buscador global de
        MainWindow lo siga encontrando exactamente igual que antes."""
        self.assertNotIn('VIN', COLUMNAS_UNIDADES_VISIBLES)
        self.assertIn('VIN', COLUMNAS_UNIDADES)
        self.assertIn('VIN', COLUMNAS_BUSQUEDA_UNIDADES)

    def test_industria_visible_en_unidades(self):
        self.assertIn('Industria/s', COLUMNAS_UNIDADES_VISIBLES)
        self.assertIn('Industria/s', COLUMNAS_UNIDADES)

    def test_etapa_gestion_visible_en_unidades(self):
        self.assertIn('ETAPA GESTIÓN', COLUMNAS_UNIDADES_VISIBLES)
        self.assertIn('ETAPA GESTIÓN', COLUMNAS_UNIDADES)

    def test_industria_se_mantiene_en_columnas_clientes_base(self):
        """'Industria/s' se oculta como columna VISIBLE en Clientes (ver
        filter_clientes en general.py), pero no se elimina de la estructura
        de datos interna: sigue en COLUMNAS_CLIENTES / df_clientes_base,
        porque el filtro por industria de esta misma caja la sigue
        necesitando."""
        self.assertIn('Industria/s', COLUMNAS_CLIENTES)


class TestResolverTextoFlotaVcSinCliente(unittest.TestCase):
    """GeneralModule._resolver_texto_flota_vc_sin_cliente(): caja derecha,
    fila de Flota sin CDB asociado a ningún cliente (CDB vacío, "-", o sin
    match) -- solo se puede mostrar el dato de Flota VC de esa fila. Si
    tampoco hay Flota VC, devuelve None (la UI lo traduce como "No se
    encontró información" en rojo). Función pura (no usa self.*)."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def test_devuelve_la_flota_vc_cuando_existe(self):
        self.assertEqual(self.mod._resolver_texto_flota_vc_sin_cliente('FLOTA ABC'), 'FLOTA ABC')

    def test_devuelve_la_flota_vc_con_espacios_recortados(self):
        self.assertEqual(self.mod._resolver_texto_flota_vc_sin_cliente('  FLOTA ABC  '), 'FLOTA ABC')

    def test_flota_vc_vacia_devuelve_none(self):
        self.assertIsNone(self.mod._resolver_texto_flota_vc_sin_cliente(''))

    def test_flota_vc_none_devuelve_none(self):
        self.assertIsNone(self.mod._resolver_texto_flota_vc_sin_cliente(None))

    def test_flota_vc_nan_devuelve_none(self):
        self.assertIsNone(self.mod._resolver_texto_flota_vc_sin_cliente(float('nan')))


class TestPopulateContactCards(unittest.TestCase):
    """GeneralModule._populate_contact_cards(): rellena un layout con una
    tarjeta por contacto -- lógica compartida por la caja "Contactos
    encontrados" del Resumen y por la pestaña "Contactos" completa (caja
    derecha). Requiere una instancia real de QWidget/QVBoxLayout (no es una
    función pura), por eso se prueba aparte de las funciones de filtrado."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def setUp(self):
        # El QWidget contenedor debe mantenerse referenciado durante todo el
        # test: si se descarta, Python lo recolecta y el layout que posee
        # queda "wrapped C/C++ object ... deleted" (RuntimeError de PyQt).
        self._contenedor = QWidget()

    def _layout_vacio(self):
        return QVBoxLayout(self._contenedor)

    def test_crea_una_tarjeta_por_contacto_sin_director_empresa(self):
        layout = self._layout_vacio()
        contactos = pd.DataFrame({
            'Nombre': ['Pedro', 'Ana'],
            'Apellidos': ['Prueba', 'Test'],
            'Correo electrónico': ['pedro@propio.example', 'ana@propio.example'],
            'Número móvil': ['+56911111111', '+56922222222'],
        })
        self.mod._populate_contact_cards(layout, contactos, None)
        # 2 tarjetas + 1 stretch final, sin tarjeta de Director de empresa
        self.assertEqual(layout.count(), 3)

    def test_cada_contacto_usa_su_propio_correo_no_el_de_power_bi(self):
        """Bug real corregido: antes se le ponía a TODOS los contactos el
        mismo correo de Power BI, pisando el correo propio de cada uno en
        contactos.xlsx. Ahora cada tarjeta debe mostrar su propio correo."""
        layout = self._layout_vacio()
        contactos = pd.DataFrame({
            'Nombre': ['Pedro'],
            'Apellidos': ['Prueba'],
            'Correo electrónico': ['pedro@propio.example'],
            'Número móvil': ['+56911111111'],
        })
        director_empresa = {'correo': 'correo-empresa@pbi.example', 'telefono': '+56900000000'}
        self.mod._populate_contact_cards(layout, contactos, director_empresa)

        tarjeta_contacto = layout.itemAt(1).widget()  # índice 0 = tarjeta de Director de empresa
        textos = [lbl.text() for lbl in tarjeta_contacto.findChildren(QLabel)]
        self.assertTrue(any('pedro@propio.example' in t for t in textos))
        self.assertFalse(any('correo-empresa@pbi.example' in t for t in textos))

    def test_director_empresa_agrega_tarjeta_resaltada(self):
        layout = self._layout_vacio()
        director_empresa = {'correo': 'correo-empresa@pbi.example', 'telefono': '+56900000000'}
        self.mod._populate_contact_cards(layout, pd.DataFrame(), director_empresa)
        # tarjeta Director de empresa + mensaje "sin contactos" + stretch
        self.assertEqual(layout.count(), 3)
        tarjeta_director = layout.itemAt(0).widget()
        textos = [lbl.text() for lbl in tarjeta_director.findChildren(QLabel)]
        self.assertTrue(any('correo-empresa@pbi.example' in t for t in textos))
        self.assertTrue(any('+56900000000' in t for t in textos))

    def test_director_empresa_sin_datos_no_agrega_tarjeta(self):
        layout = self._layout_vacio()
        self.mod._populate_contact_cards(layout, pd.DataFrame(), {'correo': '', 'telefono': ''})
        self.assertEqual(layout.count(), 2)  # mensaje "sin contactos" + stretch, sin tarjeta de Director

    def test_sin_contactos_muestra_mensaje_vacio(self):
        layout = self._layout_vacio()
        self.mod._populate_contact_cards(layout, pd.DataFrame(), None)
        self.assertEqual(layout.count(), 2)  # mensaje + stretch

    def test_limpia_el_layout_antes_de_repoblar(self):
        layout = self._layout_vacio()
        contactos = pd.DataFrame({'Nombre': ['Pedro'], 'Apellidos': ['Prueba'], 'Número móvil': ['']})
        self.mod._populate_contact_cards(layout, contactos, None)
        self.mod._populate_contact_cards(layout, pd.DataFrame(), None)
        self.assertEqual(layout.count(), 2, "La segunda llamada debe reemplazar el contenido, no acumularlo.")


class TestAplicarBusquedaUnidades(unittest.TestCase):
    """GeneralModule._aplicar_busqueda_unidades(): buscador global de
    MainWindow aplicado a la caja izquierda -> Unidades. AND entre términos
    (separados por espacios), cada término puede coincidir en Razón
    Social/VIN/CDB indistintamente (COLUMNAS_BUSQUEDA_UNIDADES). Función
    pura estática -- no requiere __init__ ni instancia."""

    def _df_unidades(self):
        return pd.DataFrame({
            'VIN': ['1234567', '7654321', '1111111'],
            'CHASIS': ['CH1', 'CH2', 'CH3'],
            'Razón Social': ['Empresa Demo Camiones Chile', 'Empresa Demo Servicios Chile', 'Camiones ABC'],
            'CDB': ['1001', '1002', '1003'],
            'Flota VC': ['FLOTA A', 'FLOTA B', 'FLOTA C'],
            'Estado Activación': ['CONECTADO', 'DESCONECTADO', 'ACTIVANDO'],
        })

    def test_busqueda_simple_encuentra_por_razon_social(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), 'Empresa Demo')
        self.assertEqual(sorted(resultado['CDB'].tolist()), ['1001', '1002'])

    def test_busqueda_por_vin(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), '1234567')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Razón Social'], 'Empresa Demo Camiones Chile')

    def test_busqueda_por_cdb(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), '1001')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['VIN'], '1234567')

    def test_busqueda_and_dos_terminos(self):
        """"Empresa Demo Camiones" debe interpretarse como Empresa Demo AND Camiones, no
        como la frase exacta -- solo "Empresa Demo Camiones Chile" tiene ambos
        términos (Empresa Demo Servicios Chile no tiene "Camiones")."""
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), 'Empresa Demo Camiones')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Razón Social'], 'Empresa Demo Camiones Chile')

    def test_busqueda_and_multiples_terminos(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), 'Empresa Demo Camiones Chile')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Razón Social'], 'Empresa Demo Camiones Chile')

    def test_and_entre_columnas_distintas(self):
        """Un término puede matchear en una columna y otro término en una
        columna distinta -- ambos deben cumplirse (AND), no exigirse en la
        misma columna."""
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), 'Empresa Demo 1001')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['CDB'], '1001')

    def test_case_insensitive(self):
        base = self._df_unidades()
        resultados = [
            GeneralModule._aplicar_busqueda_unidades(base, 'EMPRESA'),
            GeneralModule._aplicar_busqueda_unidades(base, 'empresa'),
            GeneralModule._aplicar_busqueda_unidades(base, 'Empresa Demo'),
        ]
        tamanos = [len(r) for r in resultados]
        self.assertEqual(tamanos, [2, 2, 2])
        for r in resultados[1:]:
            self.assertEqual(sorted(r['CDB'].tolist()), sorted(resultados[0]['CDB'].tolist()))

    def test_espacios_extra_no_generan_terminos_vacios(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), '   Empresa Demo    Camiones   ')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Razón Social'], 'Empresa Demo Camiones Chile')

    def test_valores_vacios_no_producen_error(self):
        df = pd.DataFrame({
            'VIN': ['', '1234567'],
            'Razón Social': ['', ''],
            'CDB': ['', ''],
        })
        resultado = GeneralModule._aplicar_busqueda_unidades(df, '1234567')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['VIN'], '1234567')

    def test_buscador_vacio_devuelve_todo(self):
        base = self._df_unidades()
        resultado = GeneralModule._aplicar_busqueda_unidades(base, '')
        self.assertEqual(len(resultado), len(base))

    def test_buscador_solo_espacios_devuelve_todo(self):
        base = self._df_unidades()
        resultado = GeneralModule._aplicar_busqueda_unidades(base, '   ')
        self.assertEqual(len(resultado), len(base))

    def test_sin_coincidencias_devuelve_vacio(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(self._df_unidades(), 'NO_EXISTE_NADA_PARECIDO')
        self.assertTrue(resultado.empty)

    def test_df_vacio_no_falla(self):
        resultado = GeneralModule._aplicar_busqueda_unidades(pd.DataFrame(columns=COLUMNAS_BUSQUEDA_UNIDADES), 'empresa')
        self.assertTrue(resultado.empty)

    def test_se_combina_con_filtros_existentes(self):
        """El buscador debe combinarse (AND) con _aplicar_filtros_unidades,
        no reemplazarlo: aplicar primero el filtro de Estado Activación y
        luego el buscador debe devolver solo lo que cumple ambas
        condiciones."""
        base = self._df_unidades()
        pre_filtrado = base[base['Estado Activación'] == 'CONECTADO']
        resultado = GeneralModule._aplicar_busqueda_unidades(pre_filtrado, 'Empresa Demo Camiones')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Estado Activación'], 'CONECTADO')

        # "Empresa Demo Servicios Chile" (CDB 1002) tiene Empresa Demo pero no Camiones;
        # además su Estado Activación es DESCONECTADO -- debe quedar fuera
        # tanto por el buscador como por el filtro previo.
        self.assertNotIn('1002', resultado['CDB'].tolist())


class TestBuscadorGlobalTresPestanas(unittest.TestCase):
    """Buscador global de MainWindow (GeneralModule.search_input/
    filter_table), a pedido explícito (15-09-2026): ahora afecta las 3
    sub-pestañas de la caja izquierda (Cliente/Flota/Unidades), no solo
    Unidades como antes. Cliente y Unidades buscan directo por 'Razón
    Social'; Flota (que no tiene esa columna) se resuelve vía CDB (ver
    GeneralModule._cdbs_por_busqueda_razon_social).

    La caja derecha usa el mismo patrón de "preservar si sigue visible,
    vaciar si no" que ya usaba Unidades para su VIN seleccionado
    (_sincronizar_seleccion_vin) -- ver GeneralModule._sincronizar_seleccion_cliente/
    _sincronizar_seleccion_flota.
    Requiere una instancia real (con datos mock cargados vía DataManager,
    misma fuente que ComercialModule)."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."

    def setUp(self):
        # Datos mock de generar_mock_data.py: 'EMPRESA PRUEBA S.A.' (CDB
        # '10001') y 'TRANSPORTES TEST' (CDB '10002').
        self._df_unidades_base_original = self.module.df_unidades_base.copy()
        self._df_comercial_raw_original = self.module.df_comercial_raw.copy()
        self.module.search_input.setText("")
        self.module.filter_table()
        self.module._switch_left_view(0)  # pestaña "Cliente"
        self.module._on_cliente_card_clicked(0)
        QApplication.processEvents()
        self._cdb_esperado = self.module._selected_cdb
        self.assertIsNotNone(self._cdb_esperado, "Precondición del test: debe haber un cliente seleccionado.")

    def tearDown(self):
        # test_busqueda_en_unidades_no_toca_la_caja_derecha_de_cliente
        # inyecta su propio df_unidades_base/df_comercial_raw controlado
        # (mismo mecanismo que TestSeleccionVinUnidades): se restaura acá
        # para no afectar al resto de los tests de esta clase.
        self.module.df_unidades_base = self._df_unidades_base_original
        self.module.df_comercial_raw = self._df_comercial_raw_original
        self.module.search_input.setText("")
        self.module.filter_table()

    def test_busqueda_filtra_la_tabla_de_clientes_por_razon_social(self):
        self.module.search_input.setText("EMPRESA PRUEBA")
        self.module.filter_table()
        QApplication.processEvents()

        df_clientes = self.module._df_clientes_visible
        self.assertFalse(df_clientes.empty)
        self.assertTrue((df_clientes['Razón Social'] == 'EMPRESA PRUEBA S.A.').all())

    def test_busqueda_filtra_la_tabla_de_unidades(self):
        self.module.search_input.setText("EMPRESA PRUEBA")
        self.module.filter_table()
        QApplication.processEvents()

        df_unidades = self.module._df_unidades_visible
        self.assertFalse(df_unidades.empty)
        self.assertTrue((df_unidades['Razón Social'] == 'EMPRESA PRUEBA S.A.').all())

    def test_buscador_vacio_restaura_las_2_tablas(self):
        self.module.search_input.setText("EMPRESA PRUEBA")
        self.module.filter_table()
        QApplication.processEvents()

        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()

        self.assertEqual(len(self.module._df_unidades_visible), len(self.module.df_unidades_base))
        self.assertEqual(len(self.module._df_clientes_visible), len(self.module.df_clientes_base))

    def test_cliente_seleccionado_se_mantiene_si_sigue_visible_tras_la_busqueda(self):
        self.module.search_input.setText("EMPRESA")  # sigue matcheando 'EMPRESA PRUEBA S.A.'
        self.module.filter_table()
        QApplication.processEvents()

        self.assertEqual(self.module._selected_cdb, self._cdb_esperado)
        self.assertEqual(self.module.right_stack.currentIndex(), 1)

    def test_cliente_seleccionado_se_vacia_si_la_busqueda_lo_excluye(self):
        self.module.search_input.setText("TRANSPORTES")  # no matchea 'EMPRESA PRUEBA S.A.'
        self.module.filter_table()
        QApplication.processEvents()

        self.assertIsNone(self.module._selected_cdb)
        self.assertEqual(self.module.right_stack.currentIndex(), 0)

    def test_busqueda_en_unidades_no_toca_la_caja_derecha_de_cliente(self):
        """Si el usuario está en la pestaña Unidades (VIN seleccionado en la
        caja derecha), buscar no debe hacer que filter_clientes()/
        filter_flota() (también reevaluadas por filter_table(), ya que ahora
        el buscador afecta las 3 sub-pestañas) fuercen la caja derecha al
        detalle de Cliente (índice 1) o a su estado vacío (índice 0) -- debe
        seguir mostrando lo que corresponda al contexto de VIN (índice 3 o
        4), gobernado únicamente por la lógica propia de Unidades."""
        self.module.df_unidades_base = _df_unidades_test({
            'VIN': ['VINBUSQUEDA0001'], 'CHASIS': ['CHBUSQ1'],
            'Razón Social': ['EMPRESA PRUEBA S.A.'], 'CDB': ['10001'],
            'Flota VC': ['FLOTA X'], 'Estado Activación': ['CONECTADO'],
            'Industria/s': ['Minería'], 'ETAPA GESTIÓN': ['COMERCIAL'],
        })
        self.module.df_comercial_raw = pd.DataFrame({
            'VIN': ['VINBUSQUEDA0001'], 'CHASIS': ['CHBUSQ1'], 'RAZÓN SOCIAL': ['EMPRESA PRUEBA S.A.'],
        })
        self.module.filter_unidades()
        self.module._switch_left_view(1)  # pestaña "Unidades"
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()
        self.assertEqual(self.module._vin_seleccionado, 'VINBUSQUEDA0001')
        titulo_antes = self.module.lbl_vin_detalle_title.text()

        # "EMPRESA" también matchea la Razón Social del VIN de prueba (misma
        # columna que usa el buscador de Unidades), así que la unidad sigue
        # visible ahí -- lo único que cambiaría de no estar el guard sería
        # que filter_clientes()/filter_flota() reescriban la caja derecha.
        self.module.search_input.setText("EMPRESA")
        self.module.filter_table()
        QApplication.processEvents()

        self.assertEqual(self.module._vin_seleccionado, 'VINBUSQUEDA0001', "El VIN debe seguir visible en Unidades con este término.")
        self.assertEqual(self.module.right_stack.currentIndex(), 4, "La caja derecha debe seguir mostrando el contexto de VIN.")
        self.assertEqual(self.module.lbl_vin_detalle_title.text(), titulo_antes)


class TestClientesYUnidadesColumnasVisibles(unittest.TestCase):
    """Desde el rediseño a tarjetas (20-09-2026), Cliente/Flota/Unidades ya
    no son tablas con columnas ocultas/visibles -- son tarjetas
    (GeneralClienteCard/GeneralUnidadCard). 'Industria/s' ahora SÍ se
    muestra en la tarjeta de Cliente (a pedido explícito, junto con RUT/
    CDB) y 'VIN' ahora SÍ se muestra (y es copiable) en la tarjeta de
    Unidades -- ambos dejaron de estar ocultos con el cambio de diseño.
    'ETAPA GESTIÓN' sigue coloreada reutilizando exactamente los colores
    que MODULE_COLORS (colors.py) ya asigna a Comercial/Operaciones.
    Requiere una instancia real con datos mock (misma fuente que
    TestBuscadorAislaCajaDerecha) para verificar lo que efectivamente se
    pinta en las tarjetas, no solo los DataFrames internos."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."

    def setUp(self):
        # Vuelve siempre a la pestaña Cliente (índice 0) como estado base:
        # con el render diferido de pestañas ocultas (Fase 5, 21-09-2026),
        # las tarjetas de la pestaña visible son las únicas que se pintan de
        # inmediato -- fijar un punto de partida conocido evita que el orden
        # de ejecución de los tests deje left_stack en otro índice.
        self.module._switch_left_view(0)
        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()

    def _cargar_unidad_de_prueba(self, etapa_gestion='COMERCIAL'):
        """Otras clases de test comparten el mismo Excel mock (y el mismo
        DataManager singleton) dentro de test_main.py y pueden agregar,
        editar o eliminar camiones como parte de lo que ellas mismas
        prueban -- por eso estos tests de integración NO deben asumir que
        una fila concreta de datos mock (p.ej. "TRANSPORTES TEST") sobrevive
        intacta hasta el final de toda la batería. Se inyecta acá un
        DataFrame propio y controlado en df_unidades_base (mismo mecanismo
        de "inyección post-guardado" que ya usa el resto de la app, ver
        docs/02_Motor_de_Datos_Core.md) y se reaplica filter_unidades() para
        seguir probando el pipeline real de la caja izquierda.

        Cambia primero a la pestaña Unidades (índice 2): con el render
        diferido de pestañas ocultas (Fase 5, 21-09-2026), filter_unidades()
        solo construye las tarjetas Qt (self.module._unidad_cards) si esa
        pestaña está visible -- si no, solo actualiza el DataFrame lógico y
        queda pendiente hasta que el usuario entre a esa pestaña."""
        self.module._switch_left_view(1)
        self.module.df_unidades_base = _df_unidades_test({
            'VIN': ['VINPRUEBA0001'], 'CHASIS': ['CHPRUEBA1'],
            'Razón Social': ['EMPRESA INTEGRACION TEST'], 'CDB': ['CDBPRUEBA1'],
            'Flota VC': ['FLOTA PRUEBA'], 'Estado Activación': ['CONECTADO'],
            'Industria/s': ['Minería'], 'ETAPA GESTIÓN': [etapa_gestion],
        })
        self.module.filter_unidades()
        QApplication.processEvents()

    def test_industria_visible_en_tarjeta_de_cliente(self):
        df_clientes = self.module._df_clientes_visible
        self.assertFalse(df_clientes.empty)
        card = self.module._cliente_cards[str(df_clientes.iloc[0]['Clave'])]
        self.assertIn(str(df_clientes.iloc[0]['Industria/s']), card.lbl_sub.text())

    def test_industria_visible_en_unidades(self):
        self._cargar_unidad_de_prueba()
        df_unidades = self.module._df_unidades_visible
        self.assertIn('Industria/s', df_unidades.columns)
        fila = df_unidades[df_unidades['Razón Social'] == 'EMPRESA INTEGRACION TEST'].iloc[0]
        self.assertEqual(fila['Industria/s'], 'Minería')
        self.assertIn('VINPRUEBA0001', self.module._unidad_cards)

    def test_vin_visible_y_copiable_en_tarjeta_de_unidad(self):
        """VIN ahora se muestra (y se puede copiar al pasar el mouse, ver
        CopyableLabel) en la tarjeta de Unidades -- único lugar donde se
        puede copiar el VIN ahora que se quitó el menú contextual de la
        tabla anterior."""
        self._cargar_unidad_de_prueba()
        card = self.module._unidad_cards['VINPRUEBA0001']
        self.assertIn('VINPRUEBA0001', card.lbl_vin.text())

    def test_vin_sigue_siendo_buscable(self):
        """El buscador global de MainWindow (self.search_bar) sigue
        encontrando la unidad por VIN."""
        self._cargar_unidad_de_prueba()

        self.module.search_input.setText("VINPRUEBA0001")
        self.module.filter_table()
        QApplication.processEvents()

        df_resultado = self.module._df_unidades_visible
        self.assertEqual(len(df_resultado), 1)
        self.assertEqual(df_resultado.iloc[0]['Razón Social'], 'EMPRESA INTEGRACION TEST')

        self.module.search_input.setText("")
        self.module.filter_table()

    def test_etapa_gestion_visible_y_con_valor_correcto(self):
        """No se cambia la regla de negocio de ETAPA GESTIÓN (eso vive en
        DataFrameFormatter, ver TestBuildUnidadesDf.test_conserva_industria_
        y_etapa_gestion para el passthrough puro); acá solo se verifica que
        el valor llegue correctamente a la tarjeta de Unidades de la caja
        izquierda a través del pipeline real (filter_unidades)."""
        self._cargar_unidad_de_prueba(etapa_gestion='OPERACIONES')
        df_unidades = self.module._df_unidades_visible
        self.assertIn('ETAPA GESTIÓN', df_unidades.columns)
        fila = df_unidades[df_unidades['Razón Social'] == 'EMPRESA INTEGRACION TEST'].iloc[0]
        self.assertEqual(fila['ETAPA GESTIÓN'], 'OPERACIONES')

    def test_color_etapa_gestion_reutiliza_colores_existentes(self):
        """ETAPA_GESTION_COLORES no inventa una paleta nueva: COMERCIAL/
        OPERACIONES reutilizan tal cual MODULE_COLORS['Comercial']/
        ['Operaciones'] (mismo color que el header de MainWindow usa para
        identificar esas pantallas). CLIENTE retirado del catálogo
        (21-09-2026, matriz de 2 ejes ESTADO COMERCIAL/ESTADO DE ACTIVACIÓN
        ACTUAL): la regla ahora solo produce COMERCIAL u OPERACIONES. Mismo
        patrón que ESTADO_ACTIVACION_COLORES: solo colorea el texto, sin
        fondo (a pedido de la contraparte comercial, 10-09-2026)."""
        self.assertEqual(ETAPA_GESTION_COLORES['COMERCIAL'], MODULE_COLORS['Comercial'])
        self.assertEqual(ETAPA_GESTION_COLORES['OPERACIONES'], MODULE_COLORS['Operaciones'])
        self.assertNotIn('CLIENTE', ETAPA_GESTION_COLORES)


class TestFiltrarHistorialPorVin(unittest.TestCase):
    """GeneralModule._filtrar_historial_por_vin(): caja derecha, apartado
    Historial de una unidad (VIN) -- filtra el mismo LogApp.csv que ya lee
    HistorialModule (IDENTIFICADOR == VIN), más reciente primero. No crea
    ninguna fuente de historial nueva. Función pura (no usa self.*)."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def _df_logs(self):
        return pd.DataFrame({
            'FECHA Y HORA': ['2026-09-10 09:00:00', '2026-09-12 15:30:00', '2026-09-11 08:00:00'],
            'MÓDULO': ['Comercial', 'Comercial', 'Comercial'],
            'IDENTIFICADOR': ['VIN001', 'VIN001', 'VIN002'],
            'CAMPO MODIFICADO': ['ESTADO COMERCIAL', 'MODELO', 'ESTADO COMERCIAL'],
            'VALOR ANTERIOR': ['Revisar', 'FH', 'Revisar'],
            'NUEVO VALOR': ['Vigente', 'FHE', 'Vigente'],
        })

    def test_filtra_solo_los_eventos_del_vin(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs(), 'VIN001')
        self.assertEqual(len(resultado), 2)
        self.assertTrue((resultado['IDENTIFICADOR'] == 'VIN001').all())

    def test_ordena_mas_reciente_primero(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs(), 'VIN001')
        self.assertEqual(resultado.iloc[0]['FECHA Y HORA'], '2026-09-12 15:30:00')
        self.assertEqual(resultado.iloc[1]['FECHA Y HORA'], '2026-09-10 09:00:00')

    def test_vin_sin_eventos_devuelve_vacio(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs(), 'VIN_SIN_HISTORIAL')
        self.assertTrue(resultado.empty)

    def test_vin_vacio_devuelve_vacio(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs(), '')
        self.assertTrue(resultado.empty)

    def test_df_logs_vacio_no_falla(self):
        resultado = self.mod._filtrar_historial_por_vin(pd.DataFrame(), 'VIN001')
        self.assertTrue(resultado.empty)

    def test_df_logs_vacio_conserva_columnas_esperadas(self):
        resultado = self.mod._filtrar_historial_por_vin(pd.DataFrame(), 'VIN001')
        self.assertEqual(list(resultado.columns), COLUMNAS_HISTORIAL)

    def test_comparacion_de_vin_ignora_mayusculas_y_espacios(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs(), '  vin001  ')
        self.assertEqual(len(resultado), 2)

    # --- LogApp.csv migrado desde el .xlsx legado: columna 'VIN' en vez de
    # 'IDENTIFICADOR' (ver migrar_historial_legacy en excel_writer.py, que
    # conserva el encabezado ORIGINAL del archivo legado tal cual venía en
    # vez de normalizarlo). Bug real reportado 15-09-2026: con este esquema,
    # el historial por VIN quedaba siempre vacío aunque historial.py (que no
    # depende del nombre exacto de la columna) sí mostraba los eventos. ---
    def _df_logs_esquema_legado(self):
        return pd.DataFrame({
            'FECHA Y HORA': ['2026-09-10 09:00:00', '2026-09-12 15:30:00'],
            'MÓDULO': ['Comercial', 'Comercial'],
            'VIN': ['VIN001', 'VIN001'],
            'CAMPO MODIFICADO': ['ESTADO COMERCIAL', 'MODELO'],
            'VALOR ANTERIOR': ['Revisar', 'FM'],
            'NUEVO VALOR': ['Vigente', 'FHL'],
        })

    def test_esquema_legado_con_columna_vin_en_vez_de_identificador_tambien_filtra(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs_esquema_legado(), 'VIN001')
        self.assertEqual(len(resultado), 2)
        self.assertEqual(resultado.iloc[0]['NUEVO VALOR'], 'FHL')  # más reciente primero

    def test_esquema_legado_vin_sin_eventos_devuelve_vacio(self):
        resultado = self.mod._filtrar_historial_por_vin(self._df_logs_esquema_legado(), 'VIN_SIN_HISTORIAL')
        self.assertTrue(resultado.empty)

    def test_ninguna_columna_identificadora_reconocida_devuelve_vacio_no_falla(self):
        df_logs_sin_columna_id = pd.DataFrame({
            'FECHA Y HORA': ['2026-09-10 09:00:00'], 'MÓDULO': ['Comercial'],
            'CAMPO MODIFICADO': ['MODELO'], 'VALOR ANTERIOR': ['FM'], 'NUEVO VALOR': ['FH'],
        })
        resultado = self.mod._filtrar_historial_por_vin(df_logs_sin_columna_id, 'VIN001')
        self.assertTrue(resultado.empty)


class TestValorFicha(unittest.TestCase):
    """GeneralModule._valor_ficha(): valor de una columna de la fila de
    df_comercial_raw ya listo para mostrar en la ficha de VIN -- '-' para
    vacío/NaN/None, texto tal cual en caso contrario. Función pura."""

    @classmethod
    def setUpClass(cls):
        cls.mod = GeneralModule.__new__(GeneralModule)

    def test_valor_presente_se_devuelve_tal_cual(self):
        fila = pd.Series({'MODELO': 'FH'})
        self.assertEqual(self.mod._valor_ficha(fila, 'MODELO'), 'FH')

    def test_valor_nan_devuelve_guion(self):
        fila = pd.Series({'MODELO': float('nan')})
        self.assertEqual(self.mod._valor_ficha(fila, 'MODELO'), '-')

    def test_valor_vacio_devuelve_guion(self):
        fila = pd.Series({'MODELO': ''})
        self.assertEqual(self.mod._valor_ficha(fila, 'MODELO'), '-')

    def test_columna_ausente_devuelve_guion(self):
        fila = pd.Series({'MODELO': 'FH'})
        self.assertEqual(self.mod._valor_ficha(fila, 'COLUMNA_QUE_NO_EXISTE'), '-')

    def test_valor_con_espacios_se_recorta(self):
        fila = pd.Series({'MODELO': '  FH  '})
        self.assertEqual(self.mod._valor_ficha(fila, 'MODELO'), 'FH')


class TestSeleccionVinUnidades(unittest.TestCase):
    """Flujo VIN -> ficha -> historial (caja izquierda -> Unidades, caja
    derecha -> contexto de VIN): requiere una instancia real con datos mock
    (mismo patrón que TestBuscadorAislaCajaDerecha/TestClientesYUnidadesColumnasVisibles)
    para poder simular el clic de una tarjeta real de Unidades
    (_on_unidad_card_clicked)."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."

    def setUp(self):
        self.module.search_input.setText("")
        self.module.filter_table()
        self.module._switch_left_view(1)  # pestaña "Unidades"
        QApplication.processEvents()
        self._df_logs_original = self.dm.df_logs.copy()

    def tearDown(self):
        # DataManager es un singleton compartido por toda la batería: no
        # dejar puesto el df_logs sintético de test_logs_updated_* para las
        # clases de test que corran después.
        self.dm.df_logs = self._df_logs_original

    def _cargar_unidad_de_prueba(self):
        """Mismo mecanismo de inyección controlada que
        TestClientesYUnidadesColumnasVisibles._cargar_unidad_de_prueba, pero
        también en df_comercial_raw: _show_vin_detalle busca ahí la fila
        completa (33 columnas) para la ficha, no en df_unidades_base (que
        solo trae las 8 columnas resumidas de la tabla izquierda)."""
        self.module.df_unidades_base = _df_unidades_test({
            'VIN': ['VINFICHA0001'], 'CHASIS': ['CHFICHA1'],
            'Razón Social': ['EMPRESA FICHA TEST'], 'CDB': ['CDBFICHA1'],
            'Flota VC': ['FLOTA FICHA'], 'Estado Activación': ['CONECTADO'],
            'Industria/s': ['Minería'], 'ETAPA GESTIÓN': ['COMERCIAL'],
        })
        self.module.df_comercial_raw = pd.DataFrame({
            'VIN': ['VINFICHA0001'], 'CHASIS': ['CHFICHA1'], 'RAZÓN SOCIAL': ['EMPRESA FICHA TEST'],
            'RUT': ['31.423.846-1'], 'CDB': ['CDBFICHA1'], 'INDUSTRIA': ['Minería'],
            'EJECUTIVO': ['Juan Pérez'], 'MODELO': ['FH'],
        })
        self.module.filter_unidades()
        QApplication.processEvents()

    def _limpiar_seleccion_vin(self):
        self.module._vin_seleccionado = None
        self.module._show_vin_vacio()

    def test_sin_seleccion_muestra_estado_vacio(self):
        self._limpiar_seleccion_vin()
        QApplication.processEvents()
        self.assertIsNone(self.module._vin_seleccionado)
        self.assertEqual(self.module.right_stack.currentIndex(), 3)

    def test_seleccionar_vin_guarda_el_vin_y_muestra_la_ficha(self):
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()

        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0001')
        self.assertEqual(self.module.right_stack.currentIndex(), 4)
        self.assertIn('VINFICHA0001', self.module.lbl_vin_detalle_title.text())

    def test_ficha_muestra_los_datos_completos_del_vin(self):
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()

        fila = self.module.df_comercial_raw.iloc[0]
        self.module._render_ficha_vin(fila)  # mismo método que ya corrió _show_vin_detalle
        valores_mostrados = []
        for grupo_layout in self.module._ficha_vin_layouts.values():
            for i in range(grupo_layout.count()):
                fila_widget = grupo_layout.itemAt(i).widget()
                if fila_widget:
                    valores_mostrados.extend(
                        lbl.text() for lbl in fila_widget.findChildren(QLabel)
                    )
        self.assertTrue(any('EMPRESA FICHA TEST' in v for v in valores_mostrados))
        self.assertTrue(any('Juan Pérez' in v for v in valores_mostrados))

    def test_cambiar_de_vin_actualiza_ficha_e_historial(self):
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()
        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0001')

        # Segundo VIN: reemplaza el df de prueba por uno con un solo VIN
        # distinto y selecciona la única fila disponible.
        self.module.df_unidades_base = _df_unidades_test({
            'VIN': ['VINFICHA0002'], 'CHASIS': ['CHFICHA2'],
            'Razón Social': ['EMPRESA FICHA TEST 2'], 'CDB': ['CDBFICHA2'],
            'Flota VC': ['FLOTA FICHA 2'], 'Estado Activación': ['DESCONECTADO'],
            'Industria/s': ['Forestal'], 'ETAPA GESTIÓN': ['OPERACIONES'],
        })
        self.module.df_comercial_raw = pd.DataFrame({
            'VIN': ['VINFICHA0002'], 'CHASIS': ['CHFICHA2'], 'RAZÓN SOCIAL': ['EMPRESA FICHA TEST 2'],
        })
        self.module.filter_unidades()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()

        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0002')
        self.assertIn('VINFICHA0002', self.module.lbl_vin_detalle_title.text())
        self.assertNotIn('VINFICHA0001', self.module.lbl_vin_detalle_title.text())

    def test_salir_de_unidades_no_deja_la_ficha_de_vin_visible(self):
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()
        self.assertEqual(self.module.right_stack.currentIndex(), 4)

        self.module._switch_left_view(0)  # vuelve a "Cliente"
        QApplication.processEvents()
        self.assertNotIn(self.module.right_stack.currentIndex(), (3, 4))

        self.module._switch_left_view(1)  # vuelve a "Unidades"
        QApplication.processEvents()
        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0001', "El VIN seleccionado se conserva al cambiar de pestaña.")
        self.assertEqual(self.module.right_stack.currentIndex(), 4)

    def _textos_historial_vin(self):
        """Textos de todos los QLabel visibles en el historial del VIN --
        incluye tanto el label "vacío" (agregado directo al layout cuando no
        hay eventos) como los QLabel dentro de cada tarjeta de evento
        (_create_evento_historial_card)."""
        textos = []
        layout = self.module.historial_vin_layout
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is None:
                continue
            if isinstance(widget, QLabel):
                textos.append(widget.text())
            textos.extend(lbl.text() for lbl in widget.findChildren(QLabel))
        return textos

    def test_logs_updated_refresca_el_historial_sin_perder_la_seleccion_del_vin(self):
        """Causa raíz corregida el 15-09-2026: DataManager.set_logs_df()
        (disparado ahora desde SaveExcelThread.logs_actualizados_signal tras
        un guardado real en Comercial) debe hacer que el historial del VIN
        seleccionado se repueble solo, sin perder la selección ni tocar la
        ficha -- ver GeneralModule._on_logs_updated."""
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()
        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0001')
        titulo_ficha_antes = self.module.lbl_vin_detalle_title.text()

        df_logs_nuevo = pd.DataFrame({
            'FECHA Y HORA': ['2026-09-15 10:00:00'], 'MÓDULO': ['Comercial'],
            'IDENTIFICADOR': ['VINFICHA0001'], 'CAMPO MODIFICADO': ['MODELO'],
            'VALOR ANTERIOR': ['FM'], 'NUEVO VALOR': ['FH'],
        })
        self.module.data_manager.set_logs_df(df_logs_nuevo)
        QApplication.processEvents()

        self.assertEqual(self.module._vin_seleccionado, 'VINFICHA0001', "logs_updated no debe cambiar el VIN seleccionado.")
        self.assertEqual(self.module.lbl_vin_detalle_title.text(), titulo_ficha_antes, "logs_updated no debe tocar la ficha.")
        textos = self._textos_historial_vin()
        self.assertTrue(any('MODELO' in t for t in textos), "El campo modificado del nuevo evento debe aparecer en el historial.")
        self.assertTrue(any('FH' in t for t in textos), "El nuevo valor del evento debe aparecer en el historial.")

    def test_logs_updated_no_muestra_eventos_de_otro_vin(self):
        self._cargar_unidad_de_prueba()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()

        df_logs_otro_vin = pd.DataFrame({
            'FECHA Y HORA': ['2026-09-15 10:00:00'], 'MÓDULO': ['Comercial'],
            'IDENTIFICADOR': ['VIN_QUE_NO_ES_ESTE'], 'CAMPO MODIFICADO': ['MODELO'],
            'VALOR ANTERIOR': ['FM'], 'NUEVO VALOR': ['FH'],
        })
        self.module.data_manager.set_logs_df(df_logs_otro_vin)
        QApplication.processEvents()

        textos = self._textos_historial_vin()
        self.assertFalse(any('VIN_QUE_NO_ES_ESTE' in t for t in textos))
        self.assertTrue(any('No hay eventos' in t for t in textos))

    def test_logs_updated_sin_vin_seleccionado_no_falla(self):
        self._limpiar_seleccion_vin()
        QApplication.processEvents()
        self.assertIsNone(self.module._vin_seleccionado)
        try:
            self.module.data_manager.set_logs_df(pd.DataFrame())
            QApplication.processEvents()
        except Exception as e:
            self.fail(f"_on_logs_updated no debe fallar sin VIN seleccionado: {e}")


class _FakeSaveThreadSignalGeneral:
    """Reemplazo minimo de pyqtSignal para simular SaveExcelThread sin
    lanzar un QThread real (mismo patrón que _FakeSaveThreadSignal en
    test_comercial.py -- no se importa desde ahí para no acoplar los dos
    archivos de test entre sí con una clase "privada")."""

    def __init__(self):
        self._slot = None

    def connect(self, slot):
        self._slot = slot

    def emit(self, *args):
        if self._slot is not None:
            self._slot(*args)


class _FakeAddContactoThreadExitoso:
    """Evita tocar contactos.xlsx real durante el test: firma real de
    AddContactoThread (contactos.py): __init__(writer, new_data) y
    finished_signal(bool, dict)."""

    def __init__(self, writer, new_data):
        self.writer = writer
        self.new_data = new_data
        self.finished_signal = _FakeSaveThreadSignalGeneral()

    def start(self):
        self.finished_signal.emit(True, self.new_data)


class TestAgregarContactoCliente(unittest.TestCase):
    """Cubre "Agregar contacto" desde Clientes y Flotas -> Cliente
    seleccionado -> pestaña Contactos (ver general.py::
    _handle_agregar_contacto/_on_agregar_contacto_finished). Mismo
    ContactosAddDialog, AddContactoThread, contactos_service.
    generar_nuevo_id_contacto y ExcelWriter.add_new_row que ya usa
    ContactosModule (contactos.py) -- acá solo se cubre lo específico de
    este nuevo punto de entrada, sin duplicar la cobertura ya existente de
    alta/formateo/generación de ID en test_contactos.py/
    test_contactos_service.py. No usa la AddContactoThread real (evita
    tocar contactos.xlsx real durante el test): se reemplaza por
    _FakeAddContactoThreadExitoso o se parchea directamente. Tampoco abre
    el diálogo real: se parchea ContactosAddDialog. Mismo patrón de
    fixture de cliente que TestBuscadorGlobalTresPestanas (datos mock de
    generar_mock_data.py: 'EMPRESA PRUEBA S.A.', CDB '10001')."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."

    def setUp(self):
        self.module.search_input.setText("")
        self.module.filter_table()
        self.module._switch_left_view(0)  # "Cliente"
        self.module._on_cliente_card_clicked(0)
        QApplication.processEvents()
        self._cdb_esperado = self.module._selected_cdb
        self.assertIsNotNone(self._cdb_esperado, "Precondición del test: debe haber un cliente seleccionado.")
        cliente_row = self.module._buscar_cliente_por_clave(self.module._selected_cliente_key)
        self.assertIsNotNone(cliente_row, "Precondición del test: el CDB seleccionado debe resolver a un cliente.")
        self._razon_social_esperada = str(cliente_row['Razón Social'])
        self._df_contactos_original = self.dm.df_contactos.copy()

    def tearDown(self):
        self.dm.df_contactos = self._df_contactos_original
        # _handle_agregar_contacto deshabilita el botón mientras guarda y lo
        # reactiva en _on_agregar_contacto_finished: si algún test deja el
        # guardado "en vuelo" (thread que nunca emite), evita que quede
        # deshabilitado para el resto de los tests de esta clase (comparten
        # self.module vía setUpClass).
        self.module.btn_agregar_contacto.setEnabled(True)

    def _datos_contacto_nuevo(self, **overrides):
        datos = {
            'CDB': str(self._cdb_esperado), 'Flota': self._razon_social_esperada,
            'Nombre': 'Pedro', 'Apellidos': 'Prueba',
            'Correo electrónico': 'pedro@empresa.example', 'Número móvil': '+56911111111',
            'Rol': 'Administrador de flota',
        }
        datos.update(overrides)
        return datos

    def test_01_boton_agregar_contacto_esta_conectado_al_flujo(self):
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.module.btn_agregar_contacto.click()

        mock_dialog.assert_called_once()

    def test_02_abre_el_dialogo_con_cdb_y_razon_social_del_cliente_seleccionado(self):
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.module.btn_agregar_contacto.click()

        _, kwargs = mock_dialog.call_args
        # Desde el 08-10-2026 se precarga el CDB flota del cliente (None si no tiene)
        flotas = self.module._selected_cdbs_flota
        self.assertEqual(kwargs.get('cdb_prefill'), flotas[0] if flotas else None)
        self.assertEqual(kwargs.get('flota_prefill'), self._razon_social_esperada)

    def test_03_cancelar_no_modifica_contactos(self):
        df_antes = self.dm.df_contactos.copy()
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.module.btn_agregar_contacto.click()

        pd.testing.assert_frame_equal(
            self.dm.df_contactos.reset_index(drop=True), df_antes.reset_index(drop=True)
        )

    def test_04_guardar_usa_addcontactothread_con_el_writer_y_el_id_generado(self):
        # _FakeAddContactoThreadExitoso (no un MagicMock crudo): su start()
        # sí emite finished_signal, lo que deja _on_agregar_contacto_finished
        # correr de verdad y re-habilitar el botón -- un MagicMock sin
        # emisión real dejaría el botón deshabilitado para el resto de los
        # tests de esta clase (comparten self.module vía setUpClass).
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.general.AddContactoThread', _FakeAddContactoThreadExitoso):
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = self._datos_contacto_nuevo()
            self.module.btn_agregar_contacto.click()

        thread_usado = self.module._add_contacto_thread
        self.assertIs(thread_usado.writer, self.module.writer)
        self.assertEqual(thread_usado.new_data['CDB'], str(self._cdb_esperado))
        self.assertIn('ID', thread_usado.new_data)

    def test_05_permite_contacto_duplicado_en_otra_empresa_sin_bloquear(self):
        """Decisión explícita (Fase 4): un mismo correo puede repetirse en
        más de una empresa -- no debe existir ninguna validación que lo
        impida ni que cancele el guardado."""
        self.dm.df_contactos = pd.DataFrame({
            'ID': [1], 'CDB': ['OTRA_EMPRESA_CDB'], 'Flota': ['Otra Empresa'],
            'Nombre': ['Pedro'], 'Apellidos': ['Prueba'],
            'Correo electrónico': ['pedro@empresa.example'], 'Número móvil': ['+56911111111'],
        })
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.general.AddContactoThread', _FakeAddContactoThreadExitoso):
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = self._datos_contacto_nuevo()
            self.module.btn_agregar_contacto.click()

        thread_usado = self.module._add_contacto_thread
        self.assertEqual(thread_usado.new_data['Correo electrónico'], 'pedro@empresa.example')

    def test_06_guardar_correctamente_recarga_contactos_desde_disco(self):
        """_on_agregar_contacto_finished no repuebla la pestaña a mano: solo
        dispara data_manager.load_contactos_async(), que al terminar emite
        contactos_ready -- ya conectado a _on_contactos_ready, que repuebla
        Contactos del cliente activo (mecanismo preexistente, no se
        duplica ni se vuelve a probar acá)."""
        with patch('src.ui.general.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.general.AddContactoThread', _FakeAddContactoThreadExitoso), \
             patch.object(self.module.data_manager, 'load_contactos_async') as mock_reload:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = self._datos_contacto_nuevo()
            self.module.btn_agregar_contacto.click()

        mock_reload.assert_called_once()

    def test_07_error_durante_el_guardado_no_dispara_recarga(self):
        class _FakeAddContactoThreadError(_FakeAddContactoThreadExitoso):
            def start(self):
                self.finished_signal.emit(False, self.new_data)

        with patch('src.ui.general.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.general.AddContactoThread', _FakeAddContactoThreadError), \
             patch.object(self.module.data_manager, 'load_contactos_async') as mock_reload, \
             patch('src.ui.general.QMessageBox') as mock_msgbox:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = self._datos_contacto_nuevo()
            self.module.btn_agregar_contacto.click()

        mock_msgbox.warning.assert_called_once()
        mock_reload.assert_not_called()


class TestDetalleClienteSinHistorial(unittest.TestCase):
    """A pedido explícito (15-09-2026): la pestaña 'Historial' se quita del
    detalle de Cliente/Flota (caja derecha, right_stack índice 1,
    _build_cliente_detalle_view) -- Cliente y Flota comparten esta misma
    vista (ver _show_cliente_detalle). El historial por VIN de Unidades
    (right_stack índice 4, btn_vin_historial) NO se toca."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."
        cls.module._on_cliente_card_clicked(0)  # fuerza la construcción perezosa del detalle
        QApplication.processEvents()

    def test_no_existe_boton_historial_en_el_detalle_de_cliente(self):
        self.assertFalse(hasattr(self.module, 'btn_detalle_historial'))
        textos_botones = [btn.text() for btn in self.module._detalle_nav_buttons]
        self.assertNotIn('Historial', textos_botones)

    def test_detalle_de_cliente_tiene_las_5_pestanas(self):
        textos_botones = [btn.text().split(' (')[0] for btn in self.module._detalle_nav_buttons]
        self.assertEqual(textos_botones, ['Resumen', 'Unidades', 'Flotas VC', 'Contactos', 'Razones'])

    def test_stack_de_detalle_tiene_5_paginas(self):
        self.assertEqual(self.module.detalle_stack.count(), 5)

    def test_historial_de_vin_en_unidades_sigue_existiendo(self):
        """El historial por VIN (Unidades, caja derecha -> contexto de VIN)
        es una pantalla distinta y no debe verse afectado."""
        self.assertTrue(hasattr(self.module, 'btn_vin_historial'))
        self.assertEqual(self.module.btn_vin_historial.text(), 'Historial')


class TestContratosAnterioresEnUnidades(unittest.TestCase):
    """Fase 2 (contratos por ID, 13-10-2026): Unidades -> VIN -> subpestaña
    "Contratos anteriores" -> un contrato -> su ficha en la pestaña Ficha."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        df = cls.dm.df_master.copy()
        cls._df_original = cls.dm.df_master
        if 'ID' not in df.columns:
            df.insert(0, 'ID', [str(i + 1) for i in range(len(df))])
        cls.vin = df.iloc[0][COL_VIN]
        nuevo = df.iloc[[0]].copy()
        nuevo['ID'] = str(int(pd.to_numeric(df['ID']).max()) + 1)
        df.loc[df.index[0], 'ESTADO COMERCIAL'] = 'BAJA'
        nuevo['ESTADO COMERCIAL'] = 'ACTIVACION PENDIENTE'
        cls.id_antiguo, cls.id_nuevo = df.iloc[0]['ID'], nuevo.iloc[0]['ID']
        cls.dm.df_master = pd.concat([df, nuevo], ignore_index=True)

        cls.module = GeneralModule()
        assert _esperar_prep_thread(cls.module), "GeneralDataPrepThread no termino dentro del timeout."
        cls.module._vin_seleccionado = cls.vin
        cls.module._show_vin_detalle(cls.vin)
        QApplication.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.dm.df_master = cls._df_original

    def _ids_en_ficha(self):
        return [l.text() for l in self.module._ficha_vin_layouts['Situación de la unidad'].itemAt(0).widget().findChildren(QLabel)]

    def test_la_unidad_aparece_una_vez_y_con_el_contrato_actual(self):
        self.assertEqual(len(self.module.df_unidades_base), len(self.dm.df_master) - 1)
        self.assertIn(self.id_nuevo, self._ids_en_ficha())

    def test_la_subpestana_lista_solo_los_contratos_anteriores(self):
        from src.ui.general import _ContratoAnteriorCard
        self.assertEqual(self.module.btn_vin_contratos.text(), 'Contratos anteriores (1)')
        tarjetas = self.module.contratos_anteriores_layout.parent().findChildren(_ContratoAnteriorCard)
        self.assertEqual(len(tarjetas), 1)
        self.assertIn(f"N° Contrato {self.id_antiguo}", [l.text() for l in tarjetas[0].findChildren(QLabel)])

    def test_elegir_un_contrato_anterior_muestra_su_ficha_y_volver_restaura_el_actual(self):
        self.module._on_contrato_anterior_clicked(0)
        self.assertEqual(self.module.vin_detalle_stack.currentIndex(), 0)
        self.assertFalse(self.module._ficha_aviso_anterior.isHidden())
        self.assertIn(self.id_antiguo, self._ids_en_ficha())

        self.module._switch_vin_detalle_view(0)
        self.assertTrue(self.module._ficha_aviso_anterior.isHidden())
        self.assertIn(self.id_nuevo, self._ids_en_ficha())


class TestGeneralDataPrepThread(unittest.TestCase):
    """Fase 4 de la auditoria de rendimiento de UI (21-09-2026):
    GeneralModule.load_data() ejecutaba procesar_df_comercial() + los 3
    _build_*_df() + las listas de filtro de forma sincrona en el hilo de UI
    (~95 ms medidos con datos sinteticos a escala real -- ver conversacion
    de la auditoria). Ahora corren dentro de GeneralDataPrepThread, un
    QThread real que nunca toca self ni ningun widget. Estos tests
    construyen el hilo directamente (sin GeneralModule completo) y esperan
    su señal -- mismo patron que TestPowerBiDirectorEmpresaLoaderThread para
    el otro worker de este archivo."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                QApplication.processEvents()
                return True
            time.sleep(interval_ms / 1000.0)
        return False

    @staticmethod
    def _snapshot_de_prueba():
        return pd.DataFrame({
            COL_VIN: ['VIN001', 'VIN002', 'VIN003'],
            COL_CHASIS: ['CH001', 'CH002', 'CH003'],
            COL_RAZON_SOCIAL: ['EMPRESA A', 'EMPRESA A', 'EMPRESA B'],
            COL_RUT: ['1-1', '1-1', '2-2'],
            COL_INDUSTRIA: ['Minería', 'Minería', 'Transporte'],
            COL_CDB: ['1001.0', '1001.0', '1002'],
            COL_FLOTA_VC: ['FLOTA X', 'FLOTA Y', 'FLOTA Z'],
            COL_ESTADO_ACTIVACION: ['Conectado', 'Desconectado', 'Activando'],
            COL_ETAPA_GESTION: ['CLIENTE', 'CLIENTE', 'COMERCIAL'],
        })

    def test_emite_los_dataframes_esperados(self):
        resultado = {}
        thread = GeneralDataPrepThread(self._snapshot_de_prueba())
        thread.data_prepared_signal.connect(lambda r: resultado.update(r=r))
        thread.start()

        listo = self._wait_until(lambda: 'r' in resultado)
        self.assertTrue(listo, "Fallo: GeneralDataPrepThread no termino dentro del timeout.")

        df_comercial, df_clientes, df_unidades = resultado['r']

        self.assertEqual(len(df_comercial), 3)
        self.assertIn('N°', df_comercial.columns)  # procesar_df_comercial agrega esta columna
        self.assertEqual(df_comercial.iloc[0]['CDB'], '1001')  # se le quita el sufijo '.0'

        self.assertEqual(len(df_clientes), 2)  # EMPRESA A + EMPRESA B agrupadas
        self.assertEqual(len(df_unidades), 3)

    def test_un_vin_con_dos_contratos_cuenta_una_vez_con_el_contrato_actual(self):
        snapshot = self._snapshot_de_prueba()
        snapshot['ID'] = ['1', '2', '3']
        snapshot.loc[2, COL_VIN] = 'VIN001'
        resultado = {}
        thread = GeneralDataPrepThread(snapshot)
        thread.data_prepared_signal.connect(lambda r: resultado.update(r=r))
        thread.start()
        self.assertTrue(self._wait_until(lambda: 'r' in resultado))

        df_comercial, df_clientes, df_unidades = resultado['r']
        self.assertEqual(sorted(df_comercial['ID'].tolist()), ['2', '3'])
        self.assertEqual(len(df_unidades), 2)
        self.assertEqual(len(df_clientes), 2)

    def test_snapshot_vacio_no_revienta(self):
        resultado = {}
        thread = GeneralDataPrepThread(pd.DataFrame())
        thread.data_prepared_signal.connect(lambda r: resultado.update(r=r))
        thread.start()

        listo = self._wait_until(lambda: 'r' in resultado)
        self.assertTrue(listo, "Fallo: GeneralDataPrepThread no termino dentro del timeout.")

        df_comercial, df_clientes, df_unidades = resultado['r']
        self.assertTrue(df_comercial.empty)
        self.assertTrue(df_clientes.empty)
        self.assertTrue(df_unidades.empty)


class TestGeneralDataPrepThreadEquivaleAlPipelineSincronoAnterior(unittest.TestCase):
    """Compara el resultado de GeneralDataPrepThread contra llamar
    directamente comercial_services.procesar_df_comercial() +
    GeneralModule._build_clientes_df/_build_unidades_df()
    sobre el mismo snapshot -- exactamente lo que hacia
    GeneralModule.load_data() antes de esta fase, de forma sincrona.
    Verifica que mover el calculo a un QThread no cambio ningun resultado."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                QApplication.processEvents()
                return True
            time.sleep(interval_ms / 1000.0)
        return False

    def test_dataframes_emitidos_son_identicos_al_calculo_directo(self):
        snapshot = pd.DataFrame({
            COL_VIN: [f'VIN{i:03d}' for i in range(20)],
            COL_CHASIS: [f'CH{i:03d}' for i in range(20)],
            COL_RAZON_SOCIAL: [f'EMPRESA {i % 4}' for i in range(20)],
            COL_RUT: [f'{i % 4}-{i % 4}' for i in range(20)],
            COL_INDUSTRIA: (['Minería', 'Transporte', 'Forestal', 'Construcción'] * 5),
            COL_CDB: [f'{1000 + (i % 4)}.0' for i in range(20)],
            COL_FLOTA_VC: [f'FLOTA {i % 3}' for i in range(20)],
            COL_ESTADO_ACTIVACION: (['Conectado', 'Desconectado', 'Activando', 'Sin flota'] * 5),
            COL_ETAPA_GESTION: (['CLIENTE', 'COMERCIAL', 'OPERACIONES', 'CLIENTE'] * 5),
            'DURACIÓN (MESES)': (['12', '24', 'MENSUAL', '-'] * 5),
            'TÉRMINO CONTRATO': (['MENSUAL', '-', '15-03-2027', '20-01-2026'] * 5),
        })

        # Calculo directo: equivalente exacto de lo que hacia load_data()
        # de forma sincrona antes de esta fase.
        df_comercial_directo = comercial_services.procesar_df_comercial(snapshot.copy())
        df_clientes_directo = GeneralModule._build_clientes_df(df_comercial_directo)
        df_unidades_directo = GeneralModule._build_unidades_df(df_comercial_directo)

        # Calculo via el worker, sobre una copia independiente del mismo snapshot.
        resultado = {}
        thread = GeneralDataPrepThread(snapshot.copy())
        thread.data_prepared_signal.connect(lambda r: resultado.update(r=r))
        thread.start()
        listo = self._wait_until(lambda: 'r' in resultado)
        self.assertTrue(listo, "Fallo: GeneralDataPrepThread no termino dentro del timeout.")
        df_comercial_worker, df_clientes_worker, df_unidades_worker = resultado['r']

        pd.testing.assert_frame_equal(
            df_comercial_worker.reset_index(drop=True), df_comercial_directo.reset_index(drop=True))
        pd.testing.assert_frame_equal(
            df_clientes_worker.reset_index(drop=True), df_clientes_directo.reset_index(drop=True))
        pd.testing.assert_frame_equal(
            df_unidades_worker.reset_index(drop=True), df_unidades_directo.reset_index(drop=True))


class _FakeSignalGeneralPrep:
    """Reemplazo minimo de pyqtSignal para simular GeneralDataPrepThread sin
    lanzar un QThread real (mismo rol que _FakeSaveThreadSignalGeneral; no
    se reutiliza esa para no acoplar esta clase de test a la de Editar
    Unidad)."""

    def __init__(self):
        self._slot = None

    def connect(self, slot):
        self._slot = slot

    def emit(self, *args):
        if self._slot is not None:
            self._slot(*args)


class _FakeGeneralDataPrepThread:
    """Reemplaza GeneralDataPrepThread en los tests de reentrancia: start()
    NO calcula ni emite nada de inmediato (a diferencia de un QThread real,
    que corre en paralelo) -- el propio test decide cuando "termina" llamando
    terminar_ahora(resultado), para poder verificar de forma deterministica
    el guard de reentrancia sin depender del timing real de un QThread."""

    instancias = []

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.data_prepared_signal = _FakeSignalGeneralPrep()
        _FakeGeneralDataPrepThread.instancias.append(self)

    def start(self):
        pass  # deliberadamente no hace nada: "sigue corriendo" hasta terminar_ahora()

    def terminar_ahora(self, resultado):
        self.data_prepared_signal.emit(resultado)


class TestLoadDataGuardDeReentrancia(unittest.TestCase):
    """Fase 4 de la auditoria de rendimiento (21-09-2026): guard de
    reentrancia de GeneralModule.load_data()/GeneralDataPrepThread. Si
    load_data() se llama mientras un worker ya esta corriendo
    (_prep_en_curso), no debe lanzarse un segundo GeneralDataPrepThread --
    debe marcar _prep_pendiente y, al terminar el worker actual, reprocesar
    automaticamente con el snapshot mas reciente de DataManager. Usa un
    reemplazo de GeneralDataPrepThread controlado a mano (en vez de un
    QThread real) para que la secuencia sea 100% deterministica."""

    def _make_module(self, snapshots):
        modulo = GeneralModule.__new__(GeneralModule)  # no ejecuta __init__ (evita construir toda la UI)
        modulo.data_manager = MagicMock()
        modulo.data_manager.get_comercial_df.side_effect = snapshots
        modulo._prep_thread = None
        modulo._prep_en_curso = False
        modulo._prep_pendiente = False
        modulo._data_dirty = False
        # _on_prep_finished necesita poder llamar a esto sin construir la UI real:
        modulo._filtros_unidades = {}
        modulo.filter_clientes = MagicMock()
        modulo.filter_unidades = MagicMock()
        return modulo

    @staticmethod
    def _resultado_falso(marca):
        df = pd.DataFrame({'marca': [marca]})
        return (df, df, df)

    @patch('src.ui.general.GeneralDataPrepThread', _FakeGeneralDataPrepThread)
    def test_no_lanza_un_segundo_worker_mientras_el_actual_sigue_corriendo(self):
        _FakeGeneralDataPrepThread.instancias = []
        modulo = self._make_module([pd.DataFrame({'x': [1]}), pd.DataFrame({'x': [2]})])

        modulo.load_data()
        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 1, "Debe lanzar el primer worker.")
        self.assertTrue(modulo._prep_en_curso)
        self.assertFalse(modulo._prep_pendiente)

        modulo.load_data()  # el primero "sigue corriendo" (no se llamo terminar_ahora)
        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 1,
                          "Fallo: no debe lanzar un segundo worker mientras el primero sigue corriendo.")
        self.assertTrue(modulo._prep_pendiente, "Fallo: debe marcar la actualizacion como pendiente.")

    @patch('src.ui.general.GeneralDataPrepThread', _FakeGeneralDataPrepThread)
    def test_al_terminar_con_pendiente_reprocesa_el_snapshot_mas_reciente(self):
        _FakeGeneralDataPrepThread.instancias = []
        modulo = self._make_module([pd.DataFrame({'x': [1]}), pd.DataFrame({'x': [2]})])

        modulo.load_data()
        modulo.load_data()  # queda pendiente
        primer_worker = _FakeGeneralDataPrepThread.instancias[0]

        primer_worker.terminar_ahora(self._resultado_falso('primero'))

        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 2,
                          "Fallo: al terminar con una actualizacion pendiente, debe reprocesar automaticamente.")
        self.assertFalse(modulo._prep_pendiente, "Fallo: el flag pendiente debe limpiarse al reprocesar.")

        # El segundo worker debe haberse construido con el SEGUNDO snapshot
        # (get_comercial_df.side_effect), no repetir el primero -- prueba de
        # que "vuelve a procesar el snapshot mas reciente".
        segundo_worker = _FakeGeneralDataPrepThread.instancias[1]
        pd.testing.assert_frame_equal(segundo_worker.snapshot, pd.DataFrame({'x': [2]}))

    @patch('src.ui.general.GeneralDataPrepThread', _FakeGeneralDataPrepThread)
    def test_sin_pendiente_terminar_no_relanza_un_tercer_worker(self):
        _FakeGeneralDataPrepThread.instancias = []
        modulo = self._make_module([pd.DataFrame({'x': [1]})])

        modulo.load_data()
        primer_worker = _FakeGeneralDataPrepThread.instancias[0]
        primer_worker.terminar_ahora(self._resultado_falso('unico'))

        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 1,
                          "Fallo: sin actualizacion pendiente, no debe lanzarse un worker adicional.")
        self.assertFalse(modulo._prep_en_curso)

    @patch('src.ui.general.GeneralDataPrepThread', _FakeGeneralDataPrepThread)
    def test_terminar_aplica_los_dataframes_recibidos(self):
        _FakeGeneralDataPrepThread.instancias = []
        modulo = self._make_module([pd.DataFrame({'x': [1]})])

        modulo.load_data()
        primer_worker = _FakeGeneralDataPrepThread.instancias[0]
        primer_worker.terminar_ahora(self._resultado_falso('resultado_x'))

        self.assertEqual(modulo.df_comercial_raw.iloc[0]['marca'], 'resultado_x')
        self.assertEqual(modulo.df_clientes_base.iloc[0]['marca'], 'resultado_x')
        self.assertEqual(modulo.df_unidades_base.iloc[0]['marca'], 'resultado_x')
        modulo.filter_clientes.assert_called_once()
        modulo.filter_unidades.assert_called_once()

    @patch('src.ui.general.GeneralDataPrepThread', _FakeGeneralDataPrepThread)
    def test_nunca_hay_mas_de_un_worker_corriendo_a_la_vez(self):
        """Verifica 'no hay workers superpuestos' de punta a punta: varias
        llamadas rapidas a load_data() (simulando varios data_ready seguidos
        mientras el primer worker sigue en vuelo) nunca deben acumular mas
        de un _FakeGeneralDataPrepThread sin terminar, y las llamadas de mas
        colapsan en una sola actualizacion pendiente (no se encola una por
        cada llamada de mas)."""
        _FakeGeneralDataPrepThread.instancias = []
        modulo = self._make_module([pd.DataFrame({'x': [0]}), pd.DataFrame({'x': [1]})])

        for _ in range(4):
            modulo.load_data()  # ninguno termina todavia: el primero sigue "corriendo"

        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 1,
                          "Fallo: nunca debe haber mas de un worker en vuelo a la vez.")

        _FakeGeneralDataPrepThread.instancias[0].terminar_ahora(self._resultado_falso('r0'))
        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 2,
                          "Fallo: las llamadas de mas mientras corria deben colapsar en UNA sola actualizacion pendiente.")

        _FakeGeneralDataPrepThread.instancias[1].terminar_ahora(self._resultado_falso('r1'))
        self.assertEqual(len(_FakeGeneralDataPrepThread.instancias), 2,
                          "Fallo: sin una nueva actualizacion pendiente, no debe lanzarse un tercer worker.")


class TestRenderDiferidoPestanasOcultasFase5(unittest.TestCase):
    """Fase 5 de la auditoria de rendimiento (21-09-2026): filter_table()/
    _on_prep_finished() actualizan los 2 DataFrames de la caja izquierda
    (Cliente/Unidades) ante cada busqueda/orden/refresh, pero solo UNA
    sub-pestana es visible a la vez (self.left_stack). Reconstruir las
    tarjetas Qt de la otra -- que nadie esta viendo -- era trabajo invisible
    por busqueda. Ahora _render_clientes_cards/_render_unidades_cards solo
    pintan si su pestana esta visible; si no, marcan
    _clientes_pendiente_render/_unidades_pendiente_render y
    _switch_left_view resuelve el pendiente (pinta + sincroniza) recien al
    entrar (ver _renderizar_pestana_si_pendiente). Requiere una instancia
    real (mismos datos mock que TestBuscadorGlobalTresPestanas)."""

    ASYNC_TIMEOUT_MS = 20000

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

        cls.module = GeneralModule()
        listo = _esperar_prep_thread(cls.module, timeout_ms=cls.ASYNC_TIMEOUT_MS)
        assert listo, "GeneralDataPrepThread no termino dentro del timeout durante setUpClass."

    def setUp(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()

    def tearDown(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()

    def test_busqueda_en_clientes_renderiza_clientes_y_difiere_unidades(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("EMPRESA")
        self.module.filter_table()
        QApplication.processEvents()

        self.assertFalse(self.module._clientes_pendiente_render,
                          "Cliente es la pestaña visible: debe renderizarse de inmediato, no quedar pendiente.")
        self.assertTrue(self.module._unidades_pendiente_render, "Unidades no es visible: debe quedar pendiente.")

    def test_unidades_no_construye_tarjetas_mientras_esta_oculta(self):
        self.module._switch_left_view(0)
        unidades_widgets_antes = self.module.unidades_layout.count()

        self.module.search_input.setText("EMPRESA")
        self.module.filter_table()
        QApplication.processEvents()

        # Si se hubieran reconstruido, el pintado habria vaciado el layout
        # (takeAt+deleteLater) y vuelto a poblarlo -- con el render diferido,
        # el layout de la pestaña oculta no se toca en absoluto.
        self.assertEqual(self.module.unidades_layout.count(), unidades_widgets_antes,
                          "Fallo: no debería tocarse el layout de Unidades mientras está oculta.")

    def test_cambiar_a_unidades_pendiente_la_renderiza_y_limpia_la_bandera(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("EMPRESA")
        self.module.filter_table()
        QApplication.processEvents()
        self.assertTrue(self.module._unidades_pendiente_render)

        self.module._switch_left_view(1)
        QApplication.processEvents()

        self.assertFalse(self.module._unidades_pendiente_render, "Fallo: debe limpiarse al renderizar.")
        self.assertGreater(self.module.unidades_layout.count(), 0, "Debe haber tarjetas de Unidades pintadas.")
        self.assertEqual(len(self.module._unidad_cards), len(self.module._df_unidades_visible),
                          "El número de tarjetas debe corresponder al DataFrame ya filtrado.")

    def test_volver_a_una_pestana_sin_cambios_no_reconstruye(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("EMPRESA")
        self.module.filter_table()
        QApplication.processEvents()

        self.module._switch_left_view(1)  # entra a Unidades -> se renderiza
        QApplication.processEvents()
        cards_primera_vez = dict(self.module._unidad_cards)
        self.assertTrue(cards_primera_vez, "Precondición del test: debe haber tarjetas de Unidades.")

        self.module._switch_left_view(0)
        self.module._switch_left_view(1)  # vuelve a Unidades sin ningún cambio de datos/búsqueda
        QApplication.processEvents()

        self.assertEqual(set(self.module._unidad_cards.keys()), set(cards_primera_vez.keys()))
        for clave, card in cards_primera_vez.items():
            self.assertIs(self.module._unidad_cards[clave], card,
                          "Fallo: no debe reconstruir tarjetas si no hay render pendiente.")

    def test_actualizacion_de_datos_en_pestana_visible_renderiza_y_marca_la_oculta(self):
        self.module._switch_left_view(1)  # Unidades visible
        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()

        self.assertFalse(self.module._unidades_pendiente_render, "Unidades es la visible: debe renderizarse ya.")
        self.assertGreater(self.module.unidades_layout.count(), 0)
        self.assertTrue(self.module._clientes_pendiente_render)

    def test_dataframes_visibles_se_actualizan_aunque_la_pestana_este_oculta(self):
        self.module._switch_left_view(0)
        self.module.search_input.setText("EMPRESA PRUEBA")
        self.module.filter_table()
        QApplication.processEvents()

        # Unidades queda oculta/pendiente, pero su DataFrame lógico (usado
        # por selección/paginación) debe reflejar la búsqueda igual que
        # antes -- solo se difiere la construcción de widgets.
        self.assertTrue(self.module._unidades_pendiente_render)
        self.assertFalse(self.module._df_unidades_visible.empty)
        self.assertTrue((self.module._df_unidades_visible['Razón Social'] == 'EMPRESA PRUEBA S.A.').all())

    def test_sincronizacion_de_vin_se_ejecuta_al_entrar_a_unidades_pendiente(self):
        self.module._switch_left_view(1)
        self.module.search_input.setText("")
        self.module.filter_table()
        QApplication.processEvents()
        self.module._on_unidad_card_clicked(0)
        QApplication.processEvents()
        self.assertIsNotNone(self.module._vin_seleccionado)
        self.assertEqual(self.module.right_stack.currentIndex(), 4)

        self.module._switch_left_view(0)  # Unidades queda oculta
        self.module.search_input.setText("EMPRESA")  # dispara filter_table -> Unidades queda pendiente
        self.module.filter_table()
        QApplication.processEvents()
        self.assertTrue(self.module._unidades_pendiente_render)

        self.module._switch_left_view(1)  # vuelve a Unidades: debe resolver el pendiente + sincronizar
        QApplication.processEvents()

        self.assertFalse(self.module._unidades_pendiente_render)
        self.assertEqual(self.module.right_stack.currentIndex(), 4,
                          "Fallo: la sincronización de VIN debe ejecutarse al resolver el render pendiente.")


if __name__ == '__main__':
    unittest.main()
