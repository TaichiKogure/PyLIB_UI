"""Source-bounded, piecewise linear cathode reference-curve calculations.

This is a single CC calculation, not a porous-electrode/transport model. A
finite-current half-cell curve retains its measured polarization. Graphite OCP
subtraction and an explicitly additional series resistance are optional.
"""
import hashlib
import json
import math
from bisect import bisect_right
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

CATALOG_PATH = Path(__file__).parent / "reference/cathodes.v1.json"
VERSION = "1.0.0"

DEFAULTS = dict(name="公開正極曲線のCC計算", curve_id="nmc811_2023_cycle4", voltage_basis="vs_li",
                mode="discharge", initial_soc=0.95, positive_mass_g=10.0, ocp_capacity_mah_g=200.0,
                current_a=0.5, duration_min=360.0, dt_s=10.0,
                positive_min_v=2.0, positive_max_v=4.4, cell_min_v=2.0, cell_max_v=4.4,
                negative_capacity_ah=3.0, negative_initial_fraction=0.9, additional_r_mohm=0.0)

LIMITATIONS = [
    "公開参照曲線に沿う単一CCの容量・時間・電圧・エネルギー計算です。対象セルの実測検証は未実施です。",
    "有限電流の半電池曲線は分極を含みます。平衡正極OCPとは区別し、参照曲線の既存抵抗を再加算しません。",
    "電流変更は曲線上の進行速度だけを変えます。レート特性、温度依存性、拡散、析出、劣化、CV制御は予測しません。",
    "充放電は別々の容量座標です。枝ごとの比容量を保持し、正規化座標を絶対Li量や閉じたサイクルのSOCとは同一視しません。",
    "フルセルは正極参照電圧−黒鉛OCP−I×追加抵抗の近似。負極分極、Li対極分極の分離、初期Li損失は未同定です。",
    "電極の有効範囲の端で停止します。1.5–2.0 Vまで未収録の場合も外挿・平坦延長はしません。",
]


@lru_cache(maxsize=1)
def _catalog():
    raw = CATALOG_PATH.read_bytes()
    data = json.loads(raw)
    for curve in data["curves"]:
        for mode, branch in curve["branches"].items():
            points = branch["points"]
            if (len(points) < 3 or points[0][0] != 0 or points[-1][0] != 1
                    or any(not math.isfinite(x + v) or not 0 <= x <= 1 or not 0 < v < 6 for x, v in points)
                    or any(b[0] <= a[0] for a, b in zip(points, points[1:]))):
                raise ValueError("正極カタログの座標・電圧を確認してください。")
            q = branch["specific_capacity_mah_g"]
            if q is not None and not 0 < q < 400:
                raise ValueError("正極カタログの容量を確認してください。")
    data["sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def catalog():
    return deepcopy(_catalog())


def validate(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError("公開曲線の入力項目を確認してください。")
    c = {**DEFAULTS, **data}
    if not isinstance(c["name"], str) or not c["name"].strip() or len(c["name"]) > 100:
        raise ValueError("計算名は1〜100文字で指定してください。")
    c["name"] = c["name"].strip()
    if not isinstance(c["curve_id"], str) or c["curve_id"] not in {v["id"] for v in _catalog()["curves"]}:
        raise ValueError("収録済みの正極曲線を選択してください。")
    if c["voltage_basis"] not in ("vs_li", "full_cell") or c["mode"] not in ("charge", "discharge"):
        raise ValueError("電圧基準・充放電の区分を確認してください。")
    ranges = dict(initial_soc=(0, 1), positive_mass_g=(0.001, 10000), ocp_capacity_mah_g=(1, 400),
                  current_a=(0.00001, 1000), duration_min=(0.01, 1440), dt_s=(0.1, 120),
                  positive_min_v=(1.5, 5), positive_max_v=(1.5, 5), cell_min_v=(1.5, 5), cell_max_v=(1.5, 5),
                  negative_capacity_ah=(0.00001, 10000), negative_initial_fraction=(0, 1), additional_r_mohm=(0, 10000))
    for key, (low, high) in ranges.items():
        value = c[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
                value) or not low <= value <= high:
            raise ValueError(f"{key} は {low}〜{high} の有限数で指定してください。")
    if c["positive_min_v"] >= c["positive_max_v"] or c["cell_min_v"] >= c["cell_max_v"]:
        raise ValueError("下限電圧を上限電圧より小さくしてください。")
    if c["duration_min"] * 60 / c["dt_s"] > 12000:
        raise ValueError("出力間隔を広げてください。時間÷間隔は12000以内です。")
    if c["voltage_basis"] == "full_cell":
        xs = _catalog()["negative_reference"]["points"]
        if not xs[0][0] <= c["negative_initial_fraction"] <= xs[-1][0]:
            raise ValueError(f"負極初期座標は公開OCPの {xs[0][0]:.6f}〜{xs[-1][0]:.6f} 以内で指定してください。")
    return c


def interpolate(points, x):
    """Linear interpolation only; no clamping outside the recorded domain."""
    if x < points[0][0] - 1e-10 or x > points[-1][0] + 1e-10:
        raise ValueError("参照曲線の有効範囲を超えました。")
    x = min(points[-1][0], max(points[0][0], x))  # roundoff only
    i = max(0, min(len(points) - 2, bisect_right(points, [x, math.inf]) - 1))
    a, b = points[i], points[i + 1]
    return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])


