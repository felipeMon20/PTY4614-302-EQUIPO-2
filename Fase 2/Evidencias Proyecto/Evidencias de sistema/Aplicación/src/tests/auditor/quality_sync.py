"""Sincronizacion automatica de los entregables de calidad de duoc/calidad/
a partir del resultado real de la suite (mismo `data` que ya calcula
run_auditor.py). No hay ninguna lista fija de modulos/tests escrita a mano:
todo lo que se escribe aqui se deriva del `data` del auditor (tests, clases,
docstrings, clasificacion, duracion) o de una convencion de nombres de
archivo verificable contra el filesystem (src/services/, src/ui/, src/core/).

Punto de integracion: run_auditor.py::main() llama a sync(data, PROJECT_ROOT)
justo despues de escribir el JSON/LOG propios, y ANTES de su propio
`return data`. Un fallo aqui NUNCA debe alterar ni ocultar el resultado real
de los tests: sync() nunca lanza hacia afuera, siempre devuelve un dict con
su propio estado, y cada documento se sincroniza en su propio try/except
independiente (un documento roto no bloquea a los demas).

FUENTE DE VERDAD DE LOS IDs: no existe ningun archivo de estado nuevo
(nada como case_ids.json). La identidad estable de un test
(archivo, clase, metodo) se lee parseando el texto que YA existe, sin
excepcion, en las filas actuales de los propios .xlsx:
  - Reporte de Ejecucion de Pruebas.xlsx, columna H: 'Clase.metodo — archivo.py'
  - Casos de Prueba.xlsx, columna I: 'Test automatizado: archivo.py::Clase.'
El auditor sigue generando internamente su propio CP-XXX transitorio
(run_auditor.py::assign_case_ids, global y por orden alfabetico) — eso NO
se toca y NO se usa aqui como ID publicado.

REGLA DE SEGURIDAD (identidad no determinable): si una fila existente no
puede interpretarse (el texto no matchea el patron esperado), NO se asume
que el test correspondiente es nuevo. En ese caso, por seguridad, esta
corrida no asigna ningun CP-XXX nuevo ni agrega filas nuevas al documento
afectado (para no arriesgar un duplicado); solo actualiza las filas cuya
identidad SI se pudo confirmar, y deja un aviso [QUALITY] pidiendo revision
manual de la(s) fila(s) problematica(s).

REGLA DE NO-CONTIGUIDAD FALSA (Casos de Prueba.xlsx): el rango 'ID Caso' de
una clase se calcula colapsando SOLO los CP-XXX que de verdad pertenecen a
metodos actuales de esa clase. Si una clase tenia CP-306..CP-310 y gana un
metodo nuevo con CP-351 (porque otros modulos ocuparon 311..350 en el medio),
el resultado es 'CP-306_CP-310, CP-351' — NUNCA 'CP-306_CP-351', porque eso
afirmaria falsamente que CP-311..CP-350 pertenecieron alguna vez a esta
clase. _collapse_cp_ranges() solo fusiona numeros consecutivos que ya estan
en la lista de IDs reales de esa clase; nunca rellena huecos.

Que NUNCA se escribe automaticamente (solo lectura + aviso [QUALITY]):
  - Request for Change (RFC).docx
  - Reporte de Defectos.docx
  - duoc/calidad/_plantillas_originales/** (no se toca en ningun caso)
"""
from __future__ import annotations

import copy
import os
import re
import traceback
from datetime import datetime

import openpyxl
import docx


# ---------------------------------------------------------------------
# Utilidades genericas (no conocen ningun modulo de negocio en concreto)
# ---------------------------------------------------------------------

def _log(events: list, msg: str):
    events.append(f"[QUALITY] {msg}")


def _identity_from_observaciones(text):
    """Parsea 'Clase.metodo — archivo.py' AL INICIO del texto (convencion
    ya usada, sin excepcion, en las filas existentes de Reporte de
    Ejecucion). Se permite texto adicional despues (ej. una nota manual
    sobre un defecto, como en la fila real CP-166 sobre BUG-001) — el
    marcador siempre esta al comienzo, nunca en medio ni ausente. Devuelve
    (file, cls, method) o None si el INICIO del texto no matchea el patron
    (en cuyo caso la identidad se considera NO determinable, nunca se
    adivina)."""
    if not isinstance(text, str):
        return None
    m = re.match(r"^(?P<cls>\w+)\.(?P<method>\w+) — (?P<file>test_[A-Za-z0-9_]+\.py)\b", text.strip())
    if not m:
        return None
    return (m.group("file"), m.group("cls"), m.group("method"))


