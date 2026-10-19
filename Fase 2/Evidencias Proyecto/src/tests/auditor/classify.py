"""Clasificacion HEURISTICA de tests (no una verdad certificada).

Todo resultado de este modulo debe tratarse como una sugerencia basada en
senales objetivas del codigo (imports del modulo, nombre del metodo,
decoradores, uso de mocks). Nunca se declara una categoria como hecho: cada
resultado incluye classification_source='heuristic' y un nivel de
confidence ('high'/'medium'/'low'). Si ninguna senal aplica, se devuelve
'NO DETERMINABLE'.
"""
from __future__ import annotations


# Cada regla: (tag, confidence, funcion(signals) -> bool)
def _has_any(haystack, needles):
    low = haystack.lower()
    return any(n in low for n in needles)


def classify_test(file_analysis, method_info) -> dict:
    """Devuelve {'tags': [...], 'classification_source': 'heuristic',
    'confidence': 'high'/'medium'/'low'/'NO DETERMINABLE'}."""

    module_imports = " ".join(file_analysis.imports).lower()
    method_name = method_info.method_name.lower()
    class_doc = (method_info.docstring or "") + " " + (file_analysis.module_docstring or "")
    class_doc_low = class_doc.lower()
    mocks = set(m.lower() for m in method_info.mock_usages)
    decorators = " ".join(method_info.decorators).lower()

    imports_pyqt = "pyqt6" in module_imports
    imports_openpyxl_or_pandas = ("openpyxl" in module_imports) or ("pandas" in module_imports)
    imports_mock = "unittest.mock" in module_imports or bool(mocks) or "patch" in decorators
    imports_win32 = "win32com" in module_imports or "pythoncom" in module_imports

    signals = []  # (tag, confidence)

    # Unitaria: modulo de servicios puros, sin PyQt6, con o sin mocks minimos.
    if not imports_pyqt and not imports_win32:
        if "_services" in file_analysis.filename or "dataframe_formatter" in file_analysis.filename:
            signals.append(("unitaria", "high"))
        elif not imports_openpyxl_or_pandas:
            signals.append(("unitaria", "medium"))

    # UI: interactua con widgets PyQt6 reales.
    if imports_pyqt:
        signals.append(("interfaz/UI", "medium"))

    # Integracion: PyQt6 + (mock de QThread/hilos) o llamadas a QApplication.processEvents,
    # o espera de hilos (_wait_until, QEventLoop) delatadas por el nombre/imports.
    if imports_pyqt and ("thread" in module_imports or "qeventloop" in module_imports
                          or "async" in method_name or "hilo" in class_doc_low):
        signals.append(("integración", "medium"))

    # Excel / persistencia: uso de openpyxl/pandas ExcelWriter o tempfile con .xlsx/.csv.
    if imports_openpyxl_or_pandas:
        signals.append(("Excel", "medium"))
    if "backup" in method_name or "backup" in class_doc_low:
        signals.append(("backups", "high"))
    if "excel" in method_name or "xlsx" in class_doc_low or "csv" in method_name:
        signals.append(("persistencia", "medium"))

    # Manejo de errores: nombre o docstring menciona fallo/error/excepcion.
    if _has_any(method_name, ("fallo", "error", "invalid", "invalido", "aborta", "exception")):
        signals.append(("manejo de errores", "medium"))

    # Regresion: nombre o docstring menciona explicitamente regresion/bug.
    if _has_any(method_name, ("regresion", "regression")) or _has_any(
        class_doc_low, ("regresion", "bug ", "antes hacia", "antes de esta correccion", "antes,")
    ):
        signals.append(("regresión", "high" if "regresion" in method_name else "medium"))

    # Sincronizacion: senales Qt, hilos coordinados entre modulos.
    if _has_any(method_name, ("sync", "sincroniz")) or _has_any(class_doc_low, ("sincroniz", "signal", "señal")):
        signals.append(("sincronización", "medium"))

    # Configuracion: toca config.settings / ConfiguracionModule.
    if "config" in module_imports or "configuracion" in file_analysis.filename:
        signals.append(("configuración", "low"))

    # Validacion: nombres tipicos de casos de validacion de entrada.
    if _has_any(method_name, ("vacio", "nan", "invalido", "invalid", "limite", "no_reconocido", "no_encuentra")):
        signals.append(("validación", "medium"))

    # Auditoria de codigo fuente (inspect.getsource en el propio test).
    if "inspect" in module_imports:
        signals.append(("auditoría de código fuente", "high"))

    if not signals:
        return {"tags": [], "classification_source": "heuristic", "confidence": "NO DETERMINABLE"}

    # Confidence global = la mas alta entre las señales encontradas.
    order = {"high": 3, "medium": 2, "low": 1}
    best = max(signals, key=lambda s: order[s[1]])
    tags = sorted({t for t, _ in signals})

    return {
        "tags": tags,
        "classification_source": "heuristic",
        "confidence": best[1],
    }
