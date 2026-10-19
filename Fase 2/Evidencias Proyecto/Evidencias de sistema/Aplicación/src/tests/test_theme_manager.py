import unittest

from PyQt6.QtGui import QIcon, QPixmap

from src.theme.theme_manager import ThemeManager


class TestThemeManagerIconCache(unittest.TestCase):
    """Fase 2 de la auditoria de rendimiento de UI (21-09-2026):
    General/Comercial/Provisiones llamaban qta.icon(nombre, color=...) (y
    luego .pixmap(QSize(...))) por cada tarjeta/fila construida, cientos de
    veces por refresh, re-renderizando el mismo glifo una y otra vez.
    ThemeManager.icon()/icon_pixmap() cachean por (nombre, color[, tamano])
    y devuelven la MISMA instancia ya renderizada en pedidos repetidos, en
    vez de volver a renderizar. No debe cambiar ningun resultado visual:
    mismo icono, mismo color, mismo tamano."""

    def setUp(self):
        # Cada test debe ver la cache "limpia" para poder afirmar que la
        # primera llamada de ESTE test es la que efectivamente renderiza.
        ThemeManager._icon_cache.clear()
        ThemeManager._pixmap_cache.clear()

    def test_icon_devuelve_un_qicon_valido(self):
        icono = ThemeManager.icon('fa5s.building', color='#000000')
        self.assertIsInstance(icono, QIcon)
        self.assertFalse(icono.isNull())

    def test_icon_mismo_nombre_y_color_devuelve_la_misma_instancia(self):
        primero = ThemeManager.icon('fa5s.building', color='#000000')
        segundo = ThemeManager.icon('fa5s.building', color='#000000')
        self.assertIs(primero, segundo, "Fallo: debe reutilizar el QIcon cacheado, no volver a renderizarlo.")

    def test_icon_distinto_color_no_comparte_cache(self):
        rojo = ThemeManager.icon('fa5s.building', color='#FF0000')
        azul = ThemeManager.icon('fa5s.building', color='#0000FF')
        self.assertIsNot(rojo, azul)

    def test_icon_distinto_nombre_no_comparte_cache(self):
        a = ThemeManager.icon('fa5s.building', color='#000000')
        b = ThemeManager.icon('fa5s.truck', color='#000000')
        self.assertIsNot(a, b)

    def test_icon_pixmap_devuelve_un_qpixmap_del_tamano_pedido(self):
        pixmap = ThemeManager.icon_pixmap('fa5s.truck', color='#000000', size=16)
        self.assertIsInstance(pixmap, QPixmap)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 16)
        self.assertEqual(pixmap.height(), 16)

    def test_icon_pixmap_mismos_parametros_devuelve_la_misma_instancia(self):
        primero = ThemeManager.icon_pixmap('fa5s.truck', color='#000000', size=16)
        segundo = ThemeManager.icon_pixmap('fa5s.truck', color='#000000', size=16)
        self.assertIs(primero, segundo, "Fallo: debe reutilizar el QPixmap cacheado, no volver a renderizarlo.")

    def test_icon_pixmap_distinto_tamano_no_comparte_cache(self):
        chico = ThemeManager.icon_pixmap('fa5s.truck', color='#000000', size=11)
        grande = ThemeManager.icon_pixmap('fa5s.truck', color='#000000', size=34)
        self.assertIsNot(chico, grande)
        self.assertEqual(chico.width(), 11)
        self.assertEqual(grande.width(), 34)

    def test_icon_pixmap_usa_la_cache_de_icon_por_debajo(self):
        """icon_pixmap() no debe crear un QIcon nuevo si icon() con el mismo
        (nombre, color) ya fue pedido antes -- ambas cachés comparten la
        misma fuente de icono cacheado."""
        icono = ThemeManager.icon('fa5s.truck', color='#123456')
        self.assertEqual(len(ThemeManager._icon_cache), 1)

        ThemeManager.icon_pixmap('fa5s.truck', color='#123456', size=20)
        self.assertEqual(len(ThemeManager._icon_cache), 1, "Fallo: icon_pixmap() no reutilizo el QIcon ya cacheado por icon().")


if __name__ == '__main__':
    unittest.main(verbosity=2)
