"""Runs only in the pinned research interpreter; no import from HTTP process."""
import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

from .physics import PINNED_PYBAMM, PHYSICS_VERSION, MESHES, DIAGNOSTICS, validate_request, validate_design


def solve(request):
    import numpy as np
    import pybamm
    if pybamm.__version__ != PINNED_PYBAMM:
        raise ValueError('pinned_version_mismatch')
    c = validate_request(request['input'])
    design = request.get('design_snapshot')
    validate_design(c, design)
    started = time.perf_counter()
    composite = c['parameter_set'] == 'Chen2020_composite'
    options = {'thermal': c['thermal'], 'calculate discharge energy': 'true',
               'calculate heat source for isothermal models': 'true'}
    if composite:
        options.update(
            {'particle phases': ('2', '1'), 'open-circuit potential': (('single', 'current sigmoid'), 'single')})
    model = getattr(pybamm.lithium_ion, c['model'])(options=options)
    parameters = pybamm.ParameterValues(c['parameter_set'])
    citations = list(parameters.get('citations', []))
    updates = {'Initial temperature [K]': c['initial_temp_c'] + 273.15,
               'Ambient temperature [K]': c['ambient_temp_c'] + 273.15,
               'Lower voltage cut-off [V]': c['min_voltage_v'], 'Upper voltage cut-off [V]': c['max_voltage_v']}
    limitations = ['PyBaMMの文献パラメータによる計算。対象セルの実測校正・予測精度検証は未実施。',
                   '局所端面集電、析出、劣化、缶の膨張・応力はこのアダプタでは計算しません。',
                   'SOCは初期SOC−符号付き通過容量/Cレート基準容量の帳簿値。相の化学量論SOCとは異なり、範囲外も切り捨てません。']
    if c['thermal'] == 'isothermal':
        limitations.append('等温では周囲温度をモデル温度とするPyBaMMの挙動。初期温度との緩和は集中熱を選択してください。')
    if design:
        d = design['input'];
        a = design['adapter_input']
        updates.update({'Electrode height [m]': a['electrode_height_m'], 'Electrode width [m]': a['electrode_width_m'],
                        'Number of electrodes connected in parallel to make a cell': a['parallel_electrodes'],
                        'Positive electrode thickness [m]': a['positive_thickness_m'],
                        'Negative electrode thickness [m]': a['negative_thickness_m'],
                        'Positive current collector thickness [m]': d['positive_foil_um'] * 1e-6,
                        'Negative current collector thickness [m]': d['negative_foil_um'] * 1e-6,
                        'Separator thickness [m]': d['separator_um'] * 1e-6,
                        'Positive electrode porosity': d['positive_porosity'],
                        'Negative electrode porosity': d['negative_porosity'],
                        'Separator porosity': d['separator_porosity'],
                        'Nominal cell capacity [A.h]': design['capacity']['c_rate_reference_ah'],
                        'Cell volume [m3]': math.pi * (d['diameter_mm'] / 1000) ** 2 / 4 * d['height_mm'] / 1000,
                        'Cell cooling surface area [m2]': math.pi * d['diameter_mm'] / 1000 * d[
                            'height_mm'] / 1000 + math.pi * (d['diameter_mm'] / 1000) ** 2 / 2})
        for side in ['Positive', 'Negative']:
            electrode = design[side.lower()]
            components = [p for p in electrode['components'] if p['id'] not in {'binder_demo', 'carbon_demo'}]
            porosity = d[side.lower() + '_porosity']
            if side == 'Negative' and composite:
                for phase, part in zip(['Primary', 'Secondary'], components):
                    updates[f'{phase}: {side} electrode active material volume fraction'] = part[
                                                                                                'solid_volume_fraction'] * (
                                                                                                        1 - porosity)
            else:
                updates[f'{side} electrode active material volume fraction'] = sum(
                    p['solid_volume_fraction'] for p in components) * (1 - porosity)
        limitations.extend(['設計寸法・空隙率・相体積分率を上書きした仮想セル。配合換算密度はStep2の仮定値。',
                            '反応・拡散・OCV等は指定文献セットを使用。設計の比容量・初期Li充填率・接触率はソルバへ転用せず、初期SOCから一貫した濃度を初期化。',
                            '負極余剰幅は1D重なり面積に縮約。局所的な余剰幅・巻回曲率・端面電流は解きません。'])
    if c['thermal'] == 'lumped':
        updates['Total heat transfer coefficient [W.m-2.K-1]'] = c['heat_transfer_w_m2_k']
        limitations.append(
            '温度は集中熱。端面接触抵抗の追加発熱は未導入。形状を上書きしても文献の熱物性を引き継ぐため未校正。')
    parameters.update(updates)
    steps = []
    for s in c['protocol']:
        common = dict(period=c['dt_s'], skip_ok=False, temperature=c['ambient_temp_c'] + 273.15)
        # Explicit events ensure experiment overrides cannot relax the UI voltage limits.
        limits = [pybamm.step.VoltageTermination(c['min_voltage_v'], operator='<'),
                  pybamm.step.VoltageTermination(c['max_voltage_v'], operator='>')]
        if s['kind'] == 'cv':
            steps.append(pybamm.step.voltage(s['voltage_v'], duration=s['duration_s'],
                                             termination=[pybamm.step.CurrentTermination(s['stop_current_a'])],
                                             **common))
        elif s['kind'] == 'profile':
            steps.append(pybamm.step.current(np.asarray(s['points'], dtype=float), duration=s['points'][-1][0],
                                             termination=limits, **common))
        else:
            current = 0 if s['kind'] == 'rest' else s['current_a']
            if s.get('stop_voltage_v') is not None:
                limits.append(pybamm.step.VoltageTermination(s['stop_voltage_v'], operator='<' if current > 0 else '>'))
            steps.append(pybamm.step.current(current, duration=s['duration_s'], termination=limits, **common))
    nx, nr = MESHES[c['mesh']]
    var_pts = {'x_n': nx, 'x_s': nx, 'x_p': nx, 'r_n': nr, 'r_p': nr}
    if composite:
        var_pts.update(r_n_prim=nr, r_n_sec=nr)
    solver = pybamm.IDAKLUSolver(rtol=c['rtol'], atol=c['atol'], options={'num_threads': 1})
    sim = pybamm.Simulation(model, parameter_values=parameters, experiment=pybamm.Experiment([tuple(steps)]),
                            solver=solver, var_pts=var_pts)
    solution = sim.solve(initial_soc=c['initial_soc'], calc_esoh=False)
    subs = [step for cycle in solution.cycles if cycle is not None for step in cycle.steps if step is not None]
    points = [];
    step_results = []
    reference_capacity = float(parameters['Nominal cell capacity [A.h]'])

    def scalar(sub, key, t):
        v = np.asarray(sub[key](t)).reshape(-1)
        if v.size != 1 or not np.isfinite(v).all():
            raise ValueError('nonfinite_result')
        return float(v[0])

    for index, sub in enumerate(subs):
        t0 = float(sub.t[0]);
        end = float(sub.t[-1])
        # Keep both sides of step discontinuities and let segment_id break graph paths.
        times = np.append(np.arange(t0, end, c['dt_s']), end)
        if len(points) + len(times) > 12050:
            raise ValueError('output_limit')
        for t in times:
            signed = scalar(sub, 'Discharge capacity [A.h]', t)
            point = dict(time_s=float(t), voltage_v=scalar(sub, 'Terminal voltage [V]', t),
                         current_a=scalar(sub, 'Current [A]', t), soc=c['initial_soc'] - signed / reference_capacity,
                         temperature_c=scalar(sub, 'Volume-averaged cell temperature [K]', t) - 273.15,
                         capacity_ah=scalar(sub, 'Throughput capacity [A.h]', t),
                         energy_wh=scalar(sub, 'Discharge energy [W.h]', t),
                         segment_id=index)
            # Spatial extrema are diagnostics, not independent plating validation.
            for name, key, func in [('electrolyte_min_mol_m3', 'Electrolyte concentration [mol.m-3]', np.min),
                                    ('negative_surface_max_mol_m3', 'Negative particle surface concentration [mol.m-3]',
                                     np.max)] if not composite else [
                ('electrolyte_min_mol_m3', 'Electrolyte concentration [mol.m-3]', np.min)]:
                values = np.asarray(sub[key](t))
                if not np.isfinite(values).all():
                    raise ValueError('nonfinite_result')
                point[name] = float(func(values))
            points.append(point)
            for name, (key, _label, _unit) in DIAGNOSTICS.items():
                point[name] = scalar(sub, key, t)
        step_results.append(dict(index=index, start_s=t0, end_s=end, termination=str(sub.termination)))
    if not points:
        raise ValueError('empty_solution')
    last = points[-1]
    first_sub = subs[0];
    last_sub = subs[-1]
    start_time = float(first_sub.t[0]);
    end_time = float(last_sub.t[-1])
    initial_state = {'requested_soc': c['initial_soc']}
    for key in ['Total lithium in particles [mol]', 'Total lithium in electrolyte [mol]',
                'X-averaged positive particle surface stoichiometry'] + (
                       ['X-averaged negative primary particle surface stoichiometry',
                        'X-averaged negative secondary particle surface stoichiometry'] if composite else [
                           'X-averaged negative particle surface stoichiometry']):
        initial_state[key] = scalar(first_sub, key, start_time)
    initial_li = initial_state['Total lithium in particles [mol]'] + initial_state['Total lithium in electrolyte [mol]']
    final_li = scalar(last_sub, 'Total lithium in particles [mol]', end_time) + scalar(last_sub,
                                                                                       'Total lithium in electrolyte [mol]',
                                                                                       end_time)
    partial = len(subs) != len(steps) or any(
        s['termination'] != 'final time' and '[experiment]' not in s['termination'] for s in step_results)
    scalar_parameters = {k: float(v) for k, v in parameters.items() if isinstance(v, (int, float)) and math.isfinite(v)}
    diagnostics = {name: dict(source_variable=key, label=label, unit=unit,
                              initial=points[0][name], final=points[-1][name],
                              minimum=min(p[name] for p in points), maximum=max(p[name] for p in points))
                   for name, (key, label, unit) in DIAGNOSTICS.items()}
    descriptor = json.dumps(scalar_parameters, sort_keys=True, allow_nan=False)
    return dict(schema_version='3.0', record_type='physics', id=request['result_id'], project_id=request['project_id'],
                created_at=request['created_at'], name=c['name'], source_type='simulation',
                validation_status='not_validated',
                engine=dict(id='pybamm_' + c['model'].lower(), version=pybamm.__version__,
                            label='PyBaMM ' + c['model']),
                adapter_version=PHYSICS_VERSION, input=c, design_snapshot=design,
                model_options=options,
                parameter_provenance=dict(name=c['parameter_set'], package_version=pybamm.__version__,
                                          citations=citations,
                                          source='https://docs.pybamm.org/en/pybamm-v26.10.0.0/source/api/parameters/parameter_sets.html',
                                          overrides=updates, numeric_parameters=scalar_parameters,
                                          numeric_parameters_sha256=hashlib.sha256(descriptor.encode()).hexdigest()),
                initial_state=initial_state,
                lithium_balance=dict(initial_mol=initial_li, final_mol=final_li,
                                     relative_change=(final_li - initial_li) / initial_li),
                numerical=dict(solver='IDAKLUSolver', mesh_points=var_pts, rtol=c['rtol'], atol=c['atol'],
                               elapsed_s=time.perf_counter() - started,
                               initialization='PyBaMM initial_soc / electrode SOH',
                               numeric_parameter_snapshot_stage='before initial_soc initialization; actual initial state is recorded separately'),
                diagnostic_summary=diagnostics,
                diagnostic_basis='Native signed PyBaMM variables; extrema over exported sample times. Isothermal heat sources are calculated; temperature is fixed. Heat of mixing and external end-face contact losses are excluded.',
                units=dict({name: value[2] for name, value in DIAGNOSTICS.items()}, time_s='s', voltage_v='V',
                           current_a='A', soc='1', temperature_c='degC', capacity_ah='Ah',
                           energy_wh='Wh',
                           electrolyte_min_mol_m3='mol/m3', negative_surface_max_mol_m3='mol/m3', segment_id='1'),
                sign_convention='current_a and energy_wh: discharge positive, charge negative; capacity_ah: absolute throughput',
                termination='partial' if partial else 'protocol_complete', solver_termination=str(solution.termination),
                step_results=step_results, limitations=limitations, points=points,
                summary=dict(duration_s=last['time_s'], capacity_ah=last['capacity_ah'], energy_wh=last['energy_wh'],
                             final_soc=last['soc'], final_voltage_v=last['voltage_v'],
                             max_temperature_c=max(p['temperature_c'] for p in points),
                             point_count=len(points), c_rate_reference_ah=reference_capacity))


def main():
    parser = argparse.ArgumentParser();
    parser.add_argument('--request', type=Path, required=True);
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding='utf-8'))
        payload = {'ok': True, 'result': solve(request)}
    except Exception as error:
        # No arbitrary exception text is sent to the browser (paths/auth/env can appear in third-party errors).
        reason = str(error).lower()
        code = 'initial_condition_infeasible' if 'initial' in reason and (
                    'infeasible' in reason or 'non-positive' in reason or 'termination' in reason) else 'solver_failed'
        payload = {'ok': False, 'error_code': code, 'error_type': type(error).__name__}
        import traceback
        traceback.print_exc()
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8');
    temp.replace(args.output)


if __name__ == '__main__':
    main()
