"""Versioned, stdlib-only P2 output contract. Spatial coordinates are metres."""
from copy import deepcopy

RESULT_VERSION = '1.0'
CORE = {
    'time_s': ('Time [s]', '時間', 's'), 'voltage_v': ('Terminal voltage [V]', '端子電圧', 'V'),
    'current_a': ('Current [A]', '電流（放電＋）', 'A'), 'soc': (None, '基準容量のSOC帳簿', '1'),
    'temperature_c': ('Volume-averaged cell temperature [K]', 'セル平均温度', 'degC'),
    'capacity_ah': ('Throughput capacity [A.h]', '絶対通過容量', 'Ah'),
    'energy_wh': ('Discharge energy [W.h]', '符号付きエネルギー', 'Wh'),
}
DIAGNOSTICS = {
    'surface_ocv_v': ('Surface open-circuit voltage [V]', '表面濃度OCV', 'V'),
    'reaction_overpotential_v': ('X-averaged reaction overpotential [V]', '反応過電圧（符号付き）', 'V'),
    'electrolyte_ohmic_loss_v': ('X-averaged electrolyte ohmic losses [V]', '電解液オーム損失（符号付き）', 'V'),
    'concentration_overpotential_v': ('X-averaged concentration overpotential [V]', '電解液濃度過電圧（符号付き）', 'V'),
    'solid_ohmic_loss_v': ('X-averaged solid phase ohmic losses [V]', '固相オーム損失（符号付き）', 'V'),
    'ohmic_heating_w': ('Ohmic heating [W]', 'オーム発熱', 'W'),
    'reaction_heating_w': ('Irreversible electrochemical heating [W]', '不可逆反応発熱', 'W'),
    'reversible_heating_w': ('Reversible heating [W]', '可逆反応熱', 'W'),
    'hysteresis_heating_w': ('Hysteresis electrochemical heating [W]', 'ヒステリシス発熱', 'W'),
    'mixing_heating_w': ('Heat of mixing [W]', '混合熱（現モデルでは無効）', 'W'),
    'total_heating_w': ('Total heating [W]', '全発熱', 'W'),
}
EXTRA = {
    'bulk_ocv_v': ('Bulk open-circuit voltage [V]', 'バルクOCV', 'V'),
    'negative_stoichiometry': ('Negative electrode stoichiometry', '負極平均化学量論', '1'),
    'positive_stoichiometry': ('Positive electrode stoichiometry', '正極平均化学量論', '1'),
    'negative_primary_stoichiometry': ('Negative electrode primary stoichiometry', '負極主相化学量論', '1'),
    'negative_secondary_stoichiometry': ('Negative electrode secondary stoichiometry', '負極副相化学量論', '1'),
    'negative_capacity_ah': ('Negative electrode capacity [A.h]', '負極理論容量', 'Ah'),
    'positive_capacity_ah': ('Positive electrode capacity [A.h]', '正極理論容量', 'Ah'),
    'lithium_capacity_ah': ('Total lithium capacity in particles [A.h]', '粒子内Li相当容量', 'Ah'),
    'reference_potential_v': ('Reference electrode potential [V]', '参照位置の電解液電位', 'V'),
    'positive_3e_v': ('Positive electrode 3E potential [V]', '正極−参照電極電位', 'V'),
    'negative_3e_v': ('Negative electrode 3E potential [V]', '負極−参照電極電位', 'V'),
}
SCALARS = {**CORE, **DIAGNOSTICS, **EXTRA}
DISTRIBUTIONS = {
    'electrolyte_concentration_x': ('Electrolyte concentration [mol.m-3]', '電解液濃度', 'mol/m3', 'x'),
    'electrolyte_potential_x': ('Electrolyte potential [V]', '電解液電位', 'V', 'x'),
    'negative_potential_x': ('Negative electrode potential [V]', '負極固相電位', 'V', 'x'),
    'positive_potential_x': ('Positive electrode potential [V]', '正極固相電位', 'V', 'x'),
    'negative_reaction_x': ('Negative electrode interfacial current density [A.m-2]', '負極反応電流密度', 'A/m2', 'x'),
    'positive_reaction_x': ('Positive electrode interfacial current density [A.m-2]', '正極反応電流密度', 'A/m2', 'x'),
    'temperature_x': ('Cell temperature [K]', '温度（モデルが一様なら一様値）', 'K', 'x'),
    'negative_particle_r': ('X-averaged negative particle concentration [mol.m-3]', '負極粒子濃度（x平均）', 'mol/m3',
                            'r'),
    'positive_particle_r': ('X-averaged positive particle concentration [mol.m-3]', '正極粒子濃度（x平均）', 'mol/m3',
                            'r'),
    'negative_primary_r': ('X-averaged negative primary particle concentration [mol.m-3]', '負極主相粒子濃度（x平均）',
                           'mol/m3', 'r'),
    'negative_secondary_r': ('X-averaged negative secondary particle concentration [mol.m-3]',
                             '負極副相粒子濃度（x平均）', 'mol/m3', 'r'),
}
DEFAULT_OUTPUT = dict(variables=list(DIAGNOSTICS) + list(EXTRA),
                      distributions=['electrolyte_concentration_x', 'negative_particle_r', 'positive_particle_r',
                                     'negative_primary_r', 'negative_secondary_r'], frames=21, max_nodes=80)


def catalog():
    return dict(version=RESULT_VERSION, core=list(CORE),
                scalars=[dict(id=k, source_variable=v[0], label=v[1], unit=v[2], dimensions=0,
                              required=k in CORE) for k, v in SCALARS.items()],
                distributions=[dict(id=k, source_variable=v[0], label=v[1], unit=v[2], dimensions=1,
                                    coordinate=v[3], coordinate_unit='m') for k, v in DISTRIBUTIONS.items()],
                defaults=deepcopy(DEFAULT_OUTPUT),
                note='取得不可と未選択を区別します。SPMのx系列や集中熱の温度分布はモデルの一様な縮約値です。局所精度・実測精度を示しません。')


def validate_output(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_OUTPUT):
        raise ValueError('結果出力設定の項目を確認してください。')
    output = deepcopy(DEFAULT_OUTPUT)
    output.update(deepcopy(value))
    for key, choices in [('variables', set(SCALARS) - set(CORE)), ('distributions', set(DISTRIBUTIONS))]:
        items = output[key]
        if not isinstance(items, list) or any(not isinstance(i, str) or i not in choices for i in items) or len(
                set(items)) != len(items):
            raise ValueError(f'{key}: 登録済みの結果変数を重複なしで指定してください。')
    for key, low, high in [('frames', 2, 61), ('max_nodes', 5, 80)]:
        if isinstance(output[key], bool) or not isinstance(output[key], int) or not low <= output[key] <= high:
            raise ValueError(f'{key}は{low}〜{high}の整数で指定してください。')
    return output
