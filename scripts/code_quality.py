#!/usr/bin/env python3
"""Метрики качества кода: где он расползается и где его не проверяет ни один тест.

Зачем это нужно именно здесь. Значительная часть кода в проекте написана
языковой моделью, а сгенерированный код читается ровно так же убедительно,
когда он верный и когда он неверный: те же аккуратные имена, те же ровные
комментарии. Стилевые линтеры этой разницы не видят. Видят две вещи:

  * размер и связность — раздутая функция и дубль показывают, где модель
    дописывала рядом вместо того, чтобы использовать существующее;
  * тесты — единственная метрика, которая проверяет поведение, а не форму.

Поэтому отчёт устроен так: сначала объём и сложность, потом дублирование,
потом покрытие тестами по слоям — и отдельно расчётный слой, где ошибка не
падает, а тихо искажает цифры.

Скрипт ничего не меняет и ни от чего не зависит, кроме стандартной библиотеки.
Покрытие подхватывается из coverage.json, если он есть.

Запуск из корня репозитория:
  python3 scripts/code_quality.py
  python3 scripts/code_quality.py --out docs/CODE-QUALITY.md
  python3 scripts/code_quality.py --strict          # ненулевой код при нарушениях

Как получить свежее покрытие (из backend):
  venv/bin/python -m pytest --cov=app --cov-report=json:../coverage.json -q
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]

# Пороги. Не догма: это границы, за которыми файл перестаёт помещаться в голову
# целиком, а значит его правят вслепую — и человек, и модель.
MAX_FILE_LINES = 500
MAX_FUNC_LINES = 60
MAX_COMPLEXITY = 12
MIN_DUP_BLOCK = 6          # длина совпадающего куска, с которой это уже дубль
CRITICAL_COVERAGE = 90     # расчётный слой: считает деньги, должен быть покрыт
OVERALL_COVERAGE = 60      # весь backend, включая роутеры и интеграции

# Слои, где ошибка не падает, а молча искажает результат.
CRITICAL_PREFIXES = ("app/services/analysis/", "app/utils/currency_converter.py")

SKIP_DIRS = {
    "node_modules", "venv", ".git", "__pycache__", "build", "dist",
    ".pytest_cache", "alembic",
}


# ─── Общие утилиты ───────────────────────────────────────────────────────────


def iter_files(*suffixes: str) -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def is_test(path: Path) -> bool:
    name = path.name
    return "test" in name or "tests" in path.parts


@dataclass
class FunctionInfo:
    file: str
    name: str
    line: int
    length: int
    complexity: int


@dataclass
class Findings:
    """Всё, что скрипт нашёл, в одном месте — чтобы отчёт только форматировал."""
    py_files: List[Tuple[str, int]] = field(default_factory=list)
    ts_files: List[Tuple[str, int]] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    duplicates: List[Tuple[int, List[str]]] = field(default_factory=list)
    type_ignores: int = 0
    any_casts: int = 0
    comment_ratio: float = 0.0
    tests: int = 0
    asserts: int = 0
    coverage: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # файл → (покрыто, всего)
    untested_modules: List[str] = field(default_factory=list)
    layering: List[str] = field(default_factory=list)


# ─── Python: размер, сложность ───────────────────────────────────────────────


_DECISION_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.IfExp, ast.Assert, ast.comprehension,
)


def complexity_of(node: ast.AST) -> int:
    """Цикломатическая сложность: единица плюс каждая точка ветвления."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _DECISION_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


