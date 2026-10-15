"""Step 2: independent, versioned cylindrical design balances (mm, um, g, Ah)."""
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, fields

# Explicit illustrative properties, never substituted into a calibrated solver set.
MATERIALS = {
    "NMC811_demo": {"label": "NCX / LiNi0.8Mn0.1Co0.1O2", "role": "positive", "density_g_cm3": 4.8,
                    "capacity_mah_g": 200},
    "NCA_demo": {"label": "NCX / LiNi0.8Co0.15Al0.05O2", "role": "positive", "density_g_cm3": 4.75,
                 "capacity_mah_g": 195},
    "LFP_demo": {"label": "LiFePO4", "role": "positive", "density_g_cm3": 3.6, "capacity_mah_g": 160},
    "graphite_demo": {"label": "黒鉛", "role": "negative", "density_g_cm3": 2.26, "capacity_mah_g": 350},
    "Si_demo": {"label": "Si（元素Si）", "role": "negative_additive", "density_g_cm3": 2.33, "capacity_mah_g": 3000},
    "SiOx_demo": {"label": "SiOx（x・不可逆損失は未同定）", "role": "negative_additive", "density_g_cm3": 2.2,
                  "capacity_mah_g": 1200},
    "binder_demo": {"label": "結着剤", "role": "inactive", "density_g_cm3": 1.8, "capacity_mah_g": 0},
    "carbon_demo": {"label": "導電助剤", "role": "inactive", "density_g_cm3": 2.0, "capacity_mah_g": 0},
}
for _material in MATERIALS.values():
    _material.update(status="illustrative_unvalidated",
                     source="PyLIB Step2 仮定値 v1。材料名は識別用、物性は実測・文献校正値ではない。")


