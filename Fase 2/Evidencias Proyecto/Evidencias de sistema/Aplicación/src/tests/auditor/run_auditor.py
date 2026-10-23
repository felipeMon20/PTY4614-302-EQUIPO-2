#!/usr/bin/env python
"""Auditor automatico y reutilizable de la suite de tests de Volvo Dashboard App.

Uso:
    python src/tests/auditor/run_auditor.py

Que hace, en orden:
    1. Descubre dinamicamente los archivos test_*.py de src/tests (sin lista
       fija escrita a mano) y los analiza con AST (static_analysis.py).
    2. Ejecuta la suite real reutilizando el propio sandbox del proyecto
       (test_main.py::setup_sandbox/teardown_sandbox) con un TestResult
       personalizado que captura el resultado y la duracion de CADA test
       individualmente (dynamic_runner.py).
    3. Aplica una clasificacion heuristica por test, marcada explicitamente
       como tal (classify.py).
    4. Cruza analisis estatico + resultado dinamico por test.
    5. Calcula metricas, agrupacion por archivo/"modulo" (derivado del
       nombre de archivo) y una matriz de trazabilidad.
    6. Verifica integridad: hashea los archivos test_*.py y el
       app_config.json de la raiz antes y despues de ejecutar, para
       confirmar objetivamente que el auditor no los modifico.
    7. Escribe:
         src/tests/logs/AUDITORIA_DATA_<YYYY-MM-DD>.json
         src/tests/logs/AUDITORIA_RESUMEN_<YYYY-MM-DD>.log
       con la fecha de ejecucion real (no una fecha fija).

No modifica ningun test_*.py, ningun archivo de codigo de produccion, ni
ningun Excel maestro. El unico efecto colateral esperado es el que el propio
test_main.py ya produce (regenerar src/tests/mock_data/, y el
respaldo/restauracion temporal de app_config.json de la raiz), mas la
escritura de sus dos archivos de salida en src/tests/logs/.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime

AUDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(AUDITOR_DIR)
PROJECT_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))

sys.path.insert(0, AUDITOR_DIR)
sys.path.insert(0, PROJECT_ROOT)

import static_analysis  # noqa: E402
import dynamic_runner   # noqa: E402
import classify          # noqa: E402
import quality_sync      # noqa: E402


NON_TEST_FILES_ROLE = {
    "test_main.py": "orquestador (setup/teardown de sandbox + suite legada manual)",
    "generar_mock_data.py": "generador de datos mock (fixtures), no es un archivo de test",
}


# ---------------------------------------------------------------------
# Integridad: hash de archivos antes/despues de ejecutar
# ---------------------------------------------------------------------

def _sha256_of(filepath: str) -> str:
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return "NO_EXISTIA"


def _snapshot_hashes(tests_dir: str, project_root: str) -> dict:
    snapshot = {}
    for filename in dynamic_runner.discover_test_files(tests_dir) + ["test_main.py"]:
        snapshot[f"src/tests/{filename}"] = _sha256_of(os.path.join(tests_dir, filename))
    snapshot["app_config.json"] = _sha256_of(os.path.join(project_root, "app_config.json"))
    return snapshot


def _diff_hashes(before: dict, after: dict) -> list:
    changed = []
    for key in before:
        if before[key] != after.get(key):
            changed.append(key)
    return changed


# ---------------------------------------------------------------------
# Fusion de analisis estatico + resultado dinamico
# ---------------------------------------------------------------------

def _module_name_from_filename(filename: str) -> str:
    return os.path.splitext(filename)[0]


def _derived_module_group(filename: str) -> str:
    """Agrupacion NEUTRAL derivada solo del nombre de archivo (sin
    conocimiento de negocio hardcodeado), para que el auditor siga siendo
    valido si se agregan archivos nuevos: 'test_comercial_services.py' ->
    'comercial_services'."""
    name = _module_name_from_filename(filename)
    if name.startswith("test_"):
        name = name[len("test_"):]
    return name or "NO DETERMINABLE"


def build_static_index(file_analyses: list) -> dict:
    """Indexa cada metodo de test estatico por su id completo
    '<modulo>.<Clase>.<metodo>' (mismo formato que unittest TestCase.id())."""
    index = {}
    for fa in file_analyses:
        module_name = _module_name_from_filename(fa.filename)
        for cls in fa.classes:
            for m in cls.methods:
                key = f"{module_name}.{cls.name}.{m.method_name}"
                index[key] = (fa, cls, m)
    return index


def merge_records(dynamic_records: list, static_index: dict) -> list:
    merged = []
    for rec in dynamic_records:
        key = rec["test_id"]
        static_entry = static_index.get(key)
        file_analysis, cls_info, method_info = (None, None, None)
        if static_entry:
            file_analysis, cls_info, method_info = static_entry

        classification = (
            classify.classify_test(file_analysis, method_info)
            if static_entry else
            {"tags": [], "classification_source": "heuristic", "confidence": "NO DETERMINABLE"}
        )

        merged.append({
            "test_id": key,
            "file": f"{rec['module']}.py",
            "module_group": _derived_module_group(f"{rec['module']}.py"),
            "class": rec["class_name"],
            "method": rec["method_name"],
            "line": method_info.line if method_info else None,
            "docstring": method_info.docstring if method_info else "NO DOCUMENTADO",
            "class_docstring": cls_info.docstring if cls_info else "NO DOCUMENTADO",
            "decorators": method_info.decorators if method_info else [],
            "assertions": method_info.assertions if method_info else {},
            "mocks": method_info.mock_usages if method_info else [],
            "calls_skip_test": method_info.calls_skip_test if method_info else False,
            "uses_subtest": method_info.uses_subtest if method_info else False,
            "relevant_imports": file_analysis.imports if file_analysis else [],
            "classification": classification,
            "status": rec["status"],
            "duration_ms": rec["duration_ms"],
            "error": rec["error"],
            "skip_reason": rec["skip_reason"],
        })
    return merged


def assign_case_ids(merged_records: list) -> list:
    """Asigna CP-XXX de forma DETERMINISTA (orden alfabetico por archivo,
    clase, metodo), no por orden de ejecucion, para que el ID de un test
    dado sea estable entre corridas mientras el conjunto de tests no
    cambie."""
    ordered = sorted(merged_records, key=lambda r: (r["file"], r["class"], r["method"]))
    for i, rec in enumerate(ordered, start=1):
        rec["case_id"] = f"CP-{i:03d}"
    # Se devuelve en el orden original (orden real de ejecucion), ya con
    # case_id asignado por referencia.
    id_by_key = {r["test_id"]: r["case_id"] for r in ordered}
    for rec in merged_records:
        rec["case_id"] = id_by_key[rec["test_id"]]
    return merged_records


# ---------------------------------------------------------------------
# Metricas y agregaciones
# ---------------------------------------------------------------------

def compute_summary(merged_records: list, discovery_errors: list) -> dict:
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0, "XFAIL": 0, "XPASS": 0, "UNKNOWN": 0}
    for r in merged_records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(merged_records)
    return {
        "tests_executed": total,
        "pass": counts["PASS"],
        "fail": counts["FAIL"],
        "error": counts["ERROR"],
        "skipped": counts["SKIPPED"],
        "expected_failure": counts["XFAIL"],
        "unexpected_success": counts["XPASS"],
        "unknown": counts["UNKNOWN"],
        "discovery_errors": len(discovery_errors),
        "success": counts["FAIL"] == 0 and counts["ERROR"] == 0 and counts["UNKNOWN"] == 0
                   and len(discovery_errors) == 0,
    }


def compute_module_breakdown(merged_records: list) -> dict:
    modules = {}
    for r in merged_records:
        m = modules.setdefault(r["module_group"], {
            "tests": 0, "pass": 0, "fail": 0, "error": 0, "skipped": 0, "duration_ms": 0.0,
        })
        m["tests"] += 1
        m["duration_ms"] += r["duration_ms"] or 0.0
        status = r["status"]
        if status == "PASS":
            m["pass"] += 1
        elif status == "FAIL":
            m["fail"] += 1
        elif status == "ERROR":
            m["error"] += 1
        elif status == "SKIPPED":
            m["skipped"] += 1
    for m in modules.values():
        m["duration_ms"] = round(m["duration_ms"], 3)
    return dict(sorted(modules.items()))


def detect_coverage_tooling(project_root: str) -> dict:
    """Detecta (sin instalar nada) si el proyecto ya tiene configurada una
    herramienta de cobertura de codigo. No confunde esto con cobertura
    funcional."""
    candidates = {
        ".coveragerc": os.path.join(project_root, ".coveragerc"),
        "pyproject.toml [tool.coverage]": os.path.join(project_root, "pyproject.toml"),
        "setup.cfg [coverage:run]": os.path.join(project_root, "setup.cfg"),
    }
    found = {}
    for label, path in candidates.items():
        if not os.path.exists(path):
            continue
        if label.startswith("pyproject") or label.startswith("setup.cfg"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "coverage" in content.lower():
                    found[label] = path
            except Exception:
                pass
        else:
            found[label] = path

    requirements_path = os.path.join(project_root, "requirements.txt")
    coverage_in_requirements = False
    if os.path.exists(requirements_path):
        try:
            with open(requirements_path, "r", encoding="utf-16") as f:
                content = f.read()
        except Exception:
            try:
                with open(requirements_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                content = ""
        coverage_in_requirements = ("coverage" in content.lower())

    if found or coverage_in_requirements:
        return {"available": True, "evidence": found, "in_requirements_txt": coverage_in_requirements}
    return {"available": False, "note": "Cobertura de código: NO DISPONIBLE (no se encontró .coveragerc, "
                                          "sección [tool.coverage]/[coverage:run], ni 'coverage'/'pytest-cov' "
                                          "en requirements.txt)."}


# ---------------------------------------------------------------------
# Escritura de reportes
# ---------------------------------------------------------------------

def write_json_report(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _fmt_ms(ms):
    if ms is None:
        return "NO DETERMINABLE"
    return f"{ms:.1f}ms"


def write_log_report(path: str, data: dict):
    meta = data["metadata"]
    summary = data["summary"]
    metrics = data["metrics"]
    modules = data["modules"]
    tests = data["tests"]
    files = data["files"]
    integrity = data["integrity"]
    coverage = data["coverage_tooling"]

    lines = []
    add = lines.append

    add("=" * 60)
    add("AUDITORÍA AUTOMÁTICA DE TESTS")
    add("VOLVO DASHBOARD APP")
    add("=" * 60)
    add("")

    add("-" * 60)
    add("1. ENTORNO")
    add("-" * 60)
    add(f"Fecha/hora de ejecución : {meta['generated_at']}")
    add(f"Python                  : {meta['python_version']}")
    add(f"Framework               : {meta['framework']}")
    add(f"pytest instalado        : {meta['pytest_installed']}")
    add(f"Directorio de tests     : {meta['tests_dir']}")
    add(f"Raíz del proyecto       : {meta['project_root']}")
    add(f"Mecanismo de ejecución  : {meta['execution_mechanism']}")
    add(f"Generador               : {meta['generator']} v{meta['generator_version']}")
    if meta.get("run_error"):
        add("")
        add("*** ATENCIÓN: la ejecución dinámica lanzó una excepción no controlada. ***")
        add(meta["run_error"])
    add("")

    add("-" * 60)
    add("2. RESUMEN DE EJECUCIÓN")
    add("-" * 60)
    add(f"Archivos de test descubiertos : {meta['files_discovered_for_execution']}")
    add(f"Clases TestCase descubiertas  : {meta['classes_discovered']}")
    add(f"Tests descubiertos (estático) : {meta['tests_discovered_static']}")
    add(f"Tests ejecutados              : {summary['tests_executed']}")
    add(f"PASS      : {summary['pass']}")
    add(f"FAIL      : {summary['fail']}")
    add(f"ERROR     : {summary['error']}")
    add(f"SKIPPED   : {summary['skipped']}")
    add(f"XFAIL     : {summary['expected_failure']}")
    add(f"XPASS     : {summary['unexpected_success']}")
    add(f"UNKNOWN   : {summary['unknown']}")
    add(f"Errores de descubrimiento (import/carga de clase): {summary['discovery_errors']}")
    add(f"Éxito global (0 FAIL/ERROR/UNKNOWN/discovery_errors): {summary['success']}")
    add("")

    add("-" * 60)
    add("3. MÉTRICAS")
    add("-" * 60)
    add(f"Duración total (suma de tests) : {_fmt_ms(metrics['duration_total_ms'])}")
    add(f"Duración promedio              : {_fmt_ms(metrics['duration_avg_ms'])}")
    add(f"Duración mediana               : {_fmt_ms(metrics['duration_median_ms'])}")
    add(f"Duración mínima                : {_fmt_ms(metrics['duration_min_ms'])}")
    add(f"Duración máxima                : {_fmt_ms(metrics['duration_max_ms'])}")
    if metrics["slowest_test"]:
        add(f"Test más lento  : {metrics['slowest_test']['test_id']} ({_fmt_ms(metrics['slowest_test']['duration_ms'])})")
    if metrics["fastest_test"]:
        add(f"Test más rápido : {metrics['fastest_test']['test_id']} ({_fmt_ms(metrics['fastest_test']['duration_ms'])})")
    add(f"% PASS    : {metrics['pass_rate_pct']}%")
    add(f"% FAIL    : {metrics['fail_rate_pct']}%")
    add(f"% ERROR   : {metrics['error_rate_pct']}%")
    add(f"% SKIPPED : {metrics['skipped_rate_pct']}%")
    add("NOTA: la duración de setUpClass/tearDownClass compartidos por una clase")
    add("  NO se atribuye al primer test individual; se mide por separado como")
    add("  duración de grupo (ver 'class_groups' en el JSON) para no distorsionar")
    add("  el tiempo real de cada método de test.")
    add("")

    add("-" * 60)
    add("4. ARCHIVOS DE TEST")
    add("-" * 60)
    for f in files:
        if f["is_test_file"]:
            add(f"{f['file']:45s} clases={f['classes']:<3} tests={f['tests']:<4} PASS={f['pass']} FAIL={f['fail']} ERROR={f['error']} SKIPPED={f['skipped']}")
        else:
            add(f"{f['file']:45s} (no es archivo de test — {f['role']})")
    add("")

    add("-" * 60)
    add("5. RESUMEN POR MÓDULO (derivado del nombre de archivo, no de dominio de negocio)")
    add("-" * 60)
    for mod, agg in modules.items():
        add(f"{mod:30s} tests={agg['tests']:<4} PASS={agg['pass']:<4} FAIL={agg['fail']:<3} ERROR={agg['error']:<3} SKIPPED={agg['skipped']:<3} dur={_fmt_ms(agg['duration_ms'])}")
    add("")

    add("-" * 60)
    add("6. RESULTADOS ANÓMALOS")
    add("-" * 60)
    fails = [t for t in tests if t["status"] == "FAIL"]
    errors = [t for t in tests if t["status"] == "ERROR"]
    skips = [t for t in tests if t["status"] == "SKIPPED"]
    add(f"FAIL ({len(fails)}):")
    if not fails:
        add("  (ninguno)")
    for t in fails:
        add(f"  - {t['case_id']} {t['test_id']}")
        if t["error"]:
            add(f"      {t['error']['type']}: {t['error']['message']}")
    add(f"ERROR ({len(errors)}):")
    if not errors:
        add("  (ninguno)")
    for t in errors:
        add(f"  - {t['case_id']} {t['test_id']}")
        if t["error"]:
            add(f"      {t['error']['type']}: {t['error']['message']}")
    add(f"SKIPPED ({len(skips)}):")
    if not skips:
        add("  (ninguno)")
    for t in skips:
        add(f"  - {t['case_id']} {t['test_id']} — motivo: {t['skip_reason']}")
    if data["discovery_errors"]:
        add(f"Errores de descubrimiento/importación ({len(data['discovery_errors'])}):")
        for e in data["discovery_errors"]:
            add(f"  - {e['file']} [{e['stage']}]: {e['error']}")
    add("")
    add("Detalle completo de traceback disponible en el JSON (campo 'error.traceback' por test).")
    add("")

    add("-" * 60)
    add("7. ANÁLISIS ESTÁTICO (AST)")
    add("-" * 60)
    total_assertions = {}
    total_mocks = set()
    tests_sin_docstring = 0
    tests_con_mocks = 0
    tests_con_subtest = 0
    for t in tests:
        for name, count in t["assertions"].items():
            total_assertions[name] = total_assertions.get(name, 0) + count
        if t["mocks"]:
            tests_con_mocks += 1
            total_mocks.update(t["mocks"])
        if t["docstring"] == "NO DOCUMENTADO":
            tests_sin_docstring += 1
        if t["uses_subtest"]:
            tests_con_subtest += 1
    add(f"Tests sin docstring (NO DOCUMENTADO): {tests_sin_docstring} / {len(tests)}")
    add(f"Tests que usan mocks/patch: {tests_con_mocks} / {len(tests)}")
    add(f"Tests que usan subTest(): {tests_con_subtest}")
    add("Assertions detectadas (nombre: apariciones totales):")
    for name, count in sorted(total_assertions.items(), key=lambda x: -x[1]):
        add(f"  {name:25s} {count}")
    add(f"Tipos de mock detectados: {', '.join(sorted(total_mocks)) if total_mocks else 'ninguno'}")
    add("")
    add("Clasificación heurística (classification_source=heuristic; NUNCA un hecho confirmado):")
    conf_counts = {}
    for t in tests:
        conf = t["classification"]["confidence"]
        conf_counts[conf] = conf_counts.get(conf, 0) + 1
    for conf, count in sorted(conf_counts.items(), key=lambda x: -x[1]):
        add(f"  confidence={conf:15s} {count} tests")
    add("")

    add("-" * 60)
    add("8. RECURSOS / FIXTURES")
    add("-" * 60)
    add("Generador de datos mock : generar_mock_data.py (6 archivos Excel en src/tests/mock_data/,")
    add("  regenerados en cada ejecución — 'Clean Slate' — por test_main.py::setup_sandbox()).")
    add("Sandbox real reutilizado: test_main.py::setup_sandbox()/teardown_sandbox() (respalda y")
    add("  sobreescribe temporalmente app_config.json de la raíz; se restaura al finalizar).")
    add(f"Archivos de test descubiertos dinámicamente: {len(data['files_executed'])}")
    add("")

    add("-" * 60)
    add("9. MATRIZ DE TRAZABILIDAD")
    add("-" * 60)
    add(f"{'ID':8s} {'Test':48s} {'Archivo':34s} {'Módulo':20s} {'Tipo':30s} {'Estado':8s} {'Tiempo'}")
    for t in sorted(tests, key=lambda r: r["case_id"]):
        tipo = ",".join(t["classification"]["tags"]) or "NO DETERMINABLE"
        test_name = f"{t['class']}.{t['method']}"
        add(f"{t['case_id']:8s} {test_name[:48]:48s} {t['file'][:34]:34s} {t['module_group'][:20]:20s} {tipo[:30]:30s} {t['status']:8s} {_fmt_ms(t['duration_ms'])}")
    add("")

    add("-" * 60)
    add("10. COBERTURA DISPONIBLE")
    add("-" * 60)
    if coverage["available"]:
        add("Cobertura de código: herramienta detectada en el proyecto.")
        add(json.dumps(coverage, indent=2, ensure_ascii=False))
    else:
        add(coverage["note"])
    add("Cobertura FUNCIONAL (no de código): ver sección 5 (resumen por módulo derivado de archivo)")
    add("  y el campo 'modules' del JSON — indica qué archivos/módulos tienen al menos un test,")
    add("  no qué porcentaje de líneas de producción se ejecutó.")
    add("")

    add("-" * 60)
    add("11. OBSERVACIONES")
    add("-" * 60)
    add(f"Integridad de archivos de test: {'SIN CAMBIOS' if not integrity['test_files_changed'] else 'CAMBIOS DETECTADOS -> ' + str(integrity['test_files_changed'])}")
    add(f"Integridad de app_config.json (raíz): {'RESTAURADO CORRECTAMENTE' if not integrity['app_config_changed'] else 'DIFERENTE TRAS LA EJECUCIÓN (revisar)'}")
    add("Metodología: el estado PASS/FAIL/ERROR/SKIPPED de cada test proviene de los eventos reales")
    add("  emitidos por unittest.TestResult (addSuccess/addFailure/addError/addSkip) durante ESTA")
    add("  ejecución, no de una suposición basada en el resultado agregado de la suite.")
    add("Reutilización: este auditor descubre archivos/clases/tests dinámicamente (glob + introspección")
    add("  de módulos importados); no contiene ninguna lista fija de nombres de test. Si se agregan o")
    add("  eliminan tests, una nueva ejecución reflejará el cambio automáticamente.")
    add("")
    add("Información disponible para documentación de calidad (no redactada aquí, solo referenciada):")
    add(f"  - Plan de Pruebas: módulos, tipos de prueba (heurísticos) y cantidad total ({summary['tests_executed']}).")
    add(f"  - Casos de Prueba: los {summary['tests_executed']} registros de 'tests' en el JSON (docstring, línea,")
    add("    assertions, precondiciones inferibles de decoradores/mocks).")
    add(f"  - Reporte de Ejecución: sección 2 y 3 de este log, y 'summary'/'metrics' del JSON.")
    add(f"  - Reporte de Defectos: sección 6 (solo 'test_failure' real, nunca 'confirmed_defect' automático;")
    add("    la confirmación de un defecto requiere revisión humana).")
    add("  - Gestión de Cambios / RFC: INFORMACIÓN NO DISPONIBLE EN LOS TESTS (requiere historial de")
    add("    control de versiones y contexto de negocio, fuera del alcance de este auditor).")
    add("")

    add("=" * 60)
    add("FIN")
    add("=" * 60)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main():
    run_started_at = datetime.now()
    date_str = run_started_at.strftime("%Y-%m-%d")
    logs_dir = os.path.join(TESTS_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    json_path = os.path.join(logs_dir, f"AUDITORIA_DATA_{date_str}.json")
    log_path = os.path.join(logs_dir, f"AUDITORIA_RESUMEN_{date_str}.log")

    print(f"[auditor] Directorio de tests : {TESTS_DIR}")
    print(f"[auditor] Raíz del proyecto   : {PROJECT_ROOT}")

    hashes_before = _snapshot_hashes(TESTS_DIR, PROJECT_ROOT)

    # -- 1) Descubrimiento + analisis estatico -------------------------
    exec_files = dynamic_runner.discover_test_files(TESTS_DIR)
    all_test_pattern_files = sorted(
        os.path.basename(p) for p in
        __import__("glob").glob(os.path.join(TESTS_DIR, "test_*.py"))
    )
    non_test_extra = ["generar_mock_data.py"] if os.path.exists(
        os.path.join(TESTS_DIR, "generar_mock_data.py")) else []

    static_files = static_analysis.analyze_directory(
        TESTS_DIR, all_test_pattern_files + non_test_extra
    )
    print(f"[auditor] Archivos analizados estáticamente: {len(static_files)}")

    static_index = build_static_index(static_files)
    print(f"[auditor] Tests detectados (AST, estático): {len(static_index)}")

    # -- 2) Ejecucion dinamica real -------------------------------------
    run_error = None
    try:
        run_result = dynamic_runner.run_all(TESTS_DIR, PROJECT_ROOT)
    except Exception:
        run_error = traceback.format_exc()
        run_result = {
            "files_executed": exec_files, "discovery_errors": [],
            "class_groups": [], "records": [], "subtest_records": [],
            "was_successful": False, "testsRun": 0,
        }

    hashes_after = _snapshot_hashes(TESTS_DIR, PROJECT_ROOT)
    changed_test_files = [
        k for k in _diff_hashes(hashes_before, hashes_after) if k != "app_config.json"
    ]
    app_config_changed = hashes_before.get("app_config.json") != hashes_after.get("app_config.json")

    # -- 3) Fusion + metricas -------------------------------------------
    merged = merge_records(run_result["records"], static_index)
    merged = assign_case_ids(merged)
    metrics = dynamic_runner.compute_duration_metrics(run_result["records"])
    summary = compute_summary(merged, run_result["discovery_errors"])
    if run_error or summary["tests_executed"] == 0:
        summary["success"] = False

    total = summary["tests_executed"] or 1
    metrics["pass_rate_pct"] = round(summary["pass"] / total * 100, 2)
    metrics["fail_rate_pct"] = round(summary["fail"] / total * 100, 2)
    metrics["error_rate_pct"] = round(summary["error"] / total * 100, 2)
    metrics["skipped_rate_pct"] = round(summary["skipped"] / total * 100, 2)

    module_breakdown = compute_module_breakdown(merged)
    coverage_tooling = detect_coverage_tooling(PROJECT_ROOT)

    # -- 4) Inventario de archivos (para secciones 4 y JSON 'files') ----
    files_report = []
    per_file_status = {}
    for r in merged:
        agg = per_file_status.setdefault(r["file"], {"pass": 0, "fail": 0, "error": 0, "skipped": 0})
        key = r["status"].lower()
        if key in agg:
            agg[key] += 1

    for fa in static_files:
        is_test = fa.is_test_module
        entry = {
            "file": fa.filename,
            "relpath": fa.relpath,
            "is_test_file": is_test,
            "module_docstring": fa.module_docstring,
            "classes": len(fa.classes),
            "tests": fa.test_count,
            "parse_error": fa.parse_error,
        }
        if is_test:
            agg = per_file_status.get(fa.filename, {"pass": 0, "fail": 0, "error": 0, "skipped": 0})
            entry.update(agg)
        else:
            entry["role"] = NON_TEST_FILES_ROLE.get(fa.filename, "NO DETERMINABLE")
        files_report.append(entry)

    traceability = [
        {
            "id": r["case_id"], "test": f"{r['class']}.{r['method']}", "file": r["file"],
            "module": r["module_group"], "tipo": ",".join(r["classification"]["tags"]) or "NO DETERMINABLE",
            "estado": r["status"], "tiempo_ms": r["duration_ms"],
        }
        for r in sorted(merged, key=lambda x: x["case_id"])
    ]

    metadata = {
        "generated_at": run_started_at.isoformat(timespec="seconds"),
        "generator": "volvo_dashboard_app.auditor",
        "generator_version": "1.0",
        "python_version": sys.version.split()[0],
        "framework": "unittest",
        "pytest_installed": _detect_pytest_installed(),
        "tests_dir": TESTS_DIR,
        "project_root": PROJECT_ROOT,
        "execution_mechanism": (
            "unittest dinámico (glob + TestLoader), reutilizando "
            "test_main.py::setup_sandbox()/teardown_sandbox() para el entorno sandbox real"
        ),
        "files_discovered_for_execution": len(run_result["files_executed"]),
        "classes_discovered": len({(m["file"], m["class"]) for m in merged}) or len(
            {(k.split(".")[0], v[1].name) for k, v in static_index.items()}
        ),
        "tests_discovered_static": len(static_index),
        "run_error": run_error,
    }

    integrity = {
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
        "test_files_changed": changed_test_files,
        "app_config_changed": app_config_changed,
    }

    quality_docs_info = {
        "plan_de_pruebas": {
            "modulos_cubiertos": list(module_breakdown.keys()),
            "cantidad_total_tests": summary["tests_executed"],
            "framework": "unittest",
        },
        "casos_de_prueba": {"fuente": "campo 'tests' del JSON, uno por caso, con case_id CP-XXX"},
        "reporte_de_ejecucion": {"resumen": summary, "metricas": metrics},
        "reporte_de_defectos": {
            "nota": "Solo se reportan 'test_failure' reales (FAIL/ERROR de esta ejecución). "
                    "La confirmación como defecto del sistema requiere revisión humana.",
            "fallidos": [t["case_id"] for t in merged if t["status"] in ("FAIL", "ERROR")],
        },
        "gestion_de_cambios": "INFORMACIÓN NO DISPONIBLE EN LOS TESTS",
        "rfc": "INFORMACIÓN NO DISPONIBLE EN LOS TESTS",
    }

    data = {
        "metadata": metadata,
        "summary": summary,
        "metrics": metrics,
        "files": files_report,
        "files_executed": run_result["files_executed"],
        "tests": merged,
        "modules": module_breakdown,
        "failures": [t for t in merged if t["status"] == "FAIL"],
        "errors": [t for t in merged if t["status"] == "ERROR"],
        "skipped": [t for t in merged if t["status"] == "SKIPPED"],
        "subtests": run_result["subtest_records"],
        "discovery_errors": run_result["discovery_errors"],
        "class_groups": run_result["class_groups"],
        "traceability": traceability,
        "coverage_tooling": coverage_tooling,
        "integrity": integrity,
        "quality_docs_info": quality_docs_info,
    }

    write_json_report(json_path, data)
    write_log_report(log_path, data)

    print(f"[auditor] JSON: {json_path}")
    print(f"[auditor] LOG : {log_path}")
    print(f"[auditor] Tests: {summary['tests_executed']} | PASS={summary['pass']} FAIL={summary['fail']} "
          f"ERROR={summary['error']} SKIPPED={summary['skipped']}")
    print(f"[auditor] Archivos de test modificados por la auditoría: {changed_test_files or 'ninguno'}")
    print(f"[auditor] app_config.json restaurado correctamente: {not app_config_changed}")
    if run_error:
        print("[auditor] ATENCIÓN: la ejecución dinámica lanzó una excepción no controlada:")
        print(run_error)

    # -- 5) Sincronizacion automatica de duoc/calidad -------------------
    # Resultado de TESTS y resultado de SINCRONIZACION DE CALIDAD son dos
    # cosas distintas: un fallo aqui nunca altera ni oculta el resultado
    # real de los tests ya calculado arriba (summary/success no se tocan).
    try:
        quality_report = quality_sync.sync(data, PROJECT_ROOT)
    except Exception:
        quality_report = {
            "ok": False, "skipped": False,
            "events": [f"[QUALITY] ERROR no controlado en quality_sync.sync(): {traceback.format_exc()}"],
            "documents": {},
        }
    for line in quality_report["events"]:
        print(line)
    if not quality_report.get("skipped"):
        print(f"[QUALITY] Resultado: {'OK' if quality_report['ok'] else 'CON ERRORES'} "
              f"— detalle en {os.path.join(logs_dir, f'QUALITY_SYNC_{date_str}.log')}")
    quality_sync.write_quality_sync_log(logs_dir, date_str, quality_report)
    data["quality_sync"] = quality_report

    return data


def _detect_pytest_installed() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("pytest") is not None
    except Exception:
        return False


if __name__ == "__main__":
    main()
