# Paleta de colores oficial del sistema
VOLVO_BLUE = "#003057"
PRIMARY = "#2563EB"       # Azul moderno (Botones principales)
SECONDARY = "#60A5FA"     # Azul claro
SUCCESS = "#10B981"       # Verde (Vigente, Conectado)
WARNING = "#F59E0B"       # Naranja (Por vencer, Activando)
DANGER = "#EF4444"        # Rojo (Vencido, Desconectado, Eliminar)

BACKGROUND = "#F8FAFC"    # Gris muy claro (Fondo de la app)
FONDO_APP = "#D3DBE9"     # Gris azulado detrás de las cajas blancas de Clientes y Flota (28-10-2026)
BORDE_CAJA = "#BFCADD"    # Borde de esas cajas blancas sobre FONDO_APP
FILA_ALTERNA_TABLA = "#EDF1F8"  # Filas pares de todas las tablas: un blanco azulado algo más oscuro
FILA_HOVER_TABLA = "#DCE8FB"    # Fila bajo el mouse: un azul algo más vivo que la fila alterna, para distinguirlas
FILA_SELECCION_TABLA = "#C3D8F6"  # Fila seleccionada: un paso más fuerte que el hover
SURFACE = "#FFFFFF"       # Blanco puro (Tarjetas, Tablas)
BORDER = "#E5E7EB"        # Gris claro (Bordes de tablas y tarjetas)

TEXT_PRIMARY = "#1E293B"  # Casi negro (Títulos)
TEXT_SECONDARY = "#475569" # Gris oscuro (Etiquetas, KPIs)
TEXT_MUTED = "#94A3B8"    # Gris medio (Placeholders)

# =========================================================
# Identidad visual por módulo/pantalla (usada por el chip
# de título en el header de main_window.py)
# Clave = nombre interno del módulo (el mismo usado en
# _load_module / _on_menu_clicked / tabs de grupo).
# =========================================================
MODULE_DISPLAY_NAMES = {
    "Dashboard BI": "Dashboard",
    "Vista General": "Clientes y Flota",
    "Comercial": "Comercial",
    "Operaciones": "Operaciones",
    "Provisiones": "Provisiones",
    "Contratos (CM)": "Contratos (CM)",
    "Facturación Manual": "Facturación Manual",
    "JustTime": "JustTime",
    "Historial": "Historial",
    "Configuración": "Configuración",
    "Instalaciones": "Instalaciones",
    "Contactos": "Contactos",
    "Catálogos": "Catálogos",
    "Clientes": "Clientes",
}

MODULE_COLORS = {
    "Dashboard BI": "#2563EB",
    "Vista General": "#0EA5E9",
    "Comercial": "#10B981",
    "Operaciones": "#F59E0B",
    "Provisiones": "#8B5CF6",
    "Contratos (CM)": "#EC4899",
    "Facturación Manual": "#0D9488",
    "JustTime": "#D97706",
    "Historial": "#64748B",
    "Configuración": "#334155",
    "Instalaciones": "#F97316",
    "Contactos": "#06B6D4",
    "Catálogos": "#6366F1",
    "Clientes": "#0EA5E9",
}