@dataclass(frozen=True)
class DesignInput:
    name: str = "21700 巻回設計"
    cell_format: str = "21700"
    diameter_mm: float = 21
    height_mm: float = 70
    wall_mm: float = 0.25
    lid_total_mm: float = 0.6
    axial_reserve_mm: float = 4
    radial_gap_mm: float = 0.2
    core_diameter_mm: float = 3
    winding_width_mm: float = 64
    positive_width_mm: float = 60
    negative_width_mm: float = 62
    length_mode: str = "fit"
    length_mm: float = 1400
    positive_thickness_um: float = 65
    negative_thickness_um: float = 75
    positive_foil_um: float = 15
    negative_foil_um: float = 8
    separator_um: float = 16
    separator_porosity: float = 0.45
    positive_porosity: float = 0.3
    negative_porosity: float = 0.32
    positive_material: str = "NMC811_demo"
    negative_additive: str = "Si_demo"
    fraction_basis: str = "mass"
    positive_active: float = 0.96
    positive_binder: float = 0.02
    positive_carbon: float = 0.02
    negative_graphite: float = 0.96
    negative_si: float = 0
    negative_binder: float = 0.02
    negative_carbon: float = 0.02
    lithium_fraction_positive: float = 0.5
    lithium_fraction_negative: float = 0.5
    c_rate_capacity_mode: str = "design"
    rated_capacity_ah: float = 5
    positive_terminal: str = "top"
    negative_terminal: str = "bottom"
    positive_contact_fraction: float = 1
    negative_contact_fraction: float = 1
    electrolyte_fill: float = 1
    electrolyte_density_g_cm3: float = 1.2
    hardware_mass_g: float = 3

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
            raise ValueError("設計スキーマにない項目が含まれています。")
        defaults = asdict(cls())
        for key, val in data.items():
            if isinstance(defaults[key], str):
                if not isinstance(val, str):
                    raise ValueError(f"{key} は文字列で指定してください。")
            elif isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                raise ValueError(f"{key} は有限の数値で指定してください。")
        config = cls(**data)
        config.validate()
        return config

    def validate(self):
        if not self.name.strip() or len(self.name) > 100:
            raise ValueError("設計名は1〜100文字で指定してください。")
        for key, choices in {
            "cell_format": {"18650", "21700"}, "length_mode": {"fit", "manual"},
            "fraction_basis": {"mass", "volume"}, "positive_material": {"NMC811_demo", "NCA_demo", "LFP_demo"},
            "negative_additive": {"Si_demo", "SiOx_demo"}, "c_rate_capacity_mode": {"design", "rated"},
            "positive_terminal": {"top", "bottom"}, "negative_terminal": {"top", "bottom"},
        }.items():
            if getattr(self, key) not in choices:
                raise ValueError(f"{key} の選択が未対応です。")
        for key, val in asdict(self).items():
            if isinstance(val, str):
                continue
            if "porosity" in key or key.startswith("lithium_fraction") or key in {
                "positive_active", "positive_binder", "positive_carbon", "negative_graphite", "negative_si",
                "negative_binder", "negative_carbon", "electrolyte_fill", "positive_contact_fraction",
                "negative_contact_fraction",
            }:
                if not 0 <= val <= 1:
                    raise ValueError(f"{key} は0〜1で指定してください。")
            elif not 0 <= val <= 100000:
                raise ValueError(f"{key} は0〜100000で指定してください。")
        for key in ("diameter_mm", "height_mm", "wall_mm", "core_diameter_mm", "winding_width_mm", "positive_width_mm",
                    "negative_width_mm", "length_mm", "positive_thickness_um", "negative_thickness_um",
                    "positive_foil_um",
                    "negative_foil_um", "separator_um", "rated_capacity_ah", "electrolyte_density_g_cm3"):
            if getattr(self, key) <= 0:
                raise ValueError(f"{key} は正の値で指定してください。")
        if self.positive_porosity >= 1 or self.negative_porosity >= 1 or self.separator_porosity >= 1:
            raise ValueError("空隙率は1未満にしてください。")
        if self.positive_terminal == self.negative_terminal:
            raise ValueError("この段階の上下端面接続は正負を別の端面に指定してください。")
        if min(self.positive_contact_fraction, self.negative_contact_fraction) <= 0:
            raise ValueError("端面接触面積率は0より大きくしてください。")
        if not 0 < self.positive_width_mm <= self.negative_width_mm <= self.winding_width_mm:
            raise ValueError("塗工幅は 正極 ≤ 負極 ≤ 巻回幅 にしてください。")
        if self.winding_width_mm > self.height_mm - self.axial_reserve_mm:
            raise ValueError("巻回幅が缶の有効高さを超過しています。")
        if not 0 < self.lid_total_mm <= self.axial_reserve_mm:
            raise ValueError("上下蓋の合計厚は正値で、予約高さ以下にしてください。")
        if (self.diameter_mm / 2 - self.wall_mm - self.radial_gap_mm) <= self.core_diameter_mm / 2:
            raise ValueError("中心空間・缶壁・径方向隙間がセル径を超過しています。")
        if self.positive_active <= 0 or self.negative_graphite + self.negative_si <= 0:
            raise ValueError("正負極に活物質が必要です。")
        for parts in ((self.positive_active, self.positive_binder, self.positive_carbon),
                      (self.negative_graphite, self.negative_si, self.negative_binder, self.negative_carbon)):
            if not math.isclose(sum(parts), 1, abs_tol=1e-9):
                raise ValueError("各電極の乾燥固体配合の合計を1にしてください（孔隙は含めません）。")


def templates():
    large = asdict(DesignInput())
    small = dict(large, name="18650 巻回設計", cell_format="18650", diameter_mm=18, height_mm=65,
                 winding_width_mm=59, positive_width_mm=55, negative_width_mm=57, rated_capacity_ah=3)
    return {"21700": large, "18650": small}


def _recipe(ids, fractions, basis):
    densities = [MATERIALS[i]["density_g_cm3"] for i in ids]
    if basis == "mass":
        mass = fractions
        specific_volume = sum(f / d for f, d in zip(mass, densities))
        density = 1 / specific_volume
        volume = [f / d * density for f, d in zip(mass, densities)]
    else:
        volume = fractions
        density = sum(f * d for f, d in zip(volume, densities))
        mass = [f * d / density for f, d in zip(volume, densities)]
    return {"solid_density_g_cm3": density, "specific_capacity_mah_g": sum(
        f * MATERIALS[i]["capacity_mah_g"] for i, f in zip(ids, mass)),
            "components": [{"id": i, "mass_fraction": m, "solid_volume_fraction": v} for i, m, v in
                           zip(ids, mass, volume)]}


