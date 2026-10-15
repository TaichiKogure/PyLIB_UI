"""Traceable analytical screening, independent of PyBaMM and measured DCIR.

SI internally. Uniform through-thickness reaction and continuous foil-edge
collection are assumptions, not solutions of the porous-electrode equations.
"""
import math
from copy import deepcopy

VERSION = "design-screening-1.0"
FARADAY = 96485.33212
GAS_CONSTANT = 8.314462618
# n electrons per formula unit, molar mass in g/mol. Stoichiometric upper
# limits do not define a practical voltage window or a material's ICE.
STOICHIOMETRY = {
    "NMC811_demo": (1, 6.94 + .8 * 58.6934 + .1 * 54.938044 + .1 * 58.933194 + 2 * 15.999, "LiMO₂ → MO₂ + Li⁺ + e⁻"),
    "NCA_demo": (1, 6.94 + .8 * 58.6934 + .15 * 58.933194 + .05 * 26.981538 + 2 * 15.999, "LiMO₂ → MO₂ + Li⁺ + e⁻"),
    "LFP_demo": (1, 6.94 + 55.845 + 30.973762 + 4 * 15.999, "LiFePO₄ ↔ FePO₄ + Li⁺ + e⁻"),
    "graphite_demo": (1, 6 * 12.011, "6C + Li⁺ + e⁻ ↔ LiC₆（炭素質量基準）"),
    "Si_demo": (3.75, 28.085, "Si + 3.75Li⁺ + 3.75e⁻ ↔ Li₃.₇₅Si（Si質量基準）"),
}
REFERENCES = [
    dict(id="SiGraphite2016", authors="Sternad, Forster & Wilkening", year=2016,
         title="The microstructure matters: breaking down the barriers with single crystalline silicon as negative electrode in Li-ion batteries",
         url="https://doi.org/10.1038/srep31712",
         use="LiC₆とLi₁₅Si₄の反応終点の確認。理論比容量は各反応式から再計算し、実用比容量とは区別。"),
    dict(id="DFN1993", authors="Doyle, Fuller & Newman", year=1993,
         title="Modeling of Galvanostatic Charge and Discharge of the Lithium/Polymer/Insertion Cell",
         url="https://doi.org/10.1149/1.2221597",
         use="多孔質電極の電荷輸送・反応分極の基礎。ここでの集中近似は原著DFNの再現ではない。"),
    dict(id="Newman1995", authors="Newman", year=1995,
         title="Optimization of Porosity and Thickness of a Battery Electrode by Means of a Reaction-Zone Model",
         url="https://doi.org/10.1149/1.2043956",
         use="活物質量と孔内輸送のトレードオフ。原著の最適値を本セルへ転用しない。"),
    dict(id="Landesfeind2016", authors="Landesfeind et al.", year=2016,
         title="Tortuosity Determination of Battery Electrodes and Separators by Impedance Spectroscopy",
         url="https://doi.org/10.1149/2.1141607jes",
         use="実電極の屈曲度はBruggeman近似と異なり得る。指数1.5は未校正の初期仮定。"),
    dict(id="Tranter2020", authors="Tranter, Timms, Shearing & Brett", year=2020,
         title="Communication—Prediction of Thermal Issues for Larger Format 4680 Cylindrical Cells and Their Mitigation with Enhanced Current Collection",
         url="https://doi.org/10.1149/1945-7111/abd44f",
         use="集電方式による電流経路・熱の違い。下記1/3係数は一様注入から独立に導出した理想近似。"),
    dict(id="Bernardi1985", authors="Bernardi, Pawlikowski & Newman", year=1985,
         title="A General Energy Balance for Battery Systems",
         url="https://doi.org/10.1149/1.2113792",
         use="熱収支の基礎。本見積りは不可逆損失Iηのみで、反応エントロピー・混合熱は含めない。"),
    dict(id="Chen2020", authors="Chen et al.", year=2020,
         title="Development of Experimental Techniques for Parameterization of Multi-scale Lithium-ion Battery Models",
         url="https://doi.org/10.1149/1945-7111/ab9050",
         use="幾何・容量・輸送・反応物性を別に測定する考え方。画面の仮定値を原著実測値とは扱わない。"),
    dict(id="PyBaMMTransport", authors="PyBaMM team", year=2026,
         title="Transport efficiency and the models for tortuosity factor",
         url="https://docs.pybamm.org/en/latest/source/examples/notebooks/models/tortuosity_models.html",
         use="輸送効率ε/τ、Bruggeman式ε^bの定義確認。latest文書の確認日2026-10-16。"),
]

