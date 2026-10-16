"""Model adapter boundary. Bundled parameters and OCVs are synthetic."""
import math
from dataclasses import dataclass
from typing import Protocol

from .schema import SimulationInput

COLUMNS = ("time_s", "voltage_v", "current_a", "soc", "temperature_c", "capacity_ah", "energy_wh")
LIMITATIONS = [
    "合成・未校正のOCV曲線と等価回路パラメータです。実測検証は未実施です。",
    "NMC／LFPは模式的なフルセルOCVです。具体組成や複合負極の物性は扱いません。",
    "寸法は表面積と放熱だけに反映します。容量・抵抗・熱容量は独立した入力です。",
    "温度は集中熱（抵抗発熱＋対流放熱）です。温度から抵抗・OCVへのフィードバックはありません。",
    "全面集電の局所分布、析出、膨張・応力、劣化、CC/CV切替は未実装です。",
]


@dataclass
class ModelOutput:
    points: list[dict]
    termination: str
    summary: dict


class SimulationModel(Protocol):
    id: str
    version: str
    label: str
    source_type: str
    validation_status: str
    limitations: list[str]

    def simulate(self, config: SimulationInput) -> ModelOutput: ...


def synthetic_ocv(soc: float, chemistry: str) -> float:
    """Illustrative full-cell curves; not published material fits."""
    soc = min(1.0, max(0.0, soc))
    if chemistry == "LFP":
        return 3.25 + 0.12 * soc + 0.22 * math.exp(-30 * (1 - soc)) - 0.35 * math.exp(-30 * soc)
    return 3.0 + 1.1 * soc + 0.1 * math.tanh(12 * (soc - 0.5))


class EquivalentCircuitModel:
    id = "ecm_1rc"
    version = "1.0.0"
    label = "等価回路 1RC ＋ 集中熱"
    source_type = "synthetic"
    validation_status = "uncalibrated"
    limitations = LIMITATIONS

    def simulate(self, config):
        config.validate()
        current = {"discharge": 1, "charge": -1, "rest": 0}[config.mode] * config.c_rate * config.capacity_ah
        r0, r1 = config.r0_mohm / 1000, config.r1_mohm / 1000
        diameter, height = config.diameter_mm / 1000, config.height_mm / 1000
        area = math.pi * diameter * height + math.pi * diameter ** 2 / 2
        conductance = area * config.heat_transfer_w_m2_k
        time, soc, polarization, temperature = 0.0, config.initial_soc, 0.0, config.initial_temp_c
        throughput, energy = 0.0, 0.0

        def state_after(seconds):
            next_soc = soc - current * seconds / (config.capacity_ah * 3600)
            next_rc = current * r1 + (polarization - current * r1) * math.exp(-seconds / config.tau_s)
            voltage = synthetic_ocv(next_soc, config.chemistry) - current * r0 - next_rc
            return next_soc, next_rc, voltage

        def stop_reason(state_soc, voltage):
            if voltage <= config.min_voltage_v:
                return "lower_voltage"
            if voltage >= config.max_voltage_v:
                return "upper_voltage"
            if current > 0 and state_soc <= 0:
                return "soc_empty"
            if current < 0 and state_soc >= 1:
                return "soc_full"
            return None

        def point(voltage):
            return dict(
                zip(COLUMNS, (time, voltage, current, min(1.0, max(0.0, soc)), temperature, throughput, energy)))

        voltage = state_after(0)[2]
        points = [point(voltage)]
        termination = stop_reason(soc, voltage)
        end_time = config.duration_min * 60
        while termination is None and time < end_time - 1e-9:
            seconds = min(config.dt_s, end_time - time)
            next_soc, next_rc, next_voltage = state_after(seconds)
            reason = stop_reason(next_soc, next_voltage)
            if reason:
                low, high = 0.0, seconds
                for _ in range(45):
                    middle = (low + high) / 2
                    middle_soc, _, middle_voltage = state_after(middle)
                    if stop_reason(middle_soc, middle_voltage):
                        high = middle
                    else:
                        low = middle
                seconds = high
                next_soc, next_rc, next_voltage = state_after(seconds)
                termination = stop_reason(next_soc, next_voltage) or reason
            # Exact integral of RC resistor dissipation over this interval.
            rc_heat = 0.0
            if r1 > 0:
                steady = current * r1
                delta = polarization - steady
                rc_heat = (steady ** 2 * seconds + 2 * steady * delta * config.tau_s *
                           (-math.expm1(-seconds / config.tau_s)) + delta ** 2 * config.tau_s / 2 *
                           (-math.expm1(-2 * seconds / config.tau_s))) / r1
            heat = current ** 2 * r0 * seconds + max(0.0, rc_heat)
            if conductance > 0:
                decay = math.exp(-conductance * seconds / config.thermal_capacity_j_k)
                temperature = (config.ambient_temp_c + (temperature - config.ambient_temp_c) * decay +
                               heat / seconds / conductance * (1 - decay))
            else:
                temperature += heat / config.thermal_capacity_j_k
            energy += current * (voltage + next_voltage) / 2 * seconds / 3600
            throughput += abs(current) * seconds / 3600
            time += seconds
            soc, polarization, voltage = next_soc, next_rc, next_voltage
            points.append(point(voltage))
        return ModelOutput(points, termination or "duration", {
            "duration_s": time, "capacity_ah": throughput, "energy_wh": energy,
            "final_soc": min(1.0, max(0.0, soc)), "final_voltage_v": voltage,
            "max_temperature_c": max(p["temperature_c"] for p in points),
            "current_a": current, "surface_area_m2": area, "point_count": len(points),
        })


MODEL_REGISTRY: dict[str, SimulationModel] = {EquivalentCircuitModel.id: EquivalentCircuitModel()}
