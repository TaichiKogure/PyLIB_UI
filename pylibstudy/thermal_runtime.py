"""Pinned native thermal wiring and independent sampled energy accounting."""
import math


def configure_thermal(pybamm, model, parameters, config, updates, design):
    t = config['thermal_settings']
    if t['cell_volume_m3'] is not None: updates['Cell volume [m3]'] = t['cell_volume_m3']
    if t['cooling_area_m2'] is not None: updates['Cell cooling surface area [m2]'] = t['cooling_area_m2']
    parameters.update(updates)
    volume = float(parameters['Cell volume [m3]']) if 'Cell volume [m3]' in parameters else None
    area = float(
        parameters['Cell cooling surface area [m2]']) if 'Cell cooling surface area [m2]' in parameters else None
    if config['thermal'] == 'lumped' and (volume is None or area is None):
        raise ValueError('missing_thermal_geometry')
    thermal_updates = {}
    if config['thermal'] == 'lumped':
        thermal_updates['Total heat transfer coefficient [W.m-2.K-1]'] = config['heat_transfer_w_m2_k']
        if t['capacity_mode'] == 'user':
            thermal_updates['Cell heat capacity [J.K-1.m-3]'] = t['cell_heat_capacity_j_k'] / volume
        if t['surface_temperature'] == 'lumped':
            thermal_updates.update({'Casing heat capacity [J.K-1]': t['casing_heat_capacity_j_k'],
                                    'Environment thermal resistance [K.W-1]': t['environment_thermal_resistance_k_w']})
    thermal_updates['Contact resistance [Ohm]'] = t['contact_resistance_ohm']
    # Only registered P3 parameters may be added when absent in a literature set.
    parameters.update(thermal_updates, check_already_exists=False)
    updates.update(thermal_updates)
    if config['thermal'] == 'lumped':
        cpv = float(parameters.evaluate(model.param.cell_heat_capacity if t['capacity_mode'] == 'user'
                                        else model.param.rho_c_p_eff(pybamm.Scalar(config['initial_temp_c'] + 273.15))))
        if not math.isfinite(cpv) or cpv <= 0: raise ValueError('invalid_thermal_capacity')
        capacity = cpv * volume
    else:
        capacity = None
    material = config.get('material_settings', {})
    material_overrides = material.get('overrides', {})
    geometry_basis = dict(volume='explicit_user' if t[
                                                        'cell_volume_m3'] is not None else 'saved_design_dimensions' if design else 'material_override' if 'Cell volume [m3]' in material_overrides else 'not_available' if volume is None else 'BPX' if
    config['parameter_set'] == 'BPX' else 'literature_parameter_set',
                          area='explicit_user' if t[
                                                      'cooling_area_m2'] is not None else 'saved_design_dimensions' if design else 'material_override' if 'Cell cooling surface area [m2]' in material_overrides else 'not_available' if area is None else 'BPX' if
                          config['parameter_set'] == 'BPX' else 'literature_parameter_set')
    return dict(version='1.0', model=config['thermal'], settings=dict(t),
                cell_volume_m3=volume, cooling_area_m2=area, geometry_basis=geometry_basis,
                cell_heat_capacity_initial_j_k=capacity,
                capacity_basis='explicit_user_cell_capacity' if t[
                                                                    'capacity_mode'] == 'user' else 'literature_layer_density_specific_heat_thickness',
                capacity_note='熱容量は文献層別値または明示入力。設計の質量×仮定比熱・接触率・ASRは転用しません。',
                parameter_overrides=thermal_updates,
                source=t['source'] or material.get('source') or config['parameter_set'] + ' bundled thermal parameters',
                boundary_equations=['C_cell dT/dt = Q_electrochemical + I²R_contact + h A (T_surface - T)',
                                    'C_surface dT_surface/dt = -h A (T_surface - T) + (T_ambient - T_surface)/R_environment']
                if t['surface_temperature'] == 'lumped' else
                ['C_cell dT/dt = Q_electrochemical + I²R_contact + h A (T_ambient - T)'],
                note='接触抵抗はセル全体の電気抵抗。正負極3E電位差は接触抵抗手前の電圧で、端子電圧はそこからI Rを引いた値。端面・タブの局所発熱分布や熱接触抵抗は未計算。外側ノードはモデル上の表面/環境で、実缶温度として未校正。')


