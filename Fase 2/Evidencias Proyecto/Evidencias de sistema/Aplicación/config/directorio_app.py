import os
import sys

# Carpeta de la aplicación: la del ejecutable, o la raíz del proyecto en desarrollo.
# Ahí viven app_config.json, data/ y logs/, sin importar desde dónde se abra la app.
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
