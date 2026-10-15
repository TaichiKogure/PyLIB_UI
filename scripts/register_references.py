"""Explicitly register downloaded original and solved baselines into a chosen local DB."""
import argparse
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylib_ui.datasets import import_curve
from pylib_ui.storage import RunRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    repository = RunRepository(args.data_dir / "runs.sqlite3")
    project = repository.create_project("Chen2020と数値基準ケース")
    source_dir = ROOT / "data" / "reference" / "chen2020"
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    request = {"project_id": project["id"], "filename": manifest["file"], "header_row": 14,
               "content_base64": base64.b64encode((source_dir / manifest["file"]).read_bytes()).decode(),
               "name": "Chen2020 LG M50 cell03 公開実測", "source_type": "public_measured",
               "source": manifest["record"], "license": "CC BY 4.0; Chen et al. (2020), DOI:10.1149/1945-7111/ab9050",
               "notes": "原条件の公開実測。セル表面温度と雰囲気は別列。Md=C/D/Rで符号を確定。対象の全面集電セルの実測ではない。",
               "specimen_id": "LG M50 cell03", "temperature_position": "cell thermocouple; original channel",
               "current_sign": "direction_column", "rest_value": "R|O|SBr", "shape": "time_series", "mode": "mixed",
               "mapping": {
                   "time_s": {"column": "Test Time [s]", "unit": "s"},
                   "voltage_v": {"column": "Voltage [V]", "unit": "V"},
                   "current_a": {"column": "Current [A]", "unit": "A"},
                   "temperature_c": {"column": "Temperature Cell [degC]", "unit": "degC"},
                   "step": {"column": "Step"}, "direction": {"column": "Md"}}}
    record, raw = import_curve(request)
    repository.save(record, raw)
    print(f'public_measured: {len(record["points"])} points, {record["quality"]["segment_count"]} segments')
    baseline = ROOT / "data" / "reference" / "baseline"
    for path in sorted(baseline.glob("*.csv")):
        evidence = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if not evidence["enabled"]:
            continue
        record, raw = import_curve({"project_id": project["id"], "text": path.read_text(encoding="utf-8"),
                                    "name": f'数値基準 {path.stem}', "source_type": "synthetic_demo", "mode": "mixed",
                                    "source": f'PyBaMM 26.10.1.0 / {evidence["parameter_set"]}; DOI:10.1149/1945-7111/ab9050',
                                    "notes": json.dumps(evidence, ensure_ascii=False), "filename": path.name,
                                    "mapping": {"time_s": {"column": "time_s", "unit": "s"},
                                                "voltage_v": {"column": "voltage_v", "unit": "V"},
                                                "current_a": {"column": "current_a", "unit": "A"},
                                                "temperature_c": {"column": "temperature_c", "unit": "degC"}}})
        record.update(source_type="simulation", validation_status="numerical_smoke_only", baseline=evidence,
                      limitations=["短時間の数値互換性確認のみ。実測との条件合わせ・誤差評価・校正は未実施。",
                                   "UIのセル設計入力で生成した結果ではありません。元の公開パラメータを使用。"])
        repository.save(record, raw)
    print(f'project: {project["id"]}; records: {len(repository.list(project["id"]))}')


if __name__ == "__main__":
    main()
