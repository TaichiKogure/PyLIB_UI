"""Explicit download of the original Chen dataset with server checksum verification."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "data" / "reference" / "chen2020"
    output.mkdir(parents=True, exist_ok=True)
    with urlopen("https://zenodo.org/api/records/4032561", timeout=30) as response:
        record = json.load(response)
    entry = next(f for f in record["files"] if f["key"] == "LGM50_cell03.csv")
    with urlopen(entry["links"]["self"], timeout=30) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) != entry["size"] or hashlib.md5(raw).hexdigest() != entry["checksum"].removeprefix("md5:"):
        raise ValueError("Original length/checksum mismatch")
    (output / entry["key"]).write_bytes(raw)
    manifest = {"record": "https://zenodo.org/records/4032561", "file": entry["key"],
                "download_url": entry["links"]["self"], "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "title": record["metadata"]["title"], "creators": record["metadata"].get("creators"),
                "license": record["metadata"].get("license"), "upstream_checksum": entry["checksum"],
                "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
                "conditions": "LG M50 cell03; original columns and row order retained; not a target end-face-collection cell validation"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    print(raw[:500].decode("utf-8-sig"))


if __name__ == "__main__":
    main()