def scan_python(findings: Findings) -> None:
    comment_lines = code_lines = 0
    for path in iter_files(".py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        findings.py_files.append((rel(path), len(lines)))
        findings.type_ignores += text.count("# type: ignore")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                comment_lines += 1
            else:
                code_lines += 1

        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        # Docstring — тоже документация: в этом проекте объяснения живут в них,
        # а не в решётках, и без их учёта доля «комментариев» выходит вчетверо ниже.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    doc_lines = len(doc.splitlines())
                    comment_lines += doc_lines
                    code_lines -= doc_lines

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                findings.functions.append(
                    FunctionInfo(
                        file=rel(path),
                        name=node.name,
                        line=node.lineno,
                        length=end - node.lineno + 1,
                        complexity=complexity_of(node),
                    )
                )
            if is_test(path) and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test"):
                    findings.tests += 1
            if is_test(path) and isinstance(node, ast.Assert):
                findings.asserts += 1

    total = comment_lines + code_lines
    findings.comment_ratio = comment_lines / total if total else 0.0


# ─── TypeScript: размер, сложность (эвристика по скобкам) ────────────────────


_TS_FUNC = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+(?P<fn>\w+)|const\s+(?P<const>\w+)\s*[:=].*?(?:=>|function))"
)
_TS_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?\?|\?[^.:]")


def scan_typescript(findings: Findings) -> None:
    for path in iter_files(".ts", ".tsx"):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        findings.ts_files.append((rel(path), len(lines)))
        findings.any_casts += sum(
            1 for line in lines if re.search(r":\s*any\b|as any\b", line)
        )

        # Функция считается открытой, пока не закроются её фигурные скобки.
        open_fn: Optional[Tuple[str, int, int]] = None  # имя, строка, глубина
        depth = 0
        decisions = 0
        for i, line in enumerate(lines, start=1):
            match = _TS_FUNC.match(line)
            if match and open_fn is None:
                name = match.group("fn") or match.group("const") or "?"
                open_fn = (name, i, depth)
                decisions = 0
            if open_fn is not None:
                decisions += len(_TS_DECISION.findall(line))
            depth += line.count("{") - line.count("}")
            if open_fn is not None and depth <= open_fn[2] and i > open_fn[1]:
                name, start, _ = open_fn
                findings.functions.append(
                    FunctionInfo(
                        file=rel(path), name=name, line=start,
                        length=i - start + 1, complexity=decisions + 1,
                    )
                )
                open_fn = None


# ─── Дублирование ────────────────────────────────────────────────────────────


def normalize(line: str) -> str:
    line = re.sub(r"//.*|#.*", "", line)
    return re.sub(r"\s+", " ", line).strip()


_BORING = re.compile(r"^(import|from|export|\}|\)|\]|</|\{|<|else|try:|\"\"\")")


def _worth_reporting(chunk: Sequence[str]) -> bool:
    """Отсечь совпадения из импортов и закрывающих скобок — это не дубль логики."""
    return sum(1 for line in chunk if not _BORING.match(line)) >= MIN_DUP_BLOCK - 1


