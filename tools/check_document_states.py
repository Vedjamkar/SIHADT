"""Check that backend enums and published mock fixtures cover every UI state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verdict import Binding, Verdict  # noqa: E402


def main() -> int:
    fixture_dir = ROOT / "frontend" / "public" / "fixtures"
    index = json.loads((fixture_dir / "index.json").read_text(encoding="utf-8"))
    verdicts = {item["verdict"] for item in index if "verdict" in item}
    bindings = {item["binding"] for item in index if "binding" in item}
    expected_verdicts = {item.value for item in Verdict}
    expected_bindings = {item.value for item in Binding}

    missing_verdicts = sorted(expected_verdicts - verdicts)
    missing_bindings = sorted(expected_bindings - bindings)
    print(f"verdicts: {len(verdicts & expected_verdicts)}/{len(expected_verdicts)}")
    print(f"bindings: {len(bindings & expected_bindings)}/{len(expected_bindings)}")
    if missing_verdicts:
        print(f"missing verdict fixtures: {', '.join(missing_verdicts)}")
    if missing_bindings:
        print(f"missing binding fixtures: {', '.join(missing_bindings)}")
    return 1 if missing_verdicts or missing_bindings else 0


if __name__ == "__main__":
    raise SystemExit(main())
