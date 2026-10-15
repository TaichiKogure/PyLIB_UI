"""Copy auditable baseline evidence and installed license notices (no binaries)."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "docs" / "evidence" / "step01"
    output.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "data" / "reference" / "baseline"
    for source in baseline.glob("*"):
        if source.suffix in {".csv", ".json"}:
            shutil.copyfile(source, output / source.name)
    shutil.copyfile(ROOT / "data" / "reference" / "chen2020" / "manifest.json", output / "chen2020-manifest.json")
    ledger = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name.lower() == "pip":
            continue
        files = []
        for file in dist.files or []:
            if ".dist-info/" not in str(file) or not any(
                    word in file.name.upper() for word in ("LICENSE", "COPYING", "NOTICE")):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file():
                continue
            raw = source.read_bytes()
            # Flatten path with a digest to retain multiple notices without collisions.
            target = output / "licenses" / name / (
                        hashlib.sha256(str(file).encode()).hexdigest()[:10] + "-" + source.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            files.append(
                {"path": str(target.relative_to(output)).replace("\\", "/"), "sha256": hashlib.sha256(raw).hexdigest()})
        ledger.append({"name": name, "version": dist.version, "requires_python": dist.metadata.get("Requires-Python"),
                       "license_expression": dist.metadata.get("License-Expression"),
                       "license_metadata": dist.metadata.get("License"),
                       "license_classifiers": [c for c in dist.metadata.get_all("Classifier", []) if
                                               c.startswith("License")],
                       "project_urls": dist.metadata.get_all("Project-URL", []), "notices": files})
    (output / "oss-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    repro = ROOT / ".test_tmp" / "repro-baseline" / "spme_chen.csv"
    baseline_csv = baseline / "spme_chen.csv"
    if repro.exists():
        (output / "reproduction.json").write_text(json.dumps({
            "runtime": "CPython 3.13.2 / Windows AMD64",
            "setup": "fresh .test_tmp/research-repro venv; pip install -r requirements-research.lock.txt; pip check passed",
            "case": "spme_chen", "identical_csv_bytes": repro.read_bytes() == baseline_csv.read_bytes(),
            "sha256": hashlib.sha256(baseline_csv.read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    print(f"Evidence: {output}; {len(ledger)} dependencies")


if __name__ == "__main__":
    main()