def scan_duplicates(findings: Findings) -> None:
    """Одинаковые куски ≥ MIN_DUP_BLOCK строк в разных местах.

    Дубли — главный след генерации: модель охотнее напишет форматтер заново,
    чем найдёт существующий, потому что чужой файл ей не виден.

    Соседние совпадения склеиваются в один блок: без этого дубль на 20 строк
    отчитывается пятнадцатью «находками» и топит собой всё остальное.
    """
    # файл → [(номер строки, нормализованная строка)] только значащих строк
    files: Dict[str, List[Tuple[int, str]]] = {}
    for path in iter_files(".py", ".ts", ".tsx"):
        if is_test(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        files[rel(path)] = [
            (i, normalize(l)) for i, l in enumerate(lines, start=1) if len(normalize(l)) > 3
        ]

    windows: Dict[Tuple[str, ...], List[Tuple[str, int]]] = defaultdict(list)
    for name, entries in files.items():
        for start in range(len(entries) - MIN_DUP_BLOCK + 1):
            key = tuple(l for _, l in entries[start:start + MIN_DUP_BLOCK])
            windows[key].append((name, start))

    claimed: set[Tuple[str, int]] = set()
    groups: List[Tuple[int, List[str]]] = []
    for key, locations in windows.items():
        if len(locations) < 2 or not _worth_reporting(key):
            continue
        if any(loc in claimed for loc in locations):
            continue

        # Растягиваем блок, пока следующая строка совпадает во всех копиях.
        length = MIN_DUP_BLOCK
        while True:
            nxt = {
                files[name][start + length][1]
                for name, start in locations
                if start + length < len(files[name])
            }
            if len(nxt) != 1 or len(locations) != sum(
                1 for name, start in locations if start + length < len(files[name])
            ):
                break
            length += 1

        for name, start in locations:
            for offset in range(length):
                claimed.add((name, start + offset))
        groups.append((
            length,
            [f"{name}:{files[name][start][0]}" for name, start in locations],
        ))

    groups.sort(key=lambda g: (-g[0], -len(g[1])))
    findings.duplicates = groups


# ─── Тесты и покрытие ────────────────────────────────────────────────────────


# ─── Расслоение: что где лежит ───────────────────────────────────────────────


# Правило про sys.path касается кода приложения и его тестов: самостоятельные
# скрипты в scripts/ и tools/ запускаются напрямую и добавляют backend в путь
# законно. Внутри приложения точка одна — обёртка над каталогом скрапера
# (дефис в имени не даёт сделать из него пакет).
_SYS_PATH_SCOPE = ("backend/app/", "backend/tests/")
_SYS_PATH_ALLOWED = ("app/services/disclosure/edisclosure_client.py",)

# Заглушки не должны попадать в рабочие слои: mock-данные уже один раз
# доехали до публичного роутера и отдавались как настоящие.
_MOCK_IMPORT = re.compile(r"^\s*from\s+app\.[\w.]*(mock|fixture)[\w.]*\s+import|^\s*import\s+app\.[\w.]*mock")


def scan_layering(findings: Findings) -> None:
    """Нарушения размещения: хаки путей, заглушки в проде, дубли хелперов."""
    for path in iter_files(".py"):
        name = rel(path)
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "sys.path.insert" in line or "sys.path.append" in line:
                in_scope = any(name.startswith(s) for s in _SYS_PATH_SCOPE)
                if in_scope and not any(name.endswith(a) for a in _SYS_PATH_ALLOWED):
                    findings.layering.append(
                        f"`{name}:{i}` правит sys.path в обход "
                        f"`ensure_scraper_importable` — путь начнёт зависеть от каталога запуска"
                    )
            if _MOCK_IMPORT.match(line) and "/tests/" not in name:
                findings.layering.append(f"`{name}:{i}` тянет заглушки в рабочий код")

    # Одноимённые локальные хелперы в разных файлах фронтенда — след того, что
    # функцию написали заново вместо импорта (так разошлись четыре fmtMln).
    helpers: Dict[str, List[str]] = defaultdict(list)
    helper_def = re.compile(r"^\s*(?:const|function)\s+(fmt\w*|format\w*)\s*[=(]")
    for path in iter_files(".ts", ".tsx"):
        if is_test(path) or "/utils/" in rel(path):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = helper_def.match(line)
            if not match:
                continue
            # Однострочная обёртка над общим утилем — не дубль, а локальная
            # подстановка валюты: `const fmtMln = (n) => formatMln(n, cur)`.
            if re.search(r"=>\s*format\w*\(", line) or "return format" in line:
                continue
            helpers[match.group(1)].append(f"{rel(path)}:{i}")
    for helper, locations in sorted(helpers.items()):
        if len(locations) > 1:
            findings.layering.append(
                f"`{helper}` объявлен в {len(locations)} местах вместо общего утиля: "
                + ", ".join(f"`{loc}`" for loc in locations[:4])
            )


def load_coverage(findings: Findings, coverage_path: Path) -> None:
    if not coverage_path.exists():
        return
    data = json.loads(coverage_path.read_text(encoding="utf-8"))
    for filename, payload in data.get("files", {}).items():
        summary = payload.get("summary", {})
        covered = summary.get("covered_lines", 0)
        total = summary.get("num_statements", 0)
        findings.coverage[filename.replace("\\", "/")] = (covered, total)


def coverage_for(findings: Findings, prefixes: Sequence[str]) -> Optional[float]:
    covered = total = 0
    for name, (cov, tot) in findings.coverage.items():
        if any(name.startswith(p) for p in prefixes):
            covered += cov
            total += tot
    return covered / total * 100 if total else None


def find_untested_modules(findings: Findings) -> None:
    """Модули сервисного слоя, где не выполнилось ни строки при прогоне тестов."""
    for name, (covered, total) in sorted(findings.coverage.items()):
        if not name.startswith("app/services/") or total == 0:
            continue
        if covered == 0:
            findings.untested_modules.append(name)


# ─── Отчёт ───────────────────────────────────────────────────────────────────


def table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def verdict(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def build_report(findings: Findings) -> Tuple[List[str], List[str]]:
    violations: List[str] = []
    lines: List[str] = ["# Метрики качества кода", ""]

    py_total = sum(n for _, n in findings.py_files)
    ts_total = sum(n for _, n in findings.ts_files)
    big_py = [(f, n) for f, n in findings.py_files if n > MAX_FILE_LINES and "test" not in f]
    big_ts = [(f, n) for f, n in findings.ts_files if n > MAX_FILE_LINES]
    long_fns = sorted(
        [f for f in findings.functions if f.length > MAX_FUNC_LINES],
        key=lambda f: -f.length,
    )
    complex_fns = sorted(
        [f for f in findings.functions if f.complexity > MAX_COMPLEXITY],
        key=lambda f: -f.complexity,
    )
    critical_cov = coverage_for(findings, CRITICAL_PREFIXES)
    overall_cov = coverage_for(findings, ("app/",))

    # ─── Сводка ───
    summary_rows = [
        ["Строк Python / TypeScript", f"{py_total} / {ts_total}", "—", "—"],
        [
            "Файлов длиннее порога",
            f"{len(big_py) + len(big_ts)}",
            f"≤ {MAX_FILE_LINES} строк",
            verdict(not big_py and not big_ts),
        ],
        [
            "Функций длиннее порога",
            f"{len(long_fns)}",
            f"≤ {MAX_FUNC_LINES} строк",
            verdict(not long_fns),
        ],
        [
            "Функций сложнее порога",
            f"{len(complex_fns)}",
            f"≤ {MAX_COMPLEXITY} ветвлений",
            verdict(not complex_fns),
        ],
        [
            "Дублирующихся блоков",
            f"{len(findings.duplicates)}",
            f"≥ {MIN_DUP_BLOCK} строк подряд",
            verdict(not findings.duplicates),
        ],
        [
            "Нарушений расслоения",
            f"{len(findings.layering)}",
            "0",
            verdict(not findings.layering),
        ],
        ["Тестов / assert'ов", f"{findings.tests} / {findings.asserts}", "—", "—"],
        [
            "Assert на тест",
            f"{findings.asserts / findings.tests:.1f}" if findings.tests else "—",
            "≥ 1.5",
            verdict(bool(findings.tests) and findings.asserts / findings.tests >= 1.5),
        ],
        [
            "Покрытие расчётного слоя",
            f"{critical_cov:.0f}%" if critical_cov is not None else "нет данных",
            f"≥ {CRITICAL_COVERAGE}%",
            verdict(critical_cov is not None and critical_cov >= CRITICAL_COVERAGE),
        ],
        [
            "Покрытие backend целиком",
            f"{overall_cov:.0f}%" if overall_cov is not None else "нет данных",
            f"≥ {OVERALL_COVERAGE}%",
            verdict(overall_cov is not None and overall_cov >= OVERALL_COVERAGE),
        ],
        ["Доля строк-комментариев", f"{findings.comment_ratio:.0%}", "10–25%", "—"],
        ["`# type: ignore` / `any`", f"{findings.type_ignores} / {findings.any_casts}", "—", "—"],
    ]
    lines += table(summary_rows, ["Метрика", "Значение", "Порог", ""]) + [""]

    if big_py or big_ts:
        violations.append(f"файлов длиннее {MAX_FILE_LINES} строк: {len(big_py) + len(big_ts)}")
        lines += ["## Файлы, которые не помещаются в голову", ""]
        lines += table(
            [[f"`{f}`", str(n)] for f, n in sorted(big_py + big_ts, key=lambda x: -x[1])[:15]],
            ["Файл", "Строк"],
        ) + [""]

    if long_fns:
        violations.append(f"функций длиннее {MAX_FUNC_LINES} строк: {len(long_fns)}")
        lines += ["## Длинные функции", ""]
        lines += table(
            [[f"`{f.file}:{f.line}`", f.name, str(f.length), str(f.complexity)] for f in long_fns[:15]],
            ["Место", "Функция", "Строк", "Ветвлений"],
        ) + [""]

    if complex_fns:
        violations.append(f"функций сложнее {MAX_COMPLEXITY}: {len(complex_fns)}")
        lines += ["## Ветвистые функции", ""]
        lines += table(
            [[f"`{f.file}:{f.line}`", f.name, str(f.complexity), str(f.length)] for f in complex_fns[:15]],
            ["Место", "Функция", "Ветвлений", "Строк"],
        ) + [""]

    if findings.duplicates:
        violations.append(f"дублирующихся блоков: {len(findings.duplicates)}")
        lines += ["## Дублирование", "", "Одинаковые куски кода в разных местах:", ""]
        for size, locations in findings.duplicates[:10]:
            lines.append(f"- {size} строк × {len(locations)}: " + ", ".join(f"`{l}`" for l in locations[:4]))
        lines.append("")

    if findings.layering:
        violations.append(f"нарушений расслоения: {len(findings.layering)}")
        lines += [
            "## Что лежит не на своём месте",
            "",
            "Заглушки в рабочем коде, правка `sys.path` мимо общей точки и",
            "одноимённые хелперы, написанные заново вместо импорта.",
            "",
        ]
        lines += [f"- {item}" for item in findings.layering] + [""]

    if findings.untested_modules:
        lines += [
            "## Сервисы, где тесты не выполнили ни строки",
            "",
            "Не «мало покрытия», а ноль: поведение этих модулей ничем не зафиксировано.",
            "",
        ]
        lines += [f"- `{name}`" for name in findings.untested_modules] + [""]

    if critical_cov is not None and critical_cov < CRITICAL_COVERAGE:
        violations.append(f"покрытие расчётного слоя {critical_cov:.0f}% < {CRITICAL_COVERAGE}%")
    if overall_cov is not None and overall_cov < OVERALL_COVERAGE:
        violations.append(f"покрытие backend {overall_cov:.0f}% < {OVERALL_COVERAGE}%")

    lines += [
        "## Как читать",
        "",
        "Длина и ветвистость показывают, где код правят вслепую. Дубли — где вместо",
        "существующей функции написали новую рядом. Покрытие расчётного слоя —",
        "единственная метрика про поведение: остальные проверяют форму, а форма у",
        "сгенерированного кода хороша всегда, в том числе когда он считает неверно.",
        "",
    ]
    return lines, violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="записать отчёт в markdown-файл")
    parser.add_argument(
        "--coverage",
        default=str(ROOT / "coverage.json"),
        help="путь к coverage.json (pytest --cov-report=json)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="вернуть код 1, если хоть один порог нарушен (для CI)",
    )
    args = parser.parse_args()

    findings = Findings()
    scan_python(findings)
    scan_typescript(findings)
    scan_duplicates(findings)
    scan_layering(findings)
    load_coverage(findings, Path(args.coverage))
    find_untested_modules(findings)

    lines, violations = build_report(findings)
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n→ {args.out}", file=sys.stderr)

    if violations:
        print("Нарушены пороги: " + "; ".join(violations), file=sys.stderr)
    return 1 if (violations and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