def add_thermal_variables(pybamm, model, config):
    """Explicitly name electrical contact heat outside native Total heating."""
    t = config['thermal_settings']
    current = model.variables['Current [A]']
    contact_heat = current ** 2 * t['contact_resistance_ohm']
    model.variables['Adapter contact heating [W]'] = contact_heat
    model.variables['Adapter contact voltage loss [V]'] = -current * t['contact_resistance_ohm']
    if 'Total heating [W]' in model.variables:
        model.variables['Adapter total heat including contact [W]'] = model.variables[
                                                                          'Total heating [W]'] + contact_heat


def thermal_summary(actual, config, provenance):
    import numpy as np
    if config['thermal'] != 'lumped':
        return dict(status='not_applicable',
                    reason='等温では蓄熱・冷却の微分方程式を解きません。熱源の有効/無効は設定に記録します。')
    volume = provenance['cell_volume_m3']
    totals = dict(electrochemical_heat_j=0., contact_heat_j=0., cell_boundary_heat_j=0.,
                  environment_heat_j=0., cell_stored_energy_j=0., surface_stored_energy_j=0.)
    count = 0
    two_node = config['thermal_settings']['surface_temperature'] == 'lumped'
    for _, sub in actual:
        # Integrate inside each step; no interpolation across protocol discontinuities.
        times = np.linspace(float(sub.t[0]), float(sub.t[-1]), 501)

        def read(name):
            values = np.asarray(sub[name](times), dtype=float).reshape(-1)
            if values.size == 1: values = np.full(len(times), values[0])
            if values.size != len(times) or not np.isfinite(values).all(): raise ValueError('invalid_thermal_series')
            return values

        temp = read('Volume-averaged cell temperature [K]')
        capacity = read('Volume-averaged effective heat capacity [J.K-1.m-3]') * volume
        if np.any(capacity <= 0): raise ValueError('invalid_thermal_capacity')
        totals['cell_stored_energy_j'] += float(np.sum((capacity[1:] + capacity[:-1]) / 2 * np.diff(temp)))
        for key, name in [('electrochemical_heat_j', 'Total heating [W]'),
                          ('contact_heat_j', 'Lumped contact resistance heating [W]'),
                          ('cell_boundary_heat_j', 'Surface total cooling [W]')]:
            totals[key] += float(np.trapezoid(read(name), times))
        if two_node:
            surface = read('Surface temperature [K]')
            totals['surface_stored_energy_j'] += config['thermal_settings']['casing_heat_capacity_j_k'] * float(
                surface[-1] - surface[0])
            totals['environment_heat_j'] += float(np.trapezoid(read('Environment total cooling [W]'), times))
        else:
            totals['environment_heat_j'] = totals['cell_boundary_heat_j']
        count += len(times)
    generated = totals['electrochemical_heat_j'] + totals['contact_heat_j']
    cell_residual = totals['cell_stored_energy_j'] - generated - totals['cell_boundary_heat_j']
    system_residual = totals['cell_stored_energy_j'] + totals['surface_stored_energy_j'] - generated - totals[
        'environment_heat_j']
    tolerance = max(.005,
                    .002 * max(abs(generated), abs(totals['environment_heat_j']), abs(totals['cell_stored_energy_j'])))
    return dict(status='available', **totals, cell_residual_j=cell_residual, system_residual_j=system_residual,
                tolerance_j=tolerance, passed=max(abs(cell_residual), abs(system_residual)) <= tolerance,
                quadrature_points=count,
                method='Per executed step: 501 equally spaced native-solution samples; trapezoidal Q dt and C(T) dT. No step-boundary integration.',
                sign='Heat into each node is positive. Native cooling is negative when the cell is hotter.',
                note='数値積分による熱収支確認。許容差=max(0.005 J, エネルギー尺度の0.2%)。実測精度・局所温度の検証ではありません。')
