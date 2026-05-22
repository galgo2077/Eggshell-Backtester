#!/usr/bin/env python3
"""
Auto-updates docs/estructura.mmd AND docs/analysis.md.

estructura.mmd
  · Updates 'Last updated' date
  · Inserts new .py modules discovered in src/ into the correct subgraph
  · Emits the diagram to stdout when new modules are added

analysis.md
  · Appends a skeleton section (what/how/why as TODO + AST structure) for
    each new .py file not yet documented
  · Re-generates ONLY the '**Structure:**' and '**Key imports:**' block for
    the file that was just written via Write/Edit — preserves hand-written
    What/How/Why text

Triggered by the PostToolUse hook configured in .claude/settings.json.
Skips silently when the triggering file was estructura.mmd itself (no loop).
"""
import ast
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
SRC      = ROOT / "src"
OUT      = ROOT / "docs" / "estructura.mmd"
ANALYSIS = ROOT / "docs" / "analysis.md"

# ── Subgraph assignment (most-specific prefix first) ──────────────────────────
_GROUPS = [
    ("strategies/Strategies-eggshell/", "SUBREPO"),
    ("strategies/",                      "STRAT"),
    ("binance_service/",                 "DATA"),
    ("core/",                            "CORE"),
    ("ui/",                              "UI"),
]

# ── stdlib top-level names to ignore for import extraction ───────────────────
_STDLIB = {
    "os", "sys", "re", "ast", "json", "datetime", "pathlib", "typing",
    "collections", "functools", "itertools", "threading", "concurrent",
    "importlib", "traceback", "math", "random", "io", "abc", "copy",
    "contextlib", "dataclasses", "enum", "warnings", "time", "string",
    "subprocess", "shutil", "hashlib", "base64", "struct", "array",
    "decimal", "fractions", "statistics", "operator", "inspect", "types",
}


# ══════════════════════════════════════════════════════════════════════════════
# estructura.mmd helpers
# ══════════════════════════════════════════════════════════════════════════════