def evaluate_design(data):
    c = DesignInput.from_dict(data)
    p = _recipe([c.positive_material, "binder_demo", "carbon_demo"],
                [c.positive_active, c.positive_binder, c.positive_carbon], c.fraction_basis)
    n = _recipe(["graphite_demo", c.negative_additive, "binder_demo", "carbon_demo"],
                [c.negative_graphite, c.negative_si, c.negative_binder, c.negative_carbon], c.fraction_basis)
    pitch = (
                        2 * c.positive_thickness_um + c.positive_foil_um + 2 * c.negative_thickness_um + c.negative_foil_um + 2 * c.separator_um) / 1000
    ri = c.core_diameter_mm / 2
    limit_r = c.diameter_mm / 2 - c.wall_mm - c.radial_gap_mm
    max_length = math.pi * (limit_r ** 2 - ri ** 2) / pitch
    length = max_length if c.length_mode == "fit" else c.length_mm
    if length > max_length * (1 + 1e-10):
        raise ValueError(f"巻回体の体積超過です。最大巻回長は {max_length:.3f} mm です。")
    ro = math.sqrt(ri ** 2 + length * pitch / math.pi)
    for electrode, width, thickness, porosity in (
            (p, c.positive_width_mm, c.positive_thickness_um, c.positive_porosity),
            (n, c.negative_width_mm, c.negative_thickness_um, c.negative_porosity),
    ):
        area = 2 * width * length / 100  # double coated faces: mm² -> cm²
        volume = area * thickness / 10000  # um -> cm
        electrode.update(area_cm2=area, coating_volume_cm3=volume,
                         pore_volume_cm3=volume * porosity,
                         mass_loading_mg_cm2=thickness / 10 * (1 - porosity) * electrode["solid_density_g_cm3"])
        electrode["dry_mass_g"] = volume * (1 - porosity) * electrode["solid_density_g_cm3"]
        electrode["capacity_ah"] = electrode["dry_mass_g"] * electrode["specific_capacity_mah_g"] / 1000
        electrode["areal_capacity_mah_cm2"] = electrode["mass_loading_mg_cm2"] * electrode[
            "specific_capacity_mah_g"] / 1000
    overlap_n_capacity = n["capacity_ah"] * c.positive_width_mm / c.negative_width_mm
    nominal = min(p["capacity_ah"], overlap_n_capacity)
    foil_volume_p = length * c.winding_width_mm * c.positive_foil_um / 1e6
    foil_volume_n = length * c.winding_width_mm * c.negative_foil_um / 1e6
    separator_volume = 2 * length * c.winding_width_mm * c.separator_um / 1e6
    pores = p["pore_volume_cm3"] + n["pore_volume_cm3"] + separator_volume * c.separator_porosity
    # Foils share the winding width; uncoated axial strips remain void and are not filled implicitly.
    envelope = length * c.winding_width_mm * pitch / 1000
    accounted = p["coating_volume_cm3"] + n["coating_volume_cm3"] + foil_volume_p + foil_volume_n + separator_volume
    can_volume = math.pi * (c.diameter_mm ** 2 / 4 * c.height_mm -
                            (c.diameter_mm / 2 - c.wall_mm) ** 2 * (c.height_mm - c.lid_total_mm)) / 1000
    masses = {"positive_dry": p["dry_mass_g"], "negative_dry": n["dry_mass_g"],
              "al_foil": foil_volume_p * 2.7, "cu_foil": foil_volume_n * 8.96,
              "separator_solid": separator_volume * (1 - c.separator_porosity) * 0.94,
              "electrolyte": pores * c.electrolyte_fill * c.electrolyte_density_g_cm3,
              "can_and_lids": can_volume * 7.85, "other_hardware": c.hardware_mass_g}
    if can_volume <= 0 or accounted > envelope * (1 + 1e-10):
        raise ValueError("缶・巻回構成の体積収支が成立しません。")
    warnings = ["材料物性・容量・質量は仮定値による設計見積り。実測校正なし。",
                "設計容量は半電池容量の小さい側。初期Li・利用率・終止電圧による実際の取出容量ではない。",
                "巻回は面積保存の連続環状近似。端部・塗工開始終了・曲率差・溶接形状は省略。",
                "上下端面集電は接続指定のみ。局所電流・接触抵抗・発熱・力学は未計算。",
                "Li在庫は容量×初期充填率のAh等価帳簿。SEI・不可逆損失・電解液Liを含まない。"]
    if overlap_n_capacity < p["capacity_ah"]:
        warnings.append("重なり領域のN/Pが1未満です。負極容量が設計容量を制限します。")
    if c.electrolyte_fill < 1:
        warnings.append("孔隙の未充填あり。濡れ不足による性能変化は未計算。")
    active_n = [part for part in n["components"][:2] if part["mass_fraction"] > 0]
    return {"schema_version": "design-2.0", "input": asdict(c), "validation_status": "illustrative_unvalidated",
            "materials": deepcopy({i: MATERIALS[i] for i in
                                   {c.positive_material, "graphite_demo", c.negative_additive, "binder_demo",
                                    "carbon_demo"}}),
            "geometry": {"pitch_mm": pitch, "length_mm": length, "max_length_mm": max_length,
                         "inner_radius_mm": ri, "outer_radius_mm": ro, "turns": (ro - ri) / pitch,
                         "envelope_cm3": envelope, "layer_volume_cm3": accounted,
                         "uncoated_void_cm3": max(0, envelope - accounted), "pore_volume_cm3": pores},
            "positive": p, "negative": n, "negative_phase_count": len(active_n),
            "capacity": {"positive_ah": p["capacity_ah"], "negative_total_ah": n["capacity_ah"],
                         "negative_overlap_ah": overlap_n_capacity, "np_ratio": overlap_n_capacity / p["capacity_ah"],
                         "design_ah": nominal,
                         "c_rate_reference_ah": nominal if c.c_rate_capacity_mode == "design" else c.rated_capacity_ah},
            "lithium_inventory": {"positive_ah_equivalent": p["capacity_ah"] * c.lithium_fraction_positive,
                                  "negative_ah_equivalent": n["capacity_ah"] * c.lithium_fraction_negative,
                                  "total_mol_equivalent": (p["capacity_ah"] * c.lithium_fraction_positive +
                                                           n[
                                                               "capacity_ah"] * c.lithium_fraction_negative) * 3600 / 96485.33212},
            "mass_g": masses, "total_mass_g": sum(masses.values()),
            "collector_connections": {"positive": {"foil": "Al", "face": c.positive_terminal,
                                                   "contact_fraction": c.positive_contact_fraction},
                                      "negative": {"foil": "Cu", "face": c.negative_terminal,
                                                   "contact_fraction": c.negative_contact_fraction},
                                      "distribution_solved": False},
            "adapter_input": {"electrode_height_m": c.positive_width_mm / 1000, "electrode_width_m": length / 1000,
                              "parallel_electrodes": 2, "paired_area_m2": p["area_cm2"] / 10000,
                              "positive_thickness_m": c.positive_thickness_um * 1e-6,
                              "negative_thickness_m": c.negative_thickness_um * 1e-6,
                              "positive_porosity": c.positive_porosity, "negative_porosity": c.negative_porosity,
                              "negative_phase_volume_fractions": [
                                  part["solid_volume_fraction"] * (1 - c.negative_porosity) for part in active_n],
                              "negative_particle_phases": "1" if len(active_n) == 1 else "2",
                              "negative_active_components": active_n,
                              "solver_ready": False, "reason": "Step3で材料パラメータ・初期化の整合検証が必要"},
            "warnings": warnings}
