"""Accesos directos entre pantallas, para avisos que mandan al usuario a otra parte de la aplicación."""
from PyQt6.QtWidgets import QApplication


def abrir_importacion_power_bi():
    """Abre Comercial, Gestión de unidades, con la guía de importación desde Power BI; False si no se pudo."""
    ventana = next((w for w in QApplication.topLevelWidgets() if hasattr(w, "_on_menu_clicked")), None)
    if ventana is None:
        return False
    try:
        ventana._on_menu_clicked("Comercial")
        comercial = ventana.loaded_modules.get("Comercial")
        comercial._on_crear_nueva_unidad_clicked()
        comercial._asegurar_unidad_nueva_form()
        comercial._abrir_importar_powerbi()
    except Exception:
        return False
    return True