def node_id(rel: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", rel).strip("_")


def subgraph_for(rel: str) -> str | None:
    for prefix, sg in _GROUPS:
        if rel.startswith(prefix):
            return sg
    return None


def scan_py_files() -> set[str]:
    """All .py files under SRC, relative posix paths.
    Excludes __pycache__ and __init__.py (except strategies/__init__.py)."""
    result = set()
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(SRC).as_posix()
        if p.name == "__init__.py" and rel != "strategies/__init__.py":
            continue
        result.add(rel)
    return result


def covered_paths(lines: list[str]) -> set[str]:
    """Extract .py path tokens already present in any node label.
    Only the literal token from the label (not bare filenames) to avoid
    false-positive matches (e.g. 'strategy.py' covering unrelated files)."""
    pattern = re.compile(r'^\s+\w+\["([^"]+)"\]')
    paths: set[str] = set()
    for line in lines:
        m = pattern.match(line)
        if m:
            for token in re.split(r"[\s·\|]+", m.group(1)):
                if token.endswith(".py"):
                    paths.add(token)
    return paths


def insert_before_end(lines: list[str], sg: str, node_line: str) -> bool:
    in_sg = False
    for i, line in enumerate(lines):
        if re.match(rf"\s*subgraph {sg}\b", line):
            in_sg = True
        if in_sg and line.strip() == "end":
            lines.insert(i, node_line)
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# analysis.md helpers
# ══════════════════════════════════════════════════════════════════════════════

def extract_structure(path: Path) -> dict:
    """AST-extract classes (with public methods) and top-level functions
    plus third-party imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"classes": [], "functions": [], "imports": []}

    classes: list[dict] = []
    functions: list[str] = []
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0]
            if top and top not in _STDLIB:
                imports.add(mod or "(relative)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _STDLIB:
                    imports.add(alias.name)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            methods: list[str] = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not child.name.startswith("__") or child.name == "__init__":
                        args = [a.arg for a in child.args.args if a.arg != "self"]
                        methods.append(f"`{child.name}({', '.join(args)})`")
            classes.append({"name": node.name, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                args = [a.arg for a in node.args.args]
                functions.append(f"`{node.name}({', '.join(args)})`")

    return {"classes": classes, "functions": functions, "imports": sorted(imports)}


def render_structure_block(s: dict) -> str:
    """Render the **Structure:** ... **Key imports:** markdown block."""
    lines = ["**Structure:**"]
    for cls in s["classes"]:
        lines.append(f"- `{cls['name']}`")
        for m in cls["methods"]:
            lines.append(f"  - {m}")
    for fn in s["functions"]:
        lines.append(f"- {fn}")
    if not s["classes"] and not s["functions"]:
        lines.append("- _(no public classes or functions)_")
    lines.append("")
    if s["imports"]:
        imp_str = "`, `".join(s["imports"][:10])
        lines.append(f"**Key imports:** `{imp_str}`")
    return "\n".join(lines)


def make_skeleton(rel: str, path: Path) -> str:
    s = extract_structure(path) if path.exists() else {}
    block = render_structure_block(s) if s else "**Structure:** _(could not parse)_"
    return (
        f"\n---\n\n"
        f"## `{rel}`\n\n"
        f"**What:** _(auto-generated — describe what this module does)_\n\n"
        f"**How:** _(describe the implementation approach)_\n\n"
        f"**Why:** _(describe design rationale and constraints)_\n\n"
        f"{block}\n"
    )


def refresh_structure_in_section(content: str, rel: str, path: Path) -> str:
    """Re-generate Structure + Key imports block for an existing section.
    Splits on '\\n---\\n' separators, finds the matching section, replaces
    from '**Structure:**' onward — preserving What/How/Why text."""
    header = f"## `{rel}`"
    if header not in content:
        return content

    s = extract_structure(path)
    new_block = render_structure_block(s)

    parts = content.split("\n---\n")
    rebuilt = []
    for part in parts:
        if header in part:
            idx = part.find("**Structure:**")
            if idx >= 0:
                part = part[:idx] + new_block
        rebuilt.append(part)
    return "\n---\n".join(rebuilt)


def update_analysis(new_files: list[str], changed_file: str):
    """Append skeletons for new files; refresh Structure for the changed file."""
    if not ANALYSIS.exists():
        return

    content = ANALYSIS.read_text(encoding="utf-8")
    changed = False

    for rel in new_files:
        if f"## `{rel}`" not in content:
            path = SRC / rel
            content += make_skeleton(rel, path)
            changed = True
            print(f"  [analysis] skeleton added: {rel}", file=sys.stderr)

    # Re-generate Structure section for the file that was just written
    if changed_file and changed_file.endswith(".py"):
        try:
            cf = Path(changed_file)
            rel = cf.relative_to(SRC).as_posix()
        except ValueError:
            rel = None
        if rel and f"## `{rel}`" in content:
            updated = refresh_structure_in_section(content, rel, SRC / rel)
            if updated != content:
                content = updated
                changed = True
                print(f"  [analysis] structure refreshed: {rel}", file=sys.stderr)

    if changed:
        ANALYSIS.write_text(content, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    # ── Guard: don't loop when we triggered by editing docs files ─────────────
    tool_input   = json.loads(os.environ.get("CLAUDE_TOOL_INPUT", "{}"))
    changed_file = tool_input.get("file_path", "")
    if any(x in changed_file for x in ("estructura.mmd", "analysis.md", "docker.mmd")):
        return 0

    if not OUT.exists():
        print("[gen_estructura] docs/estructura.mmd not found — skipping.", file=sys.stderr)
        return 0

    lines = OUT.read_text().splitlines()
    today = str(date.today())

    # ── 1. Update date ─────────────────────────────────────────────────────────
    lines = [
        f"%% Last updated: {today}" if ln.startswith("%% Last updated:") else ln
        for ln in lines
    ]

    # ── 2. Detect new Python files for estructura.mmd ─────────────────────────
    already_covered = covered_paths(lines)
    added: list[str] = []

    for rel in sorted(scan_py_files()):
        parts = Path(rel).parts
        suffixes = {rel}
        for i in range(1, len(parts)):
            suffixes.add("/".join(parts[i:]))

        if suffixes & already_covered:
            continue

        nid = node_id(rel)
        node_line = f'    {nid}["{rel}"]'
        sg = subgraph_for(rel)

        if sg:
            if insert_before_end(lines, sg, node_line):
                added.append(rel)
                print(f"  [+] {nid}  →  subgraph {sg}", file=sys.stderr)
        else:
            for i, ln in enumerate(lines):
                if 'MAIN["' in ln:
                    lines.insert(i + 1, node_line)
                    added.append(rel)
                    print(f"  [+] {nid}  →  top-level", file=sys.stderr)
                    break

    # ── 3. Write estructura.mmd ────────────────────────────────────────────────
    OUT.write_text("\n".join(lines) + "\n")

    # ── 4. Update analysis.md ─────────────────────────────────────────────────
    update_analysis(added, changed_file)

    # ── 5. Report ─────────────────────────────────────────────────────────────
    if added:
        print(
            f"\n[gen_estructura] {today} — {len(added)} new module(s): "
            + ", ".join(added),
            file=sys.stderr,
        )
        print(OUT.read_text())
    else:
        print(f"[gen_estructura] {today} — docs are current.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