FORMULAS = [
    dict(id="theoretical_capacity", expression="q_theory = n F/(3.6 M)",
         units="n: electrons/formula; M: g/mol → mAh/g", references=["SiGraphite2016"],
         assumption="反応式による上限。正極は全1Li、黒鉛はLiC6、SiはLi15Si4。実用電圧窓・不可逆損失・劣化を含まない。SiOxはx未指定なので算出しない。"),
    dict(id="capacity", expression="Q = m_dry Σ(w_i q_i)/1000; q_areal = loading × Σ(w_i q_i)/1000",
         units="g, mAh/g, mg/cm² → Ah, mAh/cm²", references=["Chen2020"],
         assumption="配合を質量分率へ換算。両面面積=2×塗工幅×巻回長。負極は重なり面積に縮約。"),
    dict(id="inventory",
         expression="Qp,u=up Qp; Qn,u=un Qn,overlap; Qloss=Qn,u(1/ICE−1); Qbalance=max(0,min(Qp,u−Qloss,Qn,u))",
         units="Ah", references=[],
         assumption="可逆容量基準ICE=脱離/挿入。負極の指定利用窓全体を形成する独立のLi消費帳簿。正極がLiを供給、予備Liなし。OCV窓・初期Li充填率とは独立。"),
    dict(id="transport", expression="κeff=κ ε^b; τfactor=ε^(1−b); Re=L/(3κeff A); Rs=Ls/(κeff,s A); Rsolid=L/(3σeff A)",
         units="S/m, m, m² → Ω", references=["DFN1993", "Landesfeind2016", "PyBaMMTransport"],
         assumption="完全含浸、一様反応。電極は線形電流分布の損失積分で1/3、セパレータは全電流。σは指定の有効値。濃度分極は省略。"),
    dict(id="kinetics", expression="as=3εactive/r; I0=i0 as L A; ηct=(2RT/F) asinh(I/(2I0)); Rct=ηct/I",
         units="m, A/m²(active surface), K → V, Ω", references=["DFN1993"],
         assumption="対称Butler–Volmer、単一等価粒子、指定評価点のi0。I=0ではRT/(F I0)。複合負極も指定i0・半径の均質近似。"),
    dict(id="collector", expression="Rfoil,edge=ρ H/(3t ℓ); Rfoil,long=ρ ℓ/(3t H); Aedge=t ℓ; Rcontact=ASR/(f Aedge)",
         units="ρ: Ωm; H,t,ℓ: m; contact ASR: Ωmm²; Aedge: mm²", references=["Tranter2020"],
         assumption="各極の連続した片端面・一様注入。H=塗工幅、未塗工リード長0。箔は両塗工面共通で2倍しない。Al 2.82e−8 / Cu 1.68e−8 Ωmは室温の工学仮定。長手集電は理想比較のみで合計しない。接触率は接触項のみ変更。"),
    dict(id="performance", expression="ΔV=I Rohmic+Σηct; V=Uref−ΔV; P=IV; Qdot=IΔV; Enom=Qbalance Uref; td=r²/Ds",
         units="A, Ω, V → V, W, Wh; m, m²/s → s", references=["Bernardi1985", "Newman1995"],
         assumption="固定評価点の放電見積り。帳簿エネルギーは放電曲線の積分ではない。拡散時間を容量減衰係数に置換しない。"),
    dict(id="thermal", expression="ΔT=Qdot/(h Aext) × (1−exp(−h Aext tpulse/Cth)); Cth=m cp; h=0: ΔT=Qdot tpulse/Cth",
         units="W, W/K, J/K, s → K", references=["Bernardi1985"],
         assumption="初期温度=周囲温度、一定損失・一定物性の平均温度近似。濃度分極・可逆熱・局所温度を省略。"),
]