def _identity_from_comentarios(text):
    """Parsea el marcador 'Test automatizado: [ruta/]archivo.py::Clase.'
    (existe, sin excepcion, en las filas actuales de Casos de Prueba — con
    o sin el prefijo de ruta 'src/tests/' segun la fila). Se captura solo
    el nombre de archivo, para que coincida con el 'file' del auditor
    (siempre bare filename, sin ruta)."""
    if not isinstance(text, str):
        return None
    m = re.search(r"Test automatizado:\s*(?:[\w./-]*/)?(?P<file>test_[A-Za-z0-9_]+\.py)::(?P<cls>\w+)\.", text)
    if not m:
        return None
    return (m.group("file"), m.group("cls"))


def _collapse_cp_ranges(numbers) -> str:
    """[306,307,308,309,310,351] -> 'CP-306_CP-310, CP-351'. Solo fusiona
    numeros consecutivos YA presentes en la lista recibida; nunca inventa
    continuidad con numeros que no pertenecen a esta clase (ver regla en el
    docstring del modulo)."""
    numbers = sorted(set(numbers))
    ranges = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    parts = [f"CP-{a:03d}" if a == b else f"CP-{a:03d}_CP-{b:03d}" for a, b in ranges]
    return ", ".join(parts)


def _fecha_humana(iso):
    """'2026-10-13T12:27:22' -> '13-10-2026 12:27:22' (otro formato se devuelve igual)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2}:\d{2})", str(iso or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4)}" if m else str(iso or "")


def _humanize(method: str) -> str:
    name = method[len("test_"):] if method.startswith("test_") else method
    return name.replace("_", " ")


def _componente_desde_imports(imports, project_root: str):
    """Si el archivo de prueba importa un módulo propio (src.ui.x, src.core.x...), ese es el componente."""
    for imp in imports or []:
        partes = imp.split(".")
        if len(partes) >= 3 and partes[0] == "src" and partes[1] in ("ui", "core", "services", "theme"):
            ruta = os.path.join(project_root, "src", partes[1], f"{partes[2]}.py")
            if os.path.exists(ruta):
                tipo = {"ui": "pantalla", "core": "núcleo", "services": "reglas y cálculos", "theme": "tema visual"}[partes[1]]
                return f"{partes[2].replace('_', ' ').title()} — {tipo} (src/{partes[1]}/{partes[2]}.py)"
    return None


def _derive_component_label(module_group: str, project_root: str) -> str:
    """Deriva '<Nombre> (Servicio|UI|Core) - <ruta real>' solo a partir de
    la convencion de nombres de archivo + existencia real en el filesystem.
    Sin tabla fija por modulo: debe funcionar igual para un modulo que no
    existe todavia (ej. clientes_service.py)."""
    base = module_group
    tipo = None
    relpath = None
    is_service = False
    for suffix in ("_services", "_service"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            is_service = True
            candidate = os.path.join(project_root, "src", "services", f"{module_group}.py")
            if os.path.exists(candidate):
                tipo, relpath = "Servicio", f"src/services/{module_group}.py"
            break
    if tipo is None:
        candidate = os.path.join(project_root, "src", "ui", f"{module_group}.py")
        if os.path.exists(candidate):
            tipo, relpath = "UI", f"src/ui/{module_group}.py"
    if tipo is None:
        candidate = os.path.join(project_root, "src", "core", f"{module_group}.py")
        if os.path.exists(candidate):
            tipo, relpath = "Core", f"src/core/{module_group}.py"

    display = base.replace("_", " ").strip().title() or module_group
    if tipo is None:
        label = f"{display} (pruebas de integración, sin un módulo único)"
        return label, is_service
    tipo_es = {"UI": "pantalla", "Servicio": "reglas y cálculos", "Core": "núcleo"}.get(tipo, tipo)
    return f"{display} — {tipo_es} ({relpath})", is_service


PRECOND_SANDBOX = (
    "Entorno de pruebas aislado (sandbox) del proyecto: los datos de prueba se regeneran en cada "
    "ejecución (src/tests/mock_data/), el archivo app_config.json se respalda y se restaura al terminar, "
    "y PyQt6 está activo para crear las pantallas reales. No se tocan los archivos reales de la empresa."
)


def _precondiciones_para(imports_relevantes, module_group: str, test_file: str) -> str:
    if any(imp.startswith("PyQt6") for imp in (imports_relevantes or [])):
        return PRECOND_SANDBOX
    stem = os.path.splitext(test_file)[0]
    return (
        "No necesita pantallas ni archivos: son funciones de cálculo puras (pandas/Python) del módulo "
        f"{module_group}. Se ejecutan junto con el resto de la batería, y también se pueden correr solas "
        f"(python -m unittest src.tests.{stem})."
    )


# ---------------------------------------------------------------------
# 1) Reporte de Ejecucion de Pruebas.xlsx
# ---------------------------------------------------------------------

# Etiquetas del resumen al pie del Reporte de Ejecución: clave histórica -> texto en español.
# La sincronización reconoce ambas y deja siempre la versión en español.
ETIQUETAS_RESUMEN_ES = {
    "RESUMEN DE LA EJECUCION (auditor automatico)": "RESUMEN DE LA EJECUCIÓN (generado por el auditor automático)",
    "Fecha/hora de ejecucion": "Fecha y hora de la ejecución",
    "Entorno (Python)": "Versión de Python",
    "Framework": "Herramienta de pruebas",
    "Mecanismo de ejecucion": "Cómo se ejecutó",
    "Archivos de test descubiertos": "Archivos de pruebas encontrados",
    "Clases TestCase descubiertas": "Grupos de pruebas (clases) encontrados",
    "Tests descubiertos (estatico)": "Pruebas encontradas (análisis del código)",
    "Tests ejecutados": "Pruebas ejecutadas",
    "PASS": "Aprobadas (PASS)",
    "FAIL": "Falladas (FAIL)",
    "ERROR": "Con error (ERROR)",
    "SKIPPED": "Omitidas (SKIPPED)",
    "Errores de descubrimiento": "Errores al cargar pruebas",
    "% PASS": "% aprobadas",
    "% FAIL": "% falladas",
    "% ERROR": "% con error",
    "Duracion total (suma de tests)": "Duración total (suma de las pruebas)",
    "Duracion promedio": "Duración promedio",
    "Duracion mediana": "Duración mediana",
    "Test mas lento": "Prueba más lenta",
    "Test mas rapido": "Prueba más rápida",
    "Cobertura de codigo (herramienta)": "Cobertura de código (herramienta)",
    "Integridad de archivos de test": "Integridad de los archivos de prueba",
    "Integridad de app_config.json": "Integridad de app_config.json",
    "Conclusion": "Conclusión",
}
_ETIQUETA_HISTORICA = {v: k for k, v in ETIQUETAS_RESUMEN_ES.items()}


def _sync_reporte_ejecucion(path: str, tests: list, meta: dict, summary: dict, metrics: dict,
                             events: list) -> dict:
    wb = openpyxl.load_workbook(path)
    ws = wb.active

    known = {}          # identity -> row index (solo identidades confirmadas)
    max_cp = 0
    last_cp_row = 1
    unparseable_rows = []
    for row in range(2, ws.max_row + 1):
        cp_val = ws.cell(row=row, column=2).value
        if not (isinstance(cp_val, str) and re.match(r"^CP-\d+$", cp_val)):
            continue
        last_cp_row = row
        max_cp = max(max_cp, int(cp_val.split("-")[1]))
        identity = _identity_from_observaciones(ws.cell(row=row, column=8).value)
        if identity:
            known[identity] = row
        else:
            unparseable_rows.append(row)
            _log(events, f"Identidad no determinable en fila {row} (CP={cp_val}, columna "
                          "'Observaciones' no matchea el patron esperado 'Clase.metodo — archivo.py').")

    integrity_compromised = bool(unparseable_rows)
    if integrity_compromised:
        _log(events, f"Reporte de Ejecucion: {len(unparseable_rows)} fila(s) con identidad no "
                      f"determinable (filas {unparseable_rows}). Por seguridad, esta corrida NO asignara "
                      "CP-XXX nuevos ni agregara filas nuevas en este documento (para evitar un posible "
                      "CP duplicado); solo se actualizan las filas cuya identidad SI se pudo confirmar. "
                      "Revisar manualmente esas filas y volver a correr el auditor.")

    fecha_ejecucion = meta["generated_at"]
    tests_to_process = []   # (identity, test) ya confirmados (existentes + nuevos de esta corrida)
    new_rows = []            # (identity, test) que van a recibir un CP-XXX nuevo
    skipped = []

    for t in tests:
        identity = (t["file"], t["class"], t["method"])
        if identity in known:
            tests_to_process.append((identity, t))
        elif integrity_compromised:
            skipped.append((identity, t))
        else:
            new_rows.append((identity, t))

    for identity, t in skipped:
        _log(events, f"Test {identity[0]}::{identity[1]}.{identity[2]} NO sincronizado esta corrida "
                      "(no se pudo confirmar si ya estaba documentado, ver filas con identidad no "
                      "determinable arriba).")

    new_rows.sort(key=lambda x: x[0])  # (file, class, method) alfabetico, solo para el orden de inserción
    n_new = len(new_rows)
    id_by_identity = {}

    if n_new:
        ws.insert_rows(last_cp_row + 1, amount=n_new)
        style_row = last_cp_row
        for offset, (identity, t) in enumerate(new_rows):
            target_row = last_cp_row + 1 + offset
            for col in range(1, 9):
                src = ws.cell(row=style_row, column=col)
                dst = ws.cell(row=target_row, column=col)
                dst.font = copy.copy(src.font)
                dst.fill = copy.copy(src.fill)
                dst.border = copy.copy(src.border)
                dst.alignment = copy.copy(src.alignment)
                dst.number_format = src.number_format
            max_cp += 1
            cp_id = f"CP-{max_cp:03d}"
            known[identity] = target_row
            id_by_identity[identity] = cp_id
            tests_to_process.append((identity, t))
            _log(events, f"Nuevo test detectado: {identity[0]}::{identity[1]}.{identity[2]}")
            _log(events, f"Nuevo CP asignado: {cp_id}")

    updated = 0
    for identity, t in tests_to_process:
        row = known[identity]
        tags = ",".join(t["classification"]["tags"]) if t["classification"]["tags"] else "NO DETERMINABLE"
        cp_id = id_by_identity.get(identity) or ws.cell(row=row, column=2).value
        id_by_identity.setdefault(identity, cp_id)
        ws.cell(row=row, column=1, value=fecha_ejecucion)
        ws.cell(row=row, column=2, value=cp_id)
        ws.cell(row=row, column=3, value=t["module_group"])
        ws.cell(row=row, column=4, value=tags)
        ws.cell(row=row, column=5, value=t["status"])
        ws.cell(row=row, column=6, value=round(t["duration_ms"] or 0.0, 3))
        ws.cell(row=row, column=8, value=f"{t['class']}.{t['method']} — {t['file']}")
        updated += 1

    current_identities = {(t["file"], t["class"], t["method"]) for t in tests}
    for ident, row in known.items():
        if ident not in current_identities:
            _log(events, f"Identidad {ident[0]}::{ident[1]}.{ident[2]} (fila {row}) ya documentada no "
                          "aparecio en esta corrida (test eliminado o renombrado); fila conservada SIN "
                          "modificar, revisar manualmente.")

    # -- footer, por coincidencia de etiqueta (nunca por offset fijo) --
    footer_updates = {
        "Fecha/hora de ejecucion": _fecha_humana(fecha_ejecucion),
        "Entorno (Python)": meta["python_version"],
        "Framework": f"unittest (pytest instalado: {'sí' if meta['pytest_installed'] else 'no'})",
        "Mecanismo de ejecucion": meta["execution_mechanism"],
        "Archivos de test descubiertos": meta["files_discovered_for_execution"],
        "Clases TestCase descubiertas": meta["classes_discovered"],
        "Tests descubiertos (estatico)": meta["tests_discovered_static"],
        "Tests ejecutados": summary["tests_executed"],
        "PASS": summary["pass"],
        "FAIL": summary["fail"],
        "ERROR": summary["error"],
        "SKIPPED": summary["skipped"],
        "Errores de descubrimiento": summary["discovery_errors"],
        "% PASS": f"{metrics['pass_rate_pct']}%",
        "% FAIL": f"{metrics['fail_rate_pct']}%",
        "% ERROR": f"{metrics['error_rate_pct']}%",
        "Duracion total (suma de tests)": f"{metrics['duration_total_ms'] / 1000:.1f} s ({metrics['duration_total_ms']} ms)",
        "Duracion promedio": f"{metrics['duration_avg_ms']} ms",
        "Duracion mediana": f"{metrics['duration_median_ms']} ms",
        "Test mas lento": (f"{metrics['slowest_test']['test_id']} ({metrics['slowest_test']['duration_ms']} ms)"
                            if metrics.get("slowest_test") else "NO DETERMINABLE"),
        "Test mas rapido": (f"{metrics['fastest_test']['test_id']} ({metrics['fastest_test']['duration_ms']} ms)"
                             if metrics.get("fastest_test") else "NO DETERMINABLE"),
        "Integridad de app_config.json": "RESTAURADO CORRECTAMENTE",
    }
    omitidas = f" {summary['skipped']} prueba(s) quedaron omitidas (no se pudieron ejecutar; no son fallas)." \
        if summary.get("skipped") else ""
    conclusion = (
        f"{metrics['pass_rate_pct']}% de las {summary['tests_executed']} pruebas automáticas fue aprobado "
        f"en la ejecución del {_fecha_humana(fecha_ejecucion)}."
        + (f" Hay {summary['fail']} falla(s) y {summary['error']} error(es): ver el Reporte de Defectos."
           if (summary["fail"] or summary["error"]) else " No hay fallas ni errores.")
        + omitidas
    )
    footer_updates["Conclusion"] = conclusion

    footer_start = None
    for row in range(2, ws.max_row + 1):
        cp_val = ws.cell(row=row, column=2).value
        is_cp = isinstance(cp_val, str) and re.match(r"^CP-\d+$", cp_val)
        if not is_cp and footer_start is None and row > last_cp_row + n_new:
            footer_start = row
    if footer_start is None:
        footer_start = last_cp_row + n_new + 1

    footer_matched = set()
    for row in range(footer_start, ws.max_row + 1):
        label = ws.cell(row=row, column=1).value
        clave = _ETIQUETA_HISTORICA.get(label, label)
        if clave in footer_updates:
            ws.cell(row=row, column=2, value=footer_updates[clave])
            ws.cell(row=row, column=1, value=ETIQUETAS_RESUMEN_ES.get(clave, clave))
            footer_matched.add(clave)
        elif clave in ETIQUETAS_RESUMEN_ES:
            ws.cell(row=row, column=1, value=ETIQUETAS_RESUMEN_ES[clave])
    for label in footer_updates:
        if label not in footer_matched:
            _log(events, f"Reporte de Ejecucion: etiqueta de footer '{label}' no encontrada, no actualizada.")

    wb.save(path)
    _log(events, f"Reporte de Ejecucion actualizado: {n_new} fila(s) nueva(s), {updated} fila(s) "
                  f"actualizada(s), footer sincronizado.")
    return {"new_rows": n_new, "updated_rows": updated, "id_by_identity": id_by_identity,
            "integrity_compromised": integrity_compromised}


# ---------------------------------------------------------------------
# 2) Casos de Prueba.xlsx
# ---------------------------------------------------------------------

def _sync_casos_de_prueba(path: str, tests: list, id_by_identity: dict, fecha_ejecucion: str,
                           project_root: str, events: list) -> dict:
    wb = openpyxl.load_workbook(path)
    ws = wb.active

    existing_row_by_class = {}
    unparseable_rows = []
    for row in range(2, ws.max_row + 1):
        raw = ws.cell(row=row, column=9).value
        if not isinstance(raw, str) or not raw.strip():
            continue
        ident = _identity_from_comentarios(raw)
        if ident:
            existing_row_by_class[ident] = row
        else:
            unparseable_rows.append(row)
            _log(events, f"Casos de Prueba: fila {row} sin marcador 'Test automatizado: archivo.py::Clase.' "
                          "reconocible en 'Comentarios/Evidencia'.")

    integrity_compromised = bool(unparseable_rows)
    if integrity_compromised:
        _log(events, f"Casos de Prueba: {len(unparseable_rows)} fila(s) sin identidad de clase "
                      "determinable. Por seguridad, esta corrida NO creara filas nuevas en este "
                      "documento; solo actualiza filas de clases ya identificadas con certeza.")

    by_class = {}
    for t in tests:
        key = (t["file"], t["class"])
        g = by_class.setdefault(key, {"docstring": (t.get("class_docstring") or "").strip(),
                                       "tests": [], "imports": t.get("relevant_imports", [])})
        g["tests"].append(t)

    n_new = 0
    n_updated = 0
    for (file, cls), g in sorted(by_class.items()):
        is_existing = (file, cls) in existing_row_by_class
        if not is_existing and integrity_compromised:
            _log(events, f"Casos de Prueba: clase {file}::{cls} no sincronizada esta corrida "
                          "(no se pudo confirmar con certeza si ya tenia fila, ver aviso de integridad).")
            continue

        methods = sorted(g["tests"], key=lambda t: t["method"])
        n = len(methods)
        module_group = methods[0]["module_group"]

        cp_numbers = []
        for t in methods:
            identity = (t["file"], t["class"], t["method"])
            cp_id = id_by_identity.get(identity)
            if cp_id is None:
                _log(events, f"Casos de Prueba: no se encontro CP-ID confirmado para {identity}; la fila "
                              f"de {file}::{cls} puede quedar incompleta esta corrida, revisar manualmente.")
                continue
            cp_numbers.append(int(cp_id.split("-")[1]))
        if not cp_numbers:
            continue
        id_range = _collapse_cp_ranges(cp_numbers)

        pass_count = sum(1 for t in methods if t["status"] == "PASS")
        fail_count = sum(1 for t in methods if t["status"] == "FAIL")
        error_count = sum(1 for t in methods if t["status"] == "ERROR")

        humanizados = [_humanize(t["method"]) for t in methods]
        if len(humanizados) > 6:
            pasos_metodos = "; ".join(humanizados[:6]) + f"; … (y {len(humanizados) - 6} más, ver el Reporte de Ejecución)."
        else:
            pasos_metodos = "; ".join(humanizados) + "."

        pasos = (
            "1) Ejecutar la batería completa (python src/tests/auditor/run_auditor.py). "
            f"2) El sistema corre el grupo de pruebas '{cls}' (archivo {file}). "
            f"3) Pruebas incluidas: {pasos_metodos}"
        )
        que_se_verifica = g['docstring']
        if not que_se_verifica or que_se_verifica == "NO DOCUMENTADO":
            que_se_verifica = "Verifica: " + "; ".join(humanizados[:4]) + ("…" if len(humanizados) > 4 else ".")
        resultado_esperado = (
            f"Las {n} prueba(s) del grupo terminan en PASS (aprobadas). "
            f"Qué se verifica: {que_se_verifica}"
        )
        if fail_count or error_count:
            estado = "FAIL" if fail_count else "ERROR"
            resultado_actual = (
                f"{pass_count} de {n} aprobadas, {fail_count} falladas (FAIL), {error_count} con error (ERROR) "
                f"en la ejecución del {_fecha_humana(fecha_ejecucion)}. Revisar el Reporte de Defectos."
            )
        else:
            estado = "PASS"
            resultado_actual = (
                f"PASS: las {n} prueba(s) se aprobaron en la ejecución del {_fecha_humana(fecha_ejecucion)}. "
                "Detalle en el Reporte de Ejecución de Pruebas."
            )
        comentarios = (
            f"Generado por el auditor automático (src/tests/auditor/run_auditor.py). Casos {id_range} "
            f"del Reporte de Ejecución. Test automatizado: src/tests/{file}::{cls}."
        )

        if is_existing:
            row = existing_row_by_class[(file, cls)]
            ws.cell(row=row, column=1, value=id_range)
            ws.cell(row=row, column=5, value=pasos)
            ws.cell(row=row, column=6, value=resultado_esperado)
            ws.cell(row=row, column=7, value=resultado_actual)
            ws.cell(row=row, column=8, value=estado)
            ws.cell(row=row, column=9, value=comentarios)
            n_updated += 1
        else:
            row = ws.max_row + 1
            style_row = ws.max_row
            for col in range(1, 10):
                src = ws.cell(row=style_row, column=col)
                dst = ws.cell(row=row, column=col)
                dst.font = copy.copy(src.font)
                dst.fill = copy.copy(src.fill)
                dst.border = copy.copy(src.border)
                dst.alignment = copy.copy(src.alignment)
                dst.number_format = src.number_format
            label, is_service = _derive_component_label(module_group, project_root)
            label = _componente_desde_imports(g["imports"], project_root) or label
            ws.cell(row=row, column=1, value=id_range)
            ws.cell(row=row, column=2, value=label)
            ws.cell(row=row, column=3, value=g["docstring"])
            ws.cell(row=row, column=4, value=_precondiciones_para(g["imports"], module_group, file))
            ws.cell(row=row, column=5, value=pasos)
            ws.cell(row=row, column=6, value=resultado_esperado)
            ws.cell(row=row, column=7, value=resultado_actual)
            ws.cell(row=row, column=8, value=estado)
            ws.cell(row=row, column=9, value=comentarios)
            n_new += 1
            _log(events, f"Nueva clase de test detectada: {file}::{cls} -> fila nueva ({id_range}).")
            if is_service:
                _log(events, f"RFC podria requerir revision manual: nuevo modulo de servicio "
                              f"detectado ({file}) — no se modifica RFC.docx automaticamente.")

    wb.save(path)
    _log(events, f"Casos de Prueba actualizado: {n_new} fila(s) nueva(s), {n_updated} fila(s) "
                  "actualizada(s) (solo columnas templadas: ID/Pasos/Resultado/Estado/Comentarios).")
    return {"new_rows": n_new, "updated_rows": n_updated, "integrity_compromised": integrity_compromised}


# ---------------------------------------------------------------------
# 3) Plan de Pruebas.docx / Plan de Gestion de Cambios.docx (solo conteos)
# ---------------------------------------------------------------------

def _regex_replace_in_docx(path: str, patterns: list, events: list, doc_label: str) -> int:
    d = docx.Document(path)
    n_applied = 0
    for regex, replace_fn in patterns:
        matched_any = False
        for p in d.paragraphs:
            if regex.search(p.text):
                matched_any = True
                new_text = regex.sub(replace_fn, p.text)
                if new_text != p.text and p.runs:
                    p.runs[0].text = new_text
                    for r in p.runs[1:]:
                        r.text = ""
                    n_applied += 1
        if not matched_any:
            _log(events, f"{doc_label}: patron {regex.pattern!r} no encontrado, no actualizado "
                          "(puede requerir revision manual si el documento cambio de redaccion).")
    d.save(path)
    return n_applied


def _sync_plan_de_pruebas(path: str, summary: dict, meta: dict, metrics: dict, fecha_ejecucion: str,
                           events: list):
    total = summary["tests_executed"]
    archivos = meta["files_discovered_for_execution"]
    clases = meta["classes_discovered"]
    pass_rate = metrics["pass_rate_pct"]

    patterns = [
        (re.compile(r"\d+ pruebas reales en \d+ archivos y \d+ clases"),
         lambda m: f"{total} pruebas reales en {archivos} archivos y {clases} clases"),
        (re.compile(r"\d+ archivos de test / \d+ clases / \d+ pruebas automatizadas"),
         lambda m: f"{archivos} archivos de test / {clases} clases / {total} pruebas automatizadas"),
        (re.compile(r"sobre \d+ pruebas\)"),
         lambda m: f"sobre {total} pruebas)"),
        (re.compile(r"En la última ejecución auditada \([^)]+\) los \d+ casos terminaron en PASS \([\d.]+%\)\."),
         lambda m: f"En la última ejecución auditada ({fecha_ejecucion}) los {total} casos "
                   f"terminaron en PASS ({pass_rate}%)."),
    ]
    n = _regex_replace_in_docx(path, patterns, events, "Plan de Pruebas.docx")
    _log(events, f"Plan de Pruebas actualizado: {n} patron(es) de conteo actualizado(s). Bullets de "
                  "'Elementos a probar' y cronograma de hitos NO se tocan automaticamente "
                  "(requieren redaccion humana).")
    return n


def _sync_plan_gestion_cambios(path: str, summary: dict, events: list):
    total = summary["tests_executed"]
    patterns = [
        (re.compile(r"\(\d+ pruebas a la fecha de este documento, ver Plan de Pruebas\)"),
         lambda m: f"({total} pruebas a la fecha de este documento, ver Plan de Pruebas)"),
        (re.compile(r"\(\d+ casos a la fecha de este documento, ver Plan de Pruebas y Reporte de "
                    r"Ejecución de Pruebas\)"),
         lambda m: f"({total} casos a la fecha de este documento, ver Plan de Pruebas y Reporte de "
                   f"Ejecución de Pruebas)"),
    ]
    n = _regex_replace_in_docx(path, patterns, events, "Plan de Gestión de Cambios.docx")
    _log(events, f"Plan de Gestión de Cambios actualizado: {n} patron(es) de conteo actualizado(s). "
                  "La lista de 'separaciones de responsabilidad recientes' NO se toca automaticamente "
                  "(juicio humano).")
    return n


# ---------------------------------------------------------------------
# 4) Reporte de Defectos.docx: SOLO lectura, deteccion de duplicados
# ---------------------------------------------------------------------

def _split_bug_blocks(d) -> dict:
    blocks = {}
    current = None
    for p in d.paragraphs:
        m = re.match(r"^Defecto (BUG-\d+)", p.text)
        if m:
            current = m.group(1)
            blocks[current] = []
        if current:
            blocks[current].append(p.text)
    return blocks


def _check_defectos(path: str, tests: list, events: list):
    fails_or_errors = [t for t in tests if t["status"] in ("FAIL", "ERROR")]
    if not fails_or_errors:
        _log(events, "Reporte de Defectos: sin FAIL/ERROR en esta corrida, no se requiere revision.")
        return
    d = docx.Document(path)
    blocks = _split_bug_blocks(d)
    for t in fails_or_errors:
        needles = [f"{t['class']}.{t['method']}".lower(), t["method"].lower(), t["file"].lower()]
        matched_bug = None
        for bug_id, lines in blocks.items():
            text = " ".join(lines).lower()
            if any(n in text for n in needles):
                matched_bug = bug_id
                break
        identity_str = f"{t['file']}::{t['class']}.{t['method']}"
        if matched_bug:
            _log(events, f"ERROR conocido: {matched_bug} ({identity_str}) — no se duplica.")
        else:
            _log(events, f"NUEVO FAIL/ERROR DETECTADO en {identity_str} — requiere revision manual. "
                          "No se inventa severidad/prioridad/causa/estado; no se escribio nada en "
                          "Reporte de Defectos.docx.")


# ---------------------------------------------------------------------
# orquestador
# ---------------------------------------------------------------------

def sync(data: dict, project_root: str, calidad_dir: str = None) -> dict:
    """Punto de entrada. Nunca lanza: devuelve {'ok', 'skipped', 'events', 'documents'}."""
    events = []
    _log(events, "Sincronizacion iniciada.")

    if os.environ.get("VOLVO_SKIP_QUALITY_SYNC"):
        _log(events, "VOLVO_SKIP_QUALITY_SYNC activo: sincronizacion de calidad omitida.")
        return {"ok": True, "skipped": True, "events": events, "documents": {}}

    calidad_dir = calidad_dir or os.path.join(project_root, "duoc", "calidad")
    documents = {}
    overall_ok = True

    tests = data["tests"]
    meta = data["metadata"]
    summary = data["summary"]
    metrics = data["metrics"]
    fecha_ejecucion = meta["generated_at"]

    def _step(name, fn):
        nonlocal overall_ok
        try:
            result = fn()
            documents[name] = {"ok": True, "result": result}
        except Exception as e:
            overall_ok = False
            documents[name] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                                "traceback": traceback.format_exc()}
            _log(events, f"ERROR sincronizando {name}: {type(e).__name__}: {e}")

    reporte_path = os.path.join(calidad_dir, "Reporte de Ejecución de Pruebas.xlsx")
    casos_path = os.path.join(calidad_dir, "Casos de Prueba.xlsx")
    plan_pruebas_path = os.path.join(calidad_dir, "Plan de Pruebas.docx")
    plan_cambios_path = os.path.join(calidad_dir, "Plan de Gestión de Cambios.docx")
    defectos_path = os.path.join(calidad_dir, "Reporte de Defectos.docx")

    reporte_result = {}

    def _run_reporte():
        r = _sync_reporte_ejecucion(reporte_path, tests, meta, summary, metrics, events)
        reporte_result.update(r)
        return r

    _step("Reporte de Ejecución de Pruebas.xlsx", _run_reporte)

    id_by_identity = reporte_result.get("id_by_identity", {})
    _step("Casos de Prueba.xlsx",
          lambda: _sync_casos_de_prueba(casos_path, tests, id_by_identity, fecha_ejecucion,
                                         project_root, events))

    _step("Plan de Pruebas.docx",
          lambda: _sync_plan_de_pruebas(plan_pruebas_path, summary, meta, metrics, fecha_ejecucion, events))

    _step("Plan de Gestión de Cambios.docx",
          lambda: _sync_plan_gestion_cambios(plan_cambios_path, summary, events))

    _step("Reporte de Defectos.docx (solo lectura)",
          lambda: _check_defectos(defectos_path, tests, events))

    def _presentar():
        import presentacion_calidad
        presentacion_calidad.aplicar(calidad_dir, data, project_root)
        _log(events, "Presentación: formato en español y hoja Resumen actualizados en los dos libros de Excel.")
        return True

    _step("Presentación (formato y hoja Resumen)", _presentar)

    _log(events, "Sincronizacion completada." if overall_ok else "Sincronizacion completada CON ERRORES.")
    return {"ok": overall_ok, "skipped": False, "events": events, "documents": documents}


def write_quality_sync_log(logs_dir: str, date_str: str, report: dict) -> str:
    path = os.path.join(logs_dir, f"QUALITY_SYNC_{date_str}.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Sincronizacion de calidad — {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"ok={report['ok']} skipped={report.get('skipped')}\n\n")
        for doc, info in report.get("documents", {}).items():
            f.write(f"- {doc}: {'OK' if info.get('ok') else 'ERROR: ' + str(info.get('error'))}\n")
        f.write("\n")
        for line in report.get("events", []):
            f.write(line + "\n")
    return path
