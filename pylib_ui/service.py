"""UI-independent orchestration and model registry dispatch."""
import csv
import io
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from .models import COLUMNS, MODEL_REGISTRY
from .schema import SimulationInput


class SimulationService:
    def __init__(self, repository):
        self.repository = repository
        self.recent = OrderedDict()
        self.lock = Lock()

    def run(self, data):
        config = SimulationInput.from_dict(data)
        if config.model not in MODEL_REGISTRY:
            raise ValueError("未登録の計算モデルです。")
        model = MODEL_REGISTRY[config.model]
        output = model.simulate(config)
        result = {
            "schema_version": "1.0", "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(), "name": config.name,
            "source_type": model.source_type, "validation_status": model.validation_status,
            "engine": {"id": model.id, "version": model.version, "label": model.label},
            "input": config.snapshot(), "limitations": list(model.limitations),
            "units": dict(zip(COLUMNS, ("s", "V", "A", "1", "degC", "Ah", "Wh"))),
            "sign_convention": "current_a / energy_wh: discharge positive, charge negative; capacity_ah: absolute throughput",
            "termination": output.termination, "summary": output.summary, "points": output.points,
        }
        with self.lock:
            self.recent[result["id"]] = result
            while len(self.recent) > 20:
                self.recent.popitem(last=False)
        return result

    def get(self, run_id):
        with self.lock:
            result = self.recent.get(run_id)
        return result or self.repository.get(run_id)

    def save(self, run_id):
        result = self.get(run_id)
        if result is None:
            raise KeyError(run_id)
        self.repository.save(result)
        return {"id": run_id, "saved": True}


def export_csv(run):
    stream = io.StringIO(newline="")
    for key, value in {
        "run_id": run["id"], "source_type": run["source_type"],
        "validation_status": run["validation_status"], "schema_version": run["schema_version"],
        "engine": f'{run["engine"]["id"]}@{run["engine"]["version"]}',
        "termination": run["termination"], "sign_convention": run["sign_convention"],
    }.items():
        stream.write(f"# {key}: {value}\n")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(run["points"])
    return stream.getvalue().encode("utf-8-sig")