def analyze_design(r):
    c = r["input"]
    p, n = r["positive"], r["negative"]
    qp = r["capacity"]["positive_ah"] * c["positive_utilization"]
    qn = r["capacity"]["negative_overlap_ah"] * c["negative_utilization"]
    loss = qn * (1 / c["negative_first_cycle_efficiency"] - 1)
    balanced = max(0, min(qp - loss, qn))
    a = dict(version=VERSION, status="available", validation_status="analytical_unvalidated",
             references=deepcopy(REFERENCES), formulas=deepcopy(FORMULAS),
             capacity=dict(positive_usable_ah=qp, negative_usable_overlap_ah=qn,
                           limiting_electrode="positive" if qp <= qn else "negative",
                           formation_loss_ah=loss, inventory_limited_ah=balanced,
                           nominal_energy_wh=balanced * c["analysis_ocv_v"],
                           nominal_specific_energy_wh_kg=balanced * c["analysis_ocv_v"] / (r["total_mass_g"] / 1000),
                           nominal_energy_density_wh_l=balanced * c["analysis_ocv_v"] /
                                                       (math.pi * c["diameter_mm"] ** 2 / 4 * c["height_mm"] / 1e6)),
             provenance=dict(property_status="user_assumptions_not_literature_calibrated",
                             specific_capacities_mah_g={
                                 "positive": p["component_capacities_mah_g"][c["positive_material"]],
                                 "graphite": n["component_capacities_mah_g"]["graphite_demo"],
                                 "additive": n["component_capacities_mah_g"][c["negative_additive"]]},
                             applied_to_pybamm=False, checked_on="2026-10-16"),
             limitations=["文献は式と設計論の根拠。入力物性は仮定またはユーザー指定で、文献の実測校正値ではありません。",
                          "指定SOC相当のOCV・温度における静的近似。測定DCIR・EIS・寿命・析出開始を予測するものではありません。",
                          "i0・κ・σ・Dは指定温度での入力と解釈。温度による自動補正や濃度依存はありません。",
                          "SPMe/DFNの反応・輸送・OCV関数は文献セットを保持。比容量と利用率は設計容量を基準に選んだ場合に公称Cレート基準容量へ影響。ICE・集中抵抗・指定κ/i0/Dはソルバへ反映しません。"],
             warnings=[])
    if c["negative_first_cycle_efficiency"] < 1:
        a["warnings"].append(
            "ICEによるLi損失は形成窓全体の仮定帳簿です。初期Li充填率から算出した在庫とは結合していません。")
    if qp - loss <= 0:
        a["warnings"].append("形成損失仮定が正極供給容量以上です。Li帳簿の残容量は0です。")
    if c["negative_si"] > 0:
        a["warnings"].append("複合負極の反応・拡散は単一等価粒子の指定値です。黒鉛とSi/SiOxの相別反応は解きません。")
    material_rows = []
    for side, electrode in [("positive", p), ("negative", n)]:
        for part in electrode["components"]:
            material = part["id"]
            if part["mass_fraction"] == 0 or material in {"binder_demo", "carbon_demo"}:
                continue
            reaction = STOICHIOMETRY.get(material)
            theoretical = reaction[0] * FARADAY / (3.6 * reaction[1]) if reaction else None
            practical = electrode["component_capacities_mah_g"][material]
            material_rows.append(dict(side=side, material_id=material, label=r["materials"][material]["label"],
                                      reversible_capacity_mah_g=practical, theoretical_capacity_mah_g=theoretical,
                                      reaction=reaction[2] if reaction else "SiOxはxと反応機構が未指定",
                                      mass_g=part["mass_g"], contribution_ah=part["capacity_ah"]))
            if theoretical is not None and practical > theoretical:
                a["warnings"].append(
                    f"{material}の指定比容量が表示反応式の理論上限を超えています。入力の質量基準・反応式を確認してください。")
    a["capacity"]["materials"] = material_rows
    if min(c[k] for k in ["positive_porosity", "negative_porosity", "separator_porosity"]) <= 0 or c[
        "electrolyte_fill"] < 1:
        a.update(status="unavailable", resistance=None, performance=None,
                 reason="抵抗見積りは正負極・セパレータの空隙率>0、注液充填率=1が必要です。未含浸の有効輸送則は未実装です。")
        return a
    current = c["analysis_current_a"] if c["analysis_current_mode"] == "fixed_a" else c["analysis_c_rate"] * \
                                                                                      r["capacity"][
                                                                                          "c_rate_reference_ah"]
    area_m2 = p["area_cm2"] / 10000
    length_m = r["geometry"]["length_mm"] / 1000
    parts, transport, collectors, diffusion = [], {}, {}, {}

    def add(key, label, resistance, family, refs):
        parts.append(dict(id=key, label=label, resistance_mohm=resistance * 1000,
                          voltage_drop_v=current * resistance, heat_w=current ** 2 * resistance,
                          family=family, references=refs))

    for side, electrode, rho in [("positive", p, 2.82e-8), ("negative", n, 1.68e-8)]:
        label = "正極" if side == "positive" else "負極"
        thickness = c[side + "_thickness_um"] * 1e-6
        epsilon = c[side + "_porosity"]
        kappa = c["electrolyte_conductivity_s_m"] * epsilon ** c[side + "_bruggeman"]
        transport[side] = dict(effective_conductivity_s_m=kappa,
                               tortuosity_factor=epsilon ** (1 - c[side + "_bruggeman"]))
        add(side + "_electrolyte", label + "孔内イオン輸送", thickness / (3 * kappa * area_m2), "ohmic",
            ["DFN1993", "PyBaMMTransport"])
        add(side + "_solid", label + "固相電子伝導", thickness / (3 * c[side + "_conductivity_s_m"] * area_m2), "ohmic",
            ["DFN1993"])
        active_volume = (1 - epsilon) * sum(part["solid_volume_fraction"] for part in electrode["components"] if
                                            part["id"] not in {"binder_demo", "carbon_demo"})
        radius = c[side + "_particle_radius_um"] * 1e-6
        specific_area = 3 * active_volume / radius
        i0_total = c[side + "_exchange_current_a_m2"] * specific_area * thickness * area_m2
        rt_f = GAS_CONSTANT * (c["analysis_temperature_c"] + 273.15) / FARADAY
        r_ct = (2 * rt_f * math.asinh(current / (2 * i0_total)) / current if current > 0 else rt_f / i0_total)
        add(side + "_kinetics", label + "反応分極（指定電流の割線値）", r_ct, "kinetic", ["DFN1993"])
        diffusion[side] = dict(particle_diffusion_time_s=radius ** 2 / c[side + "_diffusivity_m2_s"],
                               active_surface_area_m2=specific_area * thickness * area_m2,
                               exchange_current_total_a=i0_total)
        foil_m = c[side + "_foil_um"] * 1e-6
        height_m = c[side + "_width_mm"] / 1000
        r_foil = rho * height_m / (3 * foil_m * length_m)
        edge_mm2 = foil_m * length_m * 1e6
        contact_mm2 = edge_mm2 * c[side + "_contact_fraction"]
        collectors[side] = dict(foil_edge_area_mm2=edge_mm2, effective_contact_area_mm2=contact_mm2,
                                foil_resistivity_ohm_m=rho,
                                ideal_longitudinal_reference_mohm=rho * length_m / (3 * foil_m * height_m) * 1000)
        add(side + "_foil", label + "連続端面集電箔", r_foil, "ohmic", ["Tranter2020"])
        add(side + "_contact", label + "箔端面接触", c[side + "_contact_asr_ohm_mm2"] / contact_mm2, "ohmic",
            ["Tranter2020"])
    ks = c["electrolyte_conductivity_s_m"] * c["separator_porosity"] ** c["separator_bruggeman"]
    transport["separator"] = dict(effective_conductivity_s_m=ks,
                                  tortuosity_factor=c["separator_porosity"] ** (1 - c["separator_bruggeman"]))
    add("separator", "セパレータのイオン輸送", c["separator_um"] * 1e-6 / (ks * area_m2), "ohmic", ["DFN1993"])
    add("film", "指定皮膜ASR（正負合計・幾何面積基準）", c["film_asr_ohm_cm2"] / p["area_cm2"], "ohmic", [])
    add("terminal", "端板・端子等の指定直列抵抗", c["terminal_resistance_mohm"] / 1000, "ohmic", [])
    total = sum(part["resistance_mohm"] for part in parts)
    drop = current * total / 1000
    voltage = c["analysis_ocv_v"] - drop
    heat = current * drop
    mass_kg = r["total_mass_g"] / 1000
    thermal_capacity = mass_kg * c["analysis_heat_capacity_j_kg_k"]
    d, h = c["diameter_mm"] / 1000, c["height_mm"] / 1000
    external_area = math.pi * d * h + math.pi * d ** 2 / 2
    cooling = c["analysis_heat_transfer_w_m2_k"] * external_area
    pulse = c["analysis_pulse_s"]
    rise = heat / cooling * -math.expm1(
        -cooling * pulse / thermal_capacity) if cooling > 0 else heat * pulse / thermal_capacity
    discharge_time = balanced / current * 3600 if current > 0 else None
    for value in diffusion.values():
        value["diffusion_to_discharge_time_ratio"] = value[
                                                         "particle_diffusion_time_s"] / discharge_time if discharge_time else None
    if voltage <= c["analysis_cutoff_v"]:
        a["warnings"].append("評価点の端子電圧が下限以下です。この電流で全設計容量を取り出せるとは扱えません。")
    if discharge_time is not None and pulse > discharge_time:
        a["warnings"].append("評価パルスが容量帳簿の放電時間を超えます。温度式は一定損失の外挿です。")
    a.update(
        resistance=dict(total_mohm=total, ohmic_mohm=sum(x["resistance_mohm"] for x in parts if x["family"] == "ohmic"),
                        kinetic_secant_mohm=sum(x["resistance_mohm"] for x in parts if x["family"] == "kinetic"),
                        components=parts, collectors=collectors, transport=transport),
        performance=dict(current_a=current, reference_c_rate=current / r["capacity"]["c_rate_reference_ah"],
                         voltage_drop_v=drop, terminal_voltage_v=voltage,
                         operating_power_w=current * voltage if voltage >= 0 else None,
                         irreversible_heat_w=heat, average_temperature_rise_k=rise,
                         temperature_after_pulse_c=c["analysis_temperature_c"] + rise,
                         voltage_headroom_v=voltage - c["analysis_cutoff_v"],
                         cutoff_reached=voltage <= c["analysis_cutoff_v"],
                         capacity_accounting_duration_s=discharge_time, diffusion=diffusion))
    return a


