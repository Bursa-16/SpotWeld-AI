"""Stage 2A architecture tests: the new domain modules stay pure.

Locks the Stage 2A architectural rules statically, via AST inspection of the
actual imports/calls (so documentation prose cannot cause false positives):

* no import of, or attribute access to, the quarantined prototype rules
  engine (``rules_engine`` / ``DEFAULT_RULES``);
* no FastAPI / SQLAlchemy / Pydantic / repository / model / db / Alembic
  imports;
* no I/O primitives (``open``/``eval``/``exec`` calls).
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = BACKEND_ROOT / "app" / "domain"

STAGE_2A_MODULES = (
    "rule_applicability.py",
    "rule_evaluation.py",
    "unit_policy.py",
    "readiness.py",
)

FORBIDDEN_IMPORT_ROOTS = (
    "rules_engine",
    "fastapi",
    "sqlalchemy",
    "pydantic",
    "alembic",
    "requests",
    "httpx",
)
FORBIDDEN_IMPORT_MODULES = (
    "app.repositories",
    "app.models",
    "app.db",
    "app.domain.rules_engine",
)
FORBIDDEN_CALLS = ("open", "eval", "exec", "compile")
REGISTRY_AUTHORITY_TYPES = (
    "EngineeringRuleRevision",
    "EvidenceClass",
    "RuleLifecycleStatus",
)


def _module_tree(module_name: str) -> ast.Module:
    source = (DOMAIN_DIR / module_name).read_text(encoding="utf-8-sig")
    return ast.parse(source, filename=module_name)


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(node.module.split(".")[0])
    return names


def test_stage_2a_modules_exist() -> None:
    for module_name in STAGE_2A_MODULES:
        assert (DOMAIN_DIR / module_name).is_file(), module_name


def test_stage_2a_modules_do_not_import_quarantined_prototype() -> None:
    for module_name in STAGE_2A_MODULES:
        tree = _module_tree(module_name)
        imported = _imported_names(tree)
        for imported_name in imported:
            assert "rules_engine" not in imported_name, (
                f"{module_name} imports quarantined prototype: {imported_name}"
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "DEFAULT_RULES":
                raise AssertionError(
                    f"{module_name} references DEFAULT_RULES"
                )
            if isinstance(node, ast.Name) and node.id == "DEFAULT_RULES":
                raise AssertionError(
                    f"{module_name} references DEFAULT_RULES"
                )


def test_stage_2a_modules_do_not_import_frameworks_or_persistence() -> None:
    for module_name in STAGE_2A_MODULES:
        imported = _imported_names(_module_tree(module_name))
        for imported_name in imported:
            for forbidden in FORBIDDEN_IMPORT_ROOTS:
                assert imported_name != forbidden, (
                    f"{module_name} imports {imported_name}"
                )
            for forbidden_module in FORBIDDEN_IMPORT_MODULES:
                assert imported_name != forbidden_module and not (
                    imported_name.startswith(f"{forbidden_module}.")
                ), f"{module_name} imports {imported_name}"


def test_stage_2a_modules_perform_no_io() -> None:
    for module_name in STAGE_2A_MODULES:
        tree = _module_tree(module_name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                called_name = getattr(function, "id", None) or getattr(
                    function, "attr", None
                )
                assert called_name not in FORBIDDEN_CALLS, (
                    f"{module_name} performs I/O via {called_name}()"
                )


def test_rule_comparison_does_not_duplicate_registry_authority_types() -> None:
    tree = _module_tree("rule_evaluation.py")
    defined_classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    imported_symbols = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for authority_type in REGISTRY_AUTHORITY_TYPES:
        assert authority_type not in defined_classes
        assert authority_type not in imported_symbols


def test_readiness_does_not_promote_raw_comparison_results() -> None:
    imported = _imported_names(_module_tree("readiness.py"))
    assert "app.domain.rule_evaluation" not in imported
