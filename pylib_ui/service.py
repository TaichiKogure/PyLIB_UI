"""UI-independent orchestration and model registry dispatch."""
import csv
import io
import math
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from .datasets import import_curve, demo_request
from .models import COLUMNS, MODEL_REGISTRY
from .schema import SimulationInput


class SimulationService:
    def __init__(self, repository):
        self.repository = repository
        self.recent = OrderedDict()
        self.lock = Lock()
        self.originals = {}

    def run(self, data, project_id="default", design_id=None):
        self.repository.require_project(project_id)
        config = SimulationInput.from_dict(data)
        design = None
        if design_id is not None:
            if not isinstance(design_id, str):
                raise ValueError("設計IDを確認してください。")
            design = self.repository.design(design_id, project_id)
            expected = design_simulation_fields(design)
            for key, val in expected.items():
                actual = getattr(config, key)
                if (isinstance(val, str) and actual != val) or (isinstance(val, (float, int)) and
                                                                not math.isclose(actual, val, rel_tol=1e-10,
                                                                                 abs_tol=1e-12)):
                    raise ValueError("設計と試験入力が一致しません。設計を再反映してください。")
        if config.model not in MODEL_REGISTRY:
            raise ValueError("未登録の計算モデルです。")
        model = MODEL_REGISTRY[config.model]
        output = model.simulate(config)
        result = {
            "schema_version": "1.0", "id": str(uuid4()), "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "name": config.name,
            "source_type": model.source_type, "validation_status": model.validation_status,
            "engine": {"id": model.id, "version": model.version, "label": model.label},
            "input": config.snapshot(), "limitations": list(model.limitations),
            "units": dict(zip(COLUMNS, ("s", "V", "A", "1", "degC", "Ah", "Wh"))),
            "sign_convention": "current_a / energy_wh: discharge positive, charge negative; capacity_ah: absolute throughput",
            "termination": output.termination, "summary": output.summary, "points": output.points,
        }
        if design is not None:
            result["design_snapshot"] = design
            result["limitations"].append(
                "合成モデルには設計の寸法・Cレート基準容量・模式曲線のみ反映。材料配合・端面集電の物理応答は計算していません。")
        with self.lock:
            self.recent[result["id"]] = result
            while len(self.recent) > 20:
                old_id, _ = self.recent.popitem(last=False)
                self.originals.pop(old_id, None)
        return result

    def preview_import(self, data, demo=False):
        if not isinstance(data, dict):
            raise ValueError("取込条件はオブジェクトで指定してください。")
        if demo:
            data = demo_request(data.get("project_id", "default"), data.get("seed", 42))
        result, raw = import_curve(data)
        self.repository.require_project(result["project_id"])
        result["duplicate_ids"] = self.repository.duplicate_ids(result["original"]["sha256"])
        with self.lock:
            self.recent[result["id"]] = result
            self.originals[result["id"]] = raw
            while len(self.recent) > 20:
                old_id, _ = self.recent.popitem(last=False)
                self.originals.pop(old_id, None)
        return result

    def original(self, run_id):
        with self.lock:
            raw = self.originals.get(run_id)
        return raw if raw is not None else self.repository.original(run_id)

    def get(self, run_id):
        with self.lock:
            result = self.recent.get(run_id)
        return result or self.repository.get(run_id)

    def save(self, run_id):
        result = self.get(run_id)
        if result is None:
            raise KeyError(run_id)
        self.repository.save(result, self.original(run_id))
        return {"id": run_id, "saved": True}


def design_simulation_fields(design):
    c = design["input"]
    return {"cell_format": c["cell_format"], "diameter_mm": c["diameter_mm"], "height_mm": c["height_mm"],
            "capacity_ah": design["capacity"]["c_rate_reference_ah"],
            "chemistry": "LFP" if c["positive_material"] == "LFP_demo" else "NMC"}


def export_csv(run):
    stream = io.StringIO(newline="")
    if run.get("record_type") == "dataset":
        import json
        # JSON escapes embedded newlines in metadata; original is a separate download.
        for key in ("id", "source_type", "validation_status", "source", "license", "original", "transform", "notes"):
            stream.write(f"# {key}: {json.dumps(run[key], ensure_ascii=False)}\n")
        columns = ("source_row", "segment_id", "step", "time_s", "voltage_v", "current_a", "capacity_ah", "soc",
                   "temperature_c")
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(run["points"])
        return stream.getvalue().encode("utf-8-sig")
    for key, value in {
        "run_id": run["id"], "source_type": run["source_type"],
        "validation_status": run["validation_status"], "schema_version": run["schema_version"],
        "engine": f'{run["engine"]["id"]}@{run["engine"]["version"]}',
        "termination": run["termination"], "sign_convention": run["sign_convention"],
    }.items():
        stream.write(f"# {key}: {value}\n")
    columns = COLUMNS if run.get("record_type") != "physics" else COLUMNS + ("segment_id", "electrolyte_min_mol_m3",
                                                                             "negative_surface_max_mol_m3")
    if run.get("record_type") == "physics":
        import json
        for key in ("input", "parameter_provenance", "numerical", "step_results"):
            stream.write(f"# {key}: {json.dumps(run[key], ensure_ascii=False)}\n")
        if run.get("design_snapshot"):
            stream.write(f'# design_id: {run["design_snapshot"]["id"]}\n')
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(run["points"])
    return stream.getvalue().encode("utf-8-sig")