def sensitivity(r, evaluator):
    """One-at-a-time ±10%, re-fit geometry, no mutation, no full curve claim."""
    c = r["input"]
    capacities = r["analysis"]["provenance"]["specific_capacities_mah_g"]
    parameters = [
        ("positive_capacity_mah_g", "正極比容量", capacities["positive"]),
        ("graphite_capacity_mah_g", "黒鉛比容量", capacities["graphite"]),
        ("positive_thickness_um", "正極片面厚", c["positive_thickness_um"]),
        ("negative_thickness_um", "負極片面厚", c["negative_thickness_um"]),
        ("positive_porosity", "正極空隙率", c["positive_porosity"]),
        ("negative_porosity", "負極空隙率", c["negative_porosity"]),
        ("positive_foil_um", "Al箔厚", c["positive_foil_um"]),
        ("negative_foil_um", "Cu箔厚", c["negative_foil_um"]),
        ("separator_um", "セパレータ厚", c["separator_um"]),
        ("electrolyte_conductivity_s_m", "電解液導電率", c["electrolyte_conductivity_s_m"]),
        ("positive_contact_fraction", "正極接触率", c["positive_contact_fraction"]),
        ("negative_contact_fraction", "負極接触率", c["negative_contact_fraction"]),
        ("negative_particle_radius_um", "負極粒子半径", c["negative_particle_radius_um"]),
    ]
    rows = []
    baseline = _metrics(r)
    for key, label, base_value in parameters:
        for factor in (.9, 1.1):
            row = dict(parameter=key, label=label, factor=factor, baseline_value=base_value, value=base_value * factor)
            try:
                variant = evaluator(dict(c, **{key: row["value"]}), include_sensitivity=False)
                values = _metrics(variant)
                row.update(status=variant["analysis"]["status"], metrics=values,
                           delta={k: v - baseline[k] if v is not None and baseline[k] is not None else None for k, v in
                                  values.items()})
                if row["status"] != "available":
                    row["reason"] = variant["analysis"]["reason"]
            except ValueError as exc:
                row.update(status="invalid", reason=str(exc))
            rows.append(row)
    return dict(method="one_at_a_time_10_percent", baseline=baseline, rows=rows,
                comparison_basis="固定Aまたは固定Cレートは入力に従う。fitでは毎回巻回長を再計算。±10%は各1項目のみ変更。範囲外は省略せず理由表示。")


def _metrics(r):
    a = r["analysis"]
    resistance, performance = a["resistance"], a["performance"]
    return dict(design_ah=r["capacity"]["design_ah"], np_ratio=r["capacity"]["usable_np_ratio"],
                inventory_limited_ah=a["capacity"]["inventory_limited_ah"],
                specific_energy_wh_kg=a["capacity"]["nominal_specific_energy_wh_kg"],
                resistance_mohm=resistance["total_mohm"] if resistance else None,
                current_a=performance["current_a"] if performance else None,
                terminal_voltage_v=performance["terminal_voltage_v"] if performance else None,
                heat_w=performance["irreversible_heat_w"] if performance else None,
                winding_length_mm=r["geometry"]["length_mm"])
