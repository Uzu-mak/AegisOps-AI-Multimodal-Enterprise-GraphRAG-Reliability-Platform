"""The readiness probe must expect the newest migration, or /ready reports 503 after every upgrade."""
import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _revisions():
    out = {}
    for f in VERSIONS.glob("*.py"):
        values = {}
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"} and isinstance(node.value, ast.Constant):
                    values[target.id] = node.value.value
        if "revision" in values:
            out[values["revision"]] = values.get("down_revision")
    return out


def test_ready_expects_the_alembic_head():
    revs = _revisions()
    heads = set(revs) - {d for d in revs.values() if d}
    assert len(heads) == 1, heads
    source = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert f'EXPECTED_SCHEMA_REVISION = "{heads.pop()}"' in source
