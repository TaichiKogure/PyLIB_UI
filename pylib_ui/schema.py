"""Versioned inputs shared by UI, model adapters and saved runs."""
import math
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class SimulationInput:
    name: str = "21700 · 1C 放電"
    model: str = "ecm_1rc"
    cell_format: str = "21700"
    chemistry: str = "NMC"
    capacity_ah: float = 5.0
    diameter_mm: float = 21.0
    height_mm: float = 70.0
    initial_soc: float = 0.95
    mode: str = "discharge"
    c_rate: float = 1.0
    duration_min: float = 60.0
    dt_s: float = 5.0
    initial_temp_c: float = 25.0
    ambient_temp_c: float = 25.0
    r0_mohm: float = 25.0
    r1_mohm: float = 10.0
    tau_s: float = 40.0
    thermal_capacity_j_k: float = 70.0
    heat_transfer_w_m2_k: float = 10.0
    min_voltage_v: float = 2.8
    max_voltage_v: float = 4.2

    def snapshot(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("入力はJSONオブジェクトで指定してください。")
        if set(data) - {f.name for f in fields(cls)}:
            raise ValueError("未対応の入力項目が含まれています。")
        strings = {"name", "model", "cell_format", "chemistry", "mode"}
        converted = {}
        for key, value in data.items():
            if key in strings:
                if not isinstance(value, str):
                    raise ValueError(f"{key} は文字列で指定してください。")
                converted[key] = value.strip()
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} は数値で指定してください。")
                converted[key] = float(value)
        result = cls(**converted)
        result.validate()
        return result

    def validate(self):
        if not self.name or len(self.name) > 100:
            raise ValueError("計算名は1〜100文字で入力してください。")
        if not self.model or len(self.model) > 80:
            raise ValueError("計算モデルIDを指定してください。")
        for field, choices in {
            "cell_format": {"18650", "21700"},
            "chemistry": {"NMC", "LFP"}, "mode": {"discharge", "charge", "rest"},
        }.items():
            if getattr(self, field) not in choices:
                raise ValueError(f"{field} の選択が未対応です。")
        ranges = {
            "capacity_ah": (0.1, 100), "diameter_mm": (10, 50), "height_mm": (20, 150),
            "initial_soc": (0, 1), "c_rate": (0.01, 5), "duration_min": (0.1, 360),
            "dt_s": (1, 60), "initial_temp_c": (-20, 60), "ambient_temp_c": (-20, 60),
            "r0_mohm": (0, 500), "r1_mohm": (0, 500), "tau_s": (1, 3600),
            "thermal_capacity_j_k": (1, 1000), "heat_transfer_w_m2_k": (0, 1000),
            "min_voltage_v": (1.5, 4.5), "max_voltage_v": (1.5, 4.5),
        }
        for field, (low, high) in ranges.items():
            value = getattr(self, field)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} は {low}〜{high} の有限値で入力してください。")
        if self.min_voltage_v >= self.max_voltage_v:
            raise ValueError("下限電圧は上限電圧より小さくしてください。")
        if math.ceil(self.duration_min * 60 / self.dt_s) > 12000:
            raise ValueError("出力は最大12,001点です。出力間隔を広げてください。")