def simulate(data, project_id="default"):
    c = validate(data)
    source = next(x for x in _catalog()["curves"] if x["id"] == c["curve_id"])
    mode = c["mode"]
    independent_branches = "discharge" in source["branches"]
    branch = source["branches"][mode if independent_branches else "charge"]
    # All trajectories below use increasing passed-charge fraction, from 0 to 1.
    reference = branch["points"] if independent_branches or mode == "charge" else [
        [1 - x, v] for x, v in reversed(branch["points"])]
    q_specific = branch["specific_capacity_mah_g"] or c["ocp_capacity_mah_g"]
    q_positive = q_specific * c["positive_mass_g"] / 1000
    q_negative = c["negative_capacity_ah"]
    current = c["current_a"] * (1 if mode == "discharge" else -1)
    rate = abs(current) / (q_positive * 3600)
    start = 1 - c["initial_soc"] if mode == "discharge" else c["initial_soc"]
    source_end_s = (1 - start) / rate
    end = min(c["duration_min"] * 60, source_end_s)
    termination = "positive_source_end" if source_end_s <= end else "duration"
    negative = _catalog()["negative_reference"]
    negative_rate = -current / (q_negative * 3600)
    if c["voltage_basis"] == "full_cell":
        target = negative["points"][0 if current > 0 else -1][0]
        negative_end_s = max(0.0, (target - c["negative_initial_fraction"]) / negative_rate)
        if negative_end_s < end:
            end, termination = negative_end_s, "negative_source_end"

    def voltages(t):
        progress = start + rate * t
        positive = interpolate(reference, progress)
        x_negative = c["negative_initial_fraction"] + negative_rate * t if c["voltage_basis"] == "full_cell" else None
        un = interpolate(negative["points"], x_negative) if x_negative is not None else 0.0
        return positive, un, positive - un - current * c["additional_r_mohm"] / 1000, x_negative

    def margins(v):
        positive, un, terminal, xn = v
        result = [(positive - c["positive_min_v"], "positive_lower_voltage"),
                  (c["positive_max_v"] - positive, "positive_upper_voltage")]
        if c["voltage_basis"] == "full_cell":
            result.extend([(terminal - c["cell_min_v"], "cell_lower_voltage"),
                           (c["cell_max_v"] - terminal, "cell_upper_voltage")])
        return result

    # Breakpoints of both electrodes make every segment linear. Cutoff location
    # and energy integration are independent of the requested output interval.
    knots = {0.0, end}
    knots.update((x - start) / rate for x, v in reference if 0 < (x - start) / rate < end)
    if c["voltage_basis"] == "full_cell":
        knots.update((x - c["negative_initial_fraction"]) / negative_rate
                     for x, v in negative["points"] if 0 < (x - c["negative_initial_fraction"]) / negative_rate < end)
    knots.update(i * c["dt_s"] for i in range(1, math.ceil(end / c["dt_s"])) if i * c["dt_s"] < end)
    timeline = sorted(knots)
    # Stop also when the supplied initial state is outside a voltage window.
    initial_margins = margins(voltages(0))
    initial_stop = next((reason for value, reason in initial_margins if value <= 0), None)
    if initial_stop:
        timeline, termination = [0.0], initial_stop
    else:
        for index, (ta, tb) in enumerate(zip(timeline, timeline[1:])):
            ma, mb = margins(voltages(ta)), margins(voltages(tb))
            roots = [(ta + (tb - ta) * va / (va - vb), reason)
                     for (va, reason), (vb, _) in zip(ma, mb) if vb <= 0 and va > 0]
            if roots:
                stop, termination = min(roots)
                timeline = timeline[:index + 1] + [stop]
                break

    points, energy, previous_time, previous_voltage = [], 0.0, 0.0, voltages(0)[2]
    for t in timeline:
        up, un, voltage, xn = voltages(t)
        energy += current * (voltage + previous_voltage) / 2 * (t - previous_time) / 3600
        points.append(dict(time_s=t, voltage_v=voltage, current_a=current,
                           soc=1 - (start + rate * t) if mode == "discharge" else start + rate * t,
                           temperature_c=source["temperature_c"], capacity_ah=abs(current) * t / 3600,
                           energy_wh=energy, positive_reference_v=up, negative_reference_v=un,
                           negative_fraction=xn, additional_ohmic_loss_v=current * c["additional_r_mohm"] / 1000))
        previous_time, previous_voltage = t, voltage
    last = points[-1]
    warnings = list(source["notes"])
    vrange = branch["voltage_range_v"]
    if c["positive_min_v"] < vrange[0]:
        warnings.append(
            f"指定下限 {c['positive_min_v']:g} V に対し、採用枝の収録下端は {vrange[0]:.4f} V。低電圧側の未収録部分は計算しません。")
    if c["positive_max_v"] > vrange[1]:
        warnings.append(
            f"指定上限 {c['positive_max_v']:g} V に対し、採用枝の収録上端は {vrange[1]:.4f} V。上側へ外挿しません。")
    if not independent_branches:
        warnings.append("比容量を持たないOCPなので、容量スケールはユーザー指定です。充放電で同じOCPを使用します。")
    if c["voltage_basis"] == "full_cell":
        warnings.append("黒鉛と正極の組合せは仮想セルです。負極座標は Qn×Δxn = −I×t/3600 の電荷保存で更新します。")
    if source["specific_current_ma_g"] is not None:
        applied = abs(current) * 1000 / c["positive_mass_g"]
        if not math.isclose(applied, source["specific_current_ma_g"], rel_tol=0.001):
            warnings.append(
                f"参照電流 {source['specific_current_ma_g']:g} mA/g、設定 {applied:g} mA/g。設定電流でのレート性能は未予測です。")
    return dict(schema_version="1.0", record_type="reference_curve", id=str(uuid4()), project_id=project_id,
                created_at=datetime.now(timezone.utc).isoformat(), name=c["name"], input=c,
                engine=dict(id="cathode_reference_cc", version=VERSION, label="公開正極曲線 CC"),
                source_type="reference_simulation", validation_status="source_bounded_unvalidated",
                sign_convention="current_a / energy_wh: discharge positive, charge negative; capacity_ah: absolute throughput",
                voltage_reference="Li/Li+" if c["voltage_basis"] == "vs_li" else "full_cell_terminal",
                units=dict(time_s="s", voltage_v="V", current_a="A", soc="relative branch coordinate",
                           temperature_c="degC (source condition)", capacity_ah="Ah", energy_wh="Wh",
                           positive_reference_v="V vs Li/Li+ (half-cell voltage for finite-current data)",
                           negative_reference_v="V vs Li/Li+", negative_fraction="relative reference coordinate",
                           additional_ohmic_loss_v="V"),
                termination=termination, limitations=LIMITATIONS + warnings, points=points,
                source_snapshot=dict(catalog_version=_catalog()["catalog_version"], catalog_sha256=_catalog()["sha256"],
                                     positive=deepcopy(source),
                                     negative=deepcopy(negative) if c["voltage_basis"] == "full_cell" else None),
                mapping=dict(positive_capacity_ah=q_positive, positive_specific_capacity_mah_g=q_specific,
                             capacity_basis="source_branch" if branch[
                                 "specific_capacity_mah_g"] else "user_assumed_ocp_scale",
                             independent_charge_discharge=independent_branches,
                             negative_capacity_ah=q_negative if c["voltage_basis"] == "full_cell" else None,
                             method="piecewise linear; all electrode breakpoints retained; exact linear cutoff and trapezoidal energy"),
                summary=dict(duration_s=last["time_s"], capacity_ah=last["capacity_ah"], energy_wh=last["energy_wh"],
                             final_soc=last["soc"], point_count=len(points), max_temperature_c=source["temperature_c"],
                             final_positive_v=last["positive_reference_v"],
                             final_negative_v=last["negative_reference_v"],
                             final_terminal_v=last["voltage_v"],
                             additional_heat_w=current ** 2 * c["additional_r_mohm"] / 1000))
