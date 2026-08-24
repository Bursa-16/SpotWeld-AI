"""Stage 2A gatekeeper: the domain foundation stays threshold-free.

Scans the four pure-domain foundation modules for engineering-unit literals
(a number directly followed by a physical-unit token, or a bare unit token
used as a quoted string literal). The modules must carry no engineering
values whatsoever: every bound and every conversion factor arrives verbatim
from callers, and tests use synthetic arbitrary values.

Also verifies, in a fresh interpreter, that importing the foundation modules
never pulls in the quarantined prototype rule engine.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = BACKEND_ROOT / "app" / "domain"

STAGE_2A_MODULES = (
    "unit_policy.py",
    "rule_applicability.py",
    "rule_evaluation.py",
    "readiness.py",
)

_UNIT_TOKENS = (
    "kN", "kA", "mA", "kV", "mV",
    "kPa", "MPa", "GPa",
    "kg", "mg", "mL",
    "kJ", "kW", "MW",
    "\u00b5s", "\u00b5m",
    "\u00b0C", "\u00b0F", "degC", "degF",
    "mm", "ms", "ns", "psi", "bar",
)

_TOKEN_ALTERNATION = "|".join(re.escape(token) for token in _UNIT_TOKENS)

_NUMBER_THEN_UNIT = re.compile(
    rf"\d[\d_]*(?:\.\d+)?[ \t]*(?:{_TOKEN_ALTERNATION})\b"
)
_QUOTED_UNIT = re.compile(rf"[\"'](?:{_TOKEN_ALTERNATION})[\"']")


def _scan(module_name: str, pattern: re.Pattern[str]) -> list[str]:
    source = (DOMAIN_DIR / module_name).read_text(encoding="utf-8")
    hits: list[str] = []
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        hits.append(f"{module_name}:{line}: {match.group(0)!r}")
    return hits


def test_stage_2a_modules_contain_no_number_unit_literals() -> None:
    offenders = [
        hit
        for module_name in STAGE_2A_MODULES
        for hit in _scan(module_name, _NUMBER_THEN_UNIT)
    ]
    assert not offenders, (
        "engineering-unit literals found in pure-domain modules:\n"
        + "\n".join(offenders)
    )


def test_stage_2a_modules_contain_no_quoted_unit_literals() -> None:
    offenders = [
        hit
        for module_name in STAGE_2A_MODULES
        for hit in _scan(module_name, _QUOTED_UNIT)
    ]
    assert not offenders, (
        "quoted unit literals found in pure-domain modules:\n"
        + "\n".join(offenders)
    )


def test_stage_2a_modules_import_without_quarantined_prototype() -> None:
    imports = "".join(
        f"import app.domain.{module_name.removesuffix('.py')};"
        for module_name in STAGE_2A_MODULES
    )
    probe = (
        "import sys;"
        f"{imports}"
        "assert 'app.domain.rules_engine' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, (
        "quarantined prototype leaked into stage modules:\n"
        + completed.stderr
    )
