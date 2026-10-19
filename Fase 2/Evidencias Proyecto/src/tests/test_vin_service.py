import unittest

from src.services.vin_service import obtener_modelo_desde_vin


class TestObtenerModeloDesdeVin(unittest.TestCase):
    """src/services/vin_service.py: deduccion del MODELO (unicamente) a
    partir de la posicion 4 del VIN (indice 3) y, para la variante
    electrica, las posiciones 5-7 (indices 4:7)."""

    def test_posicion_r_es_fh(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2RB00CXRA900064"), "FH")

    def test_posicion_x_es_fm(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2XB00C0RA900056"), "FM")

    def test_posicion_k_es_vm(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2KB00C0RA900056"), "VM")

    def test_posicion_p_es_vm(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2PB00C0RA900056"), "VM")

    def test_posicion_t_es_fl(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2TB00C0RA900056"), "FL")

    def test_posicion_v_es_fe(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2VB00C0RA900056"), "FE")

    def test_posicion_a_es_fh_generacion_anterior(self):
        # A representa FH de generacion anterior, pero MODELO no distingue
        # generacion: el valor oficial resultante sigue siendo "FH".
        self.assertEqual(obtener_modelo_desde_vin("YV2AB00C0RA900056"), "FH")

    def test_posicion_j_es_fm_generacion_anterior(self):
        # J representa FM de generacion anterior, pero MODELO no distingue
        # generacion: el valor oficial resultante sigue siendo "FM".
        self.assertEqual(obtener_modelo_desde_vin("YV2JB00C0RA900056"), "FM")

    def test_r_mas_b40_es_fhe(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2RB40CXRA900064"), "FHE")
        self.assertEqual(obtener_modelo_desde_vin("YV2RB40DXRA900072"), "FHE")

    def test_x_mas_b40_es_fme(self):
        self.assertEqual(obtener_modelo_desde_vin("YV2XB40C0RA900056"), "FME")

    def test_vin_en_minusculas_da_mismo_resultado(self):
        self.assertEqual(obtener_modelo_desde_vin("yv2rb40cxra334990"), "FHE")
        self.assertEqual(obtener_modelo_desde_vin("yv2xb00c0ra339736"), "FM")

    def test_codigo_desconocido_no_inventa_modelo(self):
        self.assertIsNone(obtener_modelo_desde_vin("YV2ZB00C0RA900056"))

    def test_vin_vacio_no_genera_modelo(self):
        self.assertIsNone(obtener_modelo_desde_vin(""))

    def test_vin_incompleto_no_genera_modelo(self):
        self.assertIsNone(obtener_modelo_desde_vin("YV2"))

    def test_posicion_4_valida_pero_sin_posiciones_5_a_7_no_es_electrico(self):
        # VIN con largo justo hasta la posicion 4: se reconoce el modelo
        # base pero no puede evaluarse B40 (no hay posiciones 5-7).
        self.assertEqual(obtener_modelo_desde_vin("YV2R"), "FH")


if __name__ == '__main__':
    unittest.main()
