"""Analisis estatico (AST) de los archivos de test del proyecto.

No ejecuta nada: solo parsea el codigo fuente de cada archivo test_*.py con el
modulo estandar `ast` y extrae informacion objetiva (docstrings, asserts,
mocks, imports, decoradores, numeros de linea). No infiere significado de
negocio ni inventa objetivos en lenguaje natural: si no hay docstring, se
reporta 'NO DOCUMENTADO'.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


ASSERT_PREFIX = "assert"

# Nombres que, si aparecen como Name/Attribute en el cuerpo de un test,
# delatan uso de unittest.mock. No es una lista cerrada: tambien se detecta
# cualquier import de 'unittest.mock' o 'from unittest.mock import ...'.
MOCK_NAMES = {"Mock", "MagicMock", "patch", "PropertyMock", "AsyncMock", "call", "sentinel", "ANY"}

# Prefijos de import considerados relevantes para entender dependencias de un
# test (evita listar cada import irrelevante, ej. 'os', 'time', 'json').
RELEVANT_IMPORT_PREFIXES = (
    "PyQt6", "pandas", "openpyxl", "unittest.mock", "unittest", "src.", "src",
    "config", "win32com", "pythoncom", "generar_mock_data",
)


@dataclass
class TestMethodInfo:
    class_name: str
    method_name: str
    line: int
    docstring: str
    decorators: list = field(default_factory=list)
    assertions: dict = field(default_factory=dict)   # {"assertEqual": 3, ...}
    mock_usages: list = field(default_factory=list)   # nombres detectados
    calls_skip_test: bool = False
    uses_subtest: bool = False

    @property
    def qualified_name(self) -> str:
        return f"{self.class_name}.{self.method_name}"


@dataclass
class TestClassInfo:
    name: str
    line: int
    docstring: str
    bases: list = field(default_factory=list)
    methods: list = field(default_factory=list)  # list[TestMethodInfo]


@dataclass
class FileAnalysis:
    filename: str
    relpath: str
    is_test_module: bool          # tiene al menos una clase TestCase
    module_docstring: str
    imports: list = field(default_factory=list)
    classes: list = field(default_factory=list)   # list[TestClassInfo]
    parse_error: str = None

    @property
    def test_count(self) -> int:
        return sum(len(c.methods) for c in self.classes)


def _is_testcase_base(base_node: ast.expr) -> bool:
    """True si el nodo base de una clase es TestCase o unittest.TestCase."""
    if isinstance(base_node, ast.Name):
        return base_node.id == "TestCase" or base_node.id.endswith("TestCase")
    if isinstance(base_node, ast.Attribute):
        return base_node.attr == "TestCase" or base_node.attr.endswith("TestCase")
    return False


def _decorator_name(node: ast.expr) -> str:
    """Reconstruye un nombre legible de un decorador (@patch(...), @patch.object(...), etc.)."""
    try:
        if isinstance(node, ast.Call):
            return _decorator_name(node.func) + "(...)"
        if isinstance(node, ast.Attribute):
            return _decorator_name(node.value) + "." + node.attr
        if isinstance(node, ast.Name):
            return node.id
        return ast.unparse(node)
    except Exception:
        return "<decorator>"


def _collect_assertions_and_mocks(func_node: ast.AST):
    """Recorre el cuerpo de un metodo de test y cuenta assertions, detecta
    mocks y detecta self.skipTest()/self.subTest()."""
    assertions: dict = {}
    mock_usages: set = set()
    calls_skip_test = False
    uses_subtest = False

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            func = node.func
            attr_name = None
            if isinstance(func, ast.Attribute):
                attr_name = func.attr
            elif isinstance(func, ast.Name):
                attr_name = func.id

            if attr_name and attr_name.startswith(ASSERT_PREFIX):
                assertions[attr_name] = assertions.get(attr_name, 0) + 1
            elif attr_name == "skipTest":
                calls_skip_test = True
            elif attr_name == "subTest":
                uses_subtest = True
            elif attr_name in MOCK_NAMES:
                mock_usages.add(attr_name)

        elif isinstance(node, ast.Name) and node.id in MOCK_NAMES:
            mock_usages.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in MOCK_NAMES:
            mock_usages.add(node.attr)

    return assertions, sorted(mock_usages), calls_skip_test, uses_subtest


def _extract_imports(tree: ast.Module) -> list:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                found.append(f"{module}.{alias.name}" if module else alias.name)

    relevant = sorted({
        name for name in found
        if name.startswith(RELEVANT_IMPORT_PREFIXES)
    })
    return relevant


def analyze_file(filepath: str, tests_dir: str) -> FileAnalysis:
    """Analiza un unico archivo .py con AST. No ejecuta nada."""
    filename = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, tests_dir)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        return FileAnalysis(
            filename=filename, relpath=relpath, is_test_module=False,
            module_docstring="NO DOCUMENTADO", parse_error=f"No se pudo leer el archivo: {e}",
        )

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return FileAnalysis(
            filename=filename, relpath=relpath, is_test_module=False,
            module_docstring="NO DOCUMENTADO", parse_error=f"SyntaxError al parsear: {e}",
        )

    module_doc = ast.get_docstring(tree) or "NO DOCUMENTADO"
    imports = _extract_imports(tree)
    classes = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_is_testcase_base(b) for b in node.bases):
            continue

        class_doc = ast.get_docstring(node) or "NO DOCUMENTADO"
        base_names = [_decorator_name(b) for b in node.bases]
        methods = []

        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not item.name.startswith("test"):
                continue

            method_doc = ast.get_docstring(item) or "NO DOCUMENTADO"
            decorators = [_decorator_name(d) for d in item.decorator_list]
            assertions, mocks, skip_test, subtest = _collect_assertions_and_mocks(item)

            methods.append(TestMethodInfo(
                class_name=node.name,
                method_name=item.name,
                line=item.lineno,
                docstring=method_doc,
                decorators=decorators,
                assertions=assertions,
                mock_usages=mocks,
                calls_skip_test=skip_test,
                uses_subtest=subtest,
            ))

        classes.append(TestClassInfo(
            name=node.name, line=node.lineno, docstring=class_doc,
            bases=base_names, methods=methods,
        ))

    return FileAnalysis(
        filename=filename, relpath=relpath, is_test_module=bool(classes),
        module_docstring=module_doc, imports=imports, classes=classes,
    )


def analyze_directory(tests_dir: str, filenames: list) -> list:
    """Analiza una lista explicita de archivos (nombres de archivo, no rutas)
    dentro de tests_dir. La lista de archivos a analizar la decide el
    llamador (normalmente: descubrimiento dinamico por glob, no una lista
    fija escrita a mano)."""
    results = []
    for filename in filenames:
        filepath = os.path.join(tests_dir, filename)
        results.append(analyze_file(filepath, tests_dir))
    return results
