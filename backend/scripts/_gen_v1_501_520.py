"""v1-501..520 из seeds_v1_501_520.json (40 строк: chat+voice). --rewrite удаляет 501-520 и пишет заново."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SEEDS = BACKEND / "tests" / "clinical" / "seeds_v1_501_520.json"
CASES = BACKEND / "tests" / "clinical" / "cases_clinical_v1.jsonl"


def _num_from_id(case_id: str) -> int | None:
    if not case_id.startswith("v1-"):
        return None
    p = case_id.split("-")
    if len(p) < 2 or not p[1].isdigit():
        return None
    return int(p[1], 10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewrite", action="store_true", help="Удалить 501-520 и записать снова.")
    args = ap.parse_args()

    raw = json.loads(SEEDS.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != 20:
        print("seeds: need list of 20", file=sys.stderr)
        return 1

    lines = [ln for ln in CASES.read_text(encoding="utf-8").splitlines() if ln.strip()]

    if not args.rewrite:
        for ln in lines:
            if json.loads(ln).get("id") == "v1-501-chat":
                print("v1-501-chat exists; no-op (use --rewrite)")
                return 0
    else:
        lines = [ln for ln in lines if not (501 <= (_num_from_id(str(json.loads(ln).get("id") or "")) or 0) <= 520)]
        print("rewrite: dropped v1-501..v1-520 if any")

    out: list[str] = []
    for i, spec in enumerate(raw):
        n = 501 + i
        if not isinstance(spec, dict) or "turns" not in spec:
            print("bad spec", i, file=sys.stderr)
            return 1
        turns = [str(t).strip() for t in (spec.get("turns") or []) if str(t).strip()]
        for channel, suf in (("chat", "chat"), ("voice-structured", "voice")):
            row: dict = {
                "id": f"v1-{n:03d}-{suf}",
                "channel": channel,
                "user_id": f"clinical-v1-{n:03d}-{suf}",
                "turns": turns,
            }
            ex = spec.get("expect")
            if isinstance(ex, dict) and ex:
                row["expect"] = ex
            for t in spec.get("tags") or []:
                if t:
                    row.setdefault("tags", []).append(t)
            out.append(json.dumps(row, ensure_ascii=False))

    CASES.write_text("\n".join(lines) + "\n" + "\n".join(out) + "\n", encoding="utf-8")
    print(f"Appended {len(out)} lines; total {len(lines) + len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
