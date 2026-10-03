"""docs/bugs.md is the bug registry: every bug ever fixed has a row and at least one regression
test, and every test named there really exists - so the full suite re-checks all past bugs on
every run."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| (BUG-\d{3}) \|")


def rows():
    out = []
    for line in (ROOT / "docs" / "bugs.md").read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            out.append((m.group(1), [c.strip() for c in cells]))
    return out


def test_REG_01_every_bug_has_six_columns_and_a_unique_id_in_order():
    rs = rows()
    assert len(rs) >= 60
    ids = [i for i, _ in rs]
    assert ids == [f"BUG-{n:03d}" for n in range(1, len(ids) + 1)]
    assert all(len(cells) == 6 and all(cells) for _, cells in rs)


def test_REG_02_every_bug_names_regression_tests_that_exist():
    missing = []
    for bug, cells in rows():
        tests = re.findall(r"`(tests/[\w/]+\.py)::(\w+)`", cells[5])
        if not tests:
            missing.append(f"{bug}: no regression test")
        for path, name in tests:
            f = ROOT / path
            if not f.is_file() or not re.search(rf"^\s*def {name}\(", f.read_text(encoding="utf-8"), re.M):
                missing.append(f"{bug}: {path}::{name} not found")
    assert not missing, "\n".join(missing)
