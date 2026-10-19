"""Ejecucion dinamica de la suite real de tests mediante unittest.

No hay ninguna lista fija de archivos/clases/tests escrita a mano: los
archivos test_*.py se descubren con glob sobre el directorio de tests, y las
clases TestCase se descubren inspeccionando cada modulo importado (filtrando
por `obj.__module__ == module.__name__` para no duplicar clases que un
modulo pueda re-exportar de otro, como hace test_main.py).

test_main.py se importa (una sola vez) UNICAMENTE para reutilizar su propio
mecanismo real de entorno de pruebas (setup_sandbox/teardown_sandbox): este
auditor no reimplementa esa logica por separado, para respetar exactamente
el comportamiento actual del proyecto (generacion de datos mock, respaldo y
sobreescritura temporal de app_config.json, reset del singleton
DataManager). test_main.py se EXCLUYE de la ejecucion dinamica de tests
propiamente dicha (el descubrimiento por glob no lo incluye como fuente de
tests), precisamente porque re-exporta clases de todos los demas archivos y
correrlo tambien duplicaria cada test.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import re
import statistics
import sys
import time
import traceback
import unittest


# Archivos dentro de src/tests que NO deben tratarse como fuente de tests
# aunque coincidan con el patron test_*.py, porque son el orquestador
# existente del proyecto (test_main.py), no un archivo de test en si mismo.
EXCLUDED_FROM_EXECUTION = {"test_main.py"}


def discover_test_files(tests_dir: str) -> list:
    """Devuelve, ordenados alfabeticamente, los nombres de archivo
    test_*.py de nivel superior en tests_dir (sin recursividad: coincide con
    la convencion actual del proyecto, que no usa subpaquetes de test)."""
    pattern = os.path.join(tests_dir, "test_*.py")
    files = sorted(os.path.basename(p) for p in glob.glob(pattern))
    return [f for f in files if f not in EXCLUDED_FROM_EXECUTION]


def _ensure_sys_path(project_root: str, tests_dir: str):
    for p in (project_root, tests_dir):
        if p not in sys.path:
            sys.path.insert(0, p)


_BARE_TEST_MODULE_RE = re.compile(r"^test_[a-zA-Z0-9_]+$")


def import_test_main(tests_dir: str, project_root: str):
    """Importa test_main.py como modulo (sin ejecutar su bloque
    `if __name__ == '__main__':`) para reutilizar setup_sandbox()/
    teardown_sandbox(). Se hace con importlib para no depender de que
    tests_dir ya este en sys.path bajo el nombre exacto 'test_main'.

    Ademas devuelve el ORDEN real en que test_main.py importa (via sus
    propios `from test_X import ...`) cada archivo de test, derivado
    dinamicamente observando el orden de insercion en sys.modules durante
    el import (no es una lista escrita a mano por el auditor: se lee del
    propio comportamiento del archivo del proyecto). Este orden se usa
    despues solo para decidir en que secuencia CORRER las clases, de forma
    fiel al comportamiento actual de la suite (test_main.py agrupa
    deliberadamente Comercial/Provisiones/Contactos primero, etc.), evitando
    que un orden arbitrario del auditor (ej. alfabetico por archivo)
    introduzca dependencias de estado compartido/temporizacion distintas a
    las de una corrida normal del proyecto."""
    _ensure_sys_path(project_root, tests_dir)
    modules_before = set(sys.modules.keys())

    module_path = os.path.join(tests_dir, "test_main.py")
    spec = importlib.util.spec_from_file_location("test_main", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_main"] = module
    spec.loader.exec_module(module)

    import_order = [
        name for name in sys.modules.keys()
        if name not in modules_before
        and name != "test_main"
        and _BARE_TEST_MODULE_RE.match(name)
    ]
    return module, import_order


def import_test_module(filename: str, tests_dir: str):
    """Importa un archivo test_*.py como modulo top-level (mismo estilo de
    import que usa el propio proyecto: bare imports asumiendo tests_dir en
    sys.path)."""
    module_name = os.path.splitext(filename)[0]
    if module_name in sys.modules:
        return sys.modules[module_name]
    module_path = os.path.join(tests_dir, filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _testcase_classes_defined_in(module) -> list:
    """Clases unittest.TestCase definidas EN ESTE modulo (no importadas /
    re-exportadas desde otro). Ordenadas alfabeticamente, igual que el
    comportamiento por defecto de unittest.TestLoader.loadTestsFromModule."""
    found = []
    for name in dir(module):
        obj = getattr(module, name)
        if (isinstance(obj, type)
                and issubclass(obj, unittest.TestCase)
                and getattr(obj, "__module__", None) == module.__name__):
            found.append(obj)
    found.sort(key=lambda c: c.__name__)
    return found


class AuditingTestResult(unittest.TestResult):
    """TestResult que registra, por cada test individual, su estado real
    (PASS/FAIL/ERROR/SKIPPED/XFAIL/XPASS), duracion, y detalle de error o
    motivo de skip cuando corresponda. No asume que 'wasSuccessful()==True'
    implica PASS por test: cada estado se registra desde el evento real que
    unittest dispara (addSuccess/addFailure/addError/addSkip/...)."""

    def __init__(self):
        super().__init__()
        self.records = []          # list[dict] en orden de ejecucion
        self.subtest_records = []  # list[dict], subTest() individuales
        self._by_test_id = {}      # id(test) -> record dict (en curso)

    # -- helpers -----------------------------------------------------
    @staticmethod
    def _describe(test) -> dict:
        """Extrae identificacion de un test de forma defensiva: durante un
        fallo de setUpClass, unittest sustituye la instancia real por un
        _ErrorHolder que no tiene todos los atributos habituales."""
        method_name = getattr(test, "_testMethodName", None)
        cls = test.__class__.__name__
        module = getattr(test.__class__, "__module__", "NO DETERMINABLE")
        try:
            full_id = test.id()
        except Exception:
            full_id = str(test)
        if method_name is None:
            # _ErrorHolder: description suele ser algo como
            # "setUpClass (test_x.TestX)"
            method_name = getattr(test, "description", full_id)
        return {
            "test_id": full_id,
            "module": module,
            "class_name": cls,
            "method_name": method_name,
        }

    def _exc_to_dict(self, err, test) -> dict:
        exc_type, exc_value, tb = err
        formatted = self._exc_info_to_string(err, test)
        return {
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "message": str(exc_value),
            "traceback": formatted,
        }

    # -- ciclo de vida por test ---------------------------------------
    def startTest(self, test):
        super().startTest(test)
        info = self._describe(test)
        record = {
            **info,
            "status": None,
            "start_perf": time.perf_counter(),
            "duration_ms": None,
            "error": None,
            "skip_reason": None,
        }
        self._by_test_id[id(test)] = record
        self.records.append(record)

    def stopTest(self, test):
        record = self._by_test_id.get(id(test))
        if record is not None:
            end = time.perf_counter()
            record["duration_ms"] = round((end - record["start_perf"]) * 1000, 3)
            del record["start_perf"]
            if record["status"] is None:
                # No debería ocurrir (unittest siempre llama a un add*
                # antes de stopTest), pero se deja constancia explícita
                # en vez de asumir PASS silenciosamente.
                record["status"] = "UNKNOWN"
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "PASS"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "FAIL"
            rec["error"] = self._exc_to_dict(err, test)

    def addError(self, test, err):
        super().addError(test, err)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "ERROR"
            rec["error"] = self._exc_to_dict(err, test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "SKIPPED"
            rec["skip_reason"] = reason

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "XFAIL"
            rec["error"] = self._exc_to_dict(err, test)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        rec = self._by_test_id.get(id(test))
        if rec is not None:
            rec["status"] = "XPASS"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        parent = self._describe(test)
        entry = {
            "parent_test_id": parent["test_id"],
            "subtest_id": str(subtest),
            "params": getattr(subtest, "params", {}),
            "status": "PASS" if err is None else (
                "FAIL" if issubclass(err[0], test.failureException) else "ERROR"
            ),
            "error": None if err is None else self._exc_to_dict(err, test),
        }
        self.subtest_records.append(entry)


def _run_group_and_time(suite: unittest.TestSuite, result: AuditingTestResult) -> float:
    start = time.perf_counter()
    suite.run(result)
    return round((time.perf_counter() - start) * 1000, 3)


def run_all(tests_dir: str, project_root: str) -> dict:
    """Orquesta: sandbox real del proyecto -> QApplication -> descubrimiento
    dinamico -> ejecucion agrupada por clase (para atribuir el tiempo de
    setUpClass/tearDownClass a la clase, no falsamente al primer test) ->
    restauracion garantizada del entorno (try/finally)."""
    _ensure_sys_path(project_root, tests_dir)

    from PyQt6.QtWidgets import QApplication

    test_main_module, import_order = import_test_main(tests_dir, project_root)

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    discovered = discover_test_files(tests_dir)
    stem_to_file = {os.path.splitext(f)[0]: f for f in discovered}

    # Orden de ejecucion: primero, el orden real observado al importar
    # test_main.py (fiel al comportamiento actual del proyecto); despues,
    # cualquier archivo test_*.py descubierto por glob que NO este referenciado
    # todavia en test_main.py (por ejemplo, un archivo agregado recientemente
    # al proyecto) se ejecuta igualmente, al final, en orden alfabetico.
    files = []
    seen = set()
    for stem in import_order:
        f = stem_to_file.get(stem)
        if f and f not in seen:
            files.append(f)
            seen.add(f)
    for f in discovered:
        if f not in seen:
            files.append(f)
            seen.add(f)

    loader = unittest.TestLoader()
    result = AuditingTestResult()
    class_groups = []  # {"file","class","duration_ms","test_count"}
    discovery_errors = []

    sandbox_ready = False
    try:
        test_main_module.setup_sandbox()
        sandbox_ready = True

        for filename in files:
            try:
                module = import_test_module(filename, tests_dir)
            except Exception as e:
                discovery_errors.append({
                    "file": filename,
                    "stage": "import",
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                })
                continue

            for cls in _testcase_classes_defined_in(module):
                try:
                    suite = loader.loadTestsFromTestCase(cls)
                except Exception as e:
                    discovery_errors.append({
                        "file": filename,
                        "stage": "load_tests_from_class",
                        "class": cls.__name__,
                        "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc(),
                    })
                    continue

                test_count = suite.countTestCases()
                duration_ms = _run_group_and_time(suite, result)
                class_groups.append({
                    "file": filename,
                    "class": cls.__name__,
                    "test_count": test_count,
                    "duration_ms": duration_ms,
                })
    finally:
        if sandbox_ready:
            test_main_module.teardown_sandbox()

    return {
        "files_executed": files,
        "discovery_errors": discovery_errors,
        "class_groups": class_groups,
        "records": result.records,
        "subtest_records": result.subtest_records,
        "was_successful": result.wasSuccessful(),
        "testsRun": result.testsRun,
    }


def compute_duration_metrics(records: list) -> dict:
    durations = [r["duration_ms"] for r in records if r.get("duration_ms") is not None]
    if not durations:
        return {
            "duration_total_ms": 0, "duration_avg_ms": 0, "duration_median_ms": 0,
            "duration_min_ms": 0, "duration_max_ms": 0,
            "slowest_test": None, "fastest_test": None,
        }

    total = round(sum(durations), 3)
    avg = round(total / len(durations), 3)
    median = round(statistics.median(durations), 3)

    slowest = max(records, key=lambda r: r.get("duration_ms") or -1)
    fastest = min(
        (r for r in records if r.get("duration_ms") is not None),
        key=lambda r: r["duration_ms"],
    )

    return {
        "duration_total_ms": total,
        "duration_avg_ms": avg,
        "duration_median_ms": median,
        "duration_min_ms": min(durations),
        "duration_max_ms": max(durations),
        "slowest_test": {"test_id": slowest["test_id"], "duration_ms": slowest["duration_ms"]},
        "fastest_test": {"test_id": fastest["test_id"], "duration_ms": fastest["duration_ms"]},
    }
