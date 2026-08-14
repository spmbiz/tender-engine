from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def compact(rec: dict, description_limit: int) -> dict:
    desc = rec.get("description") or rec.get("text") or ""
    desc = " ".join(str(desc).split())
    if len(desc) > description_limit:
        desc = desc[:description_limit] + "…"
    return {
        "candidate_id": rec.get("candidate_id") or rec.get("canonical_key"),
        "source": rec.get("source") or rec.get("portal"),
        "title": rec.get("title"),
        "buyer": rec.get("buyer"),
        "deadline": rec.get("deadline") or rec.get("closing"),
        "value": rec.get("estimated_value") or rec.get("value"),
        "currency": rec.get("currency"),
        "notice_url": rec.get("notice_url"),
        "seen_before": bool(rec.get("seen_before")),
        "description": desc,
        "route": rec.get("route") or {},
        "documents": rec.get("documents") or [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="merged/current_candidates.jsonl")
    ap.add_argument("--out", default="wide_read_packets")
    ap.add_argument("--packet-size", type=int, default=250)
    ap.add_argument("--description-limit", type=int, default=1800)
    args = ap.parse_args()

    rows = [compact(r, args.description_limit) for r in load_jsonl(Path(args.input))]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "records": len(rows),
        "packet_size": args.packet_size,
        "packet_count": 0,
        "policy": (
            "GPT must materially read every packet before selecting DCE candidates. "
            "Do not use keyword filtering to skip packets. Previously seen records remain visible "
            "but should not be re-promoted unless changed or explicitly rechecked."
        ),
        "packets": [],
    }

    for start in range(0, len(rows), args.packet_size):
        chunk = rows[start : start + args.packet_size]
        n = start // args.packet_size + 1
        stem = f"packet_{n:03d}"
        jsonl_path = out / f"{stem}.jsonl"
        md_path = out / f"{stem}.md"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for rec in chunk:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        md = [
            f"# GPT Wide Read — Packet {n}",
            "",
            "Read every candidate in this packet. High recall is intentional. Do not discard a candidate merely because its title is unusual or its CPV/keyword fit is weak.",
            "",
        ]
        for i, rec in enumerate(chunk, start=start + 1):
            md.extend(
                [
                    f"## {i}. {rec.get('title') or '(untitled)'}",
                    f"- ID: `{rec.get('candidate_id')}`",
                    f"- Source: {rec.get('source')}",
                    f"- Buyer: {rec.get('buyer')}",
                    f"- Deadline: {rec.get('deadline')}",
                    f"- Value: {rec.get('value')} {rec.get('currency') or ''}",
                    f"- Seen before: {rec.get('seen_before')}",
                    f"- URL: {rec.get('notice_url')}",
                    "",
                    rec.get("description") or "(no description materialized)",
                    "",
                ]
            )
        md_path.write_text("\n".join(md), encoding="utf-8")
        manifest["packets"].append(
            {"packet": n, "start": start + 1, "end": start + len(chunk), "records": len(chunk), "jsonl": jsonl_path.name, "markdown": md_path.name}
        )

    manifest["packet_count"] = len(manifest["packets"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
