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

from .physics import PHYSICS_VERSION, MESHES, DIAGNOSTICS, validate_request, validate_design
from .capabilities import PINNED_PYBAMM, CATALOG_VERSION, build_model, build_solver
from .experiment_runtime import build_experiment, progress_callback
from .result_runtime import metadata, extract_scalars, extract_distributions, electrode_soh, citation_export
from .result_analysis import balance_summary


def solve(request, progress_path=None):
    import numpy as np
    import pybamm
    if pybamm.__version__ != PINNED_PYBAMM:
        raise ValueError('pinned_version_mismatch')
    c = validate_request(request['input'])
    design = request.get('design_snapshot')
    validate_design(c, design)
    started = time.perf_counter()
    composite = c['parameter_set'] == 'Chen2020_composite'
    model = build_model(pybamm, c)
    if c['reference_electrode_fraction'] is not None:
        model.insert_reference_electrode(model.param.n.L + c['reference_electrode_fraction'] * model.param.s.L)
    options = dict(model.options)
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
    experiment, preview = build_experiment(pybamm, c, design)
    if not math.isclose(float(parameters['Nominal cell capacity [A.h]']), preview['c_rate_reference_ah'],
                        rel_tol=1e-12):
        raise ValueError('capacity_reference_mismatch')
    if any(s['control'] == 'differential' for s in preview['steps']):
        limitations.append(
            '微分CP/CRはdI/dt=(目標電流−I)/時定数の定義済み追従制御。初回の電流状態は0 A、継続可能な電流状態は切替時に引き継ぎます。瞬時の定電力・定抵抗ではありません。')
    progress = progress_callback(pybamm, preview, progress_path)
    nx, nr = MESHES[c['mesh']]
    var_pts = {'x_n': nx, 'x_s': nx, 'x_p': nx, 'r_n': nr, 'r_p': nr}
    if composite:
        var_pts.update(r_n_prim=nr, r_n_sec=nr)
    solver = build_solver(pybamm, c)
    sim = pybamm.Simulation(model, parameter_values=parameters, experiment=experiment,
                            solver=solver, var_pts=var_pts)
    initial_value = f"{c['initial_ocv_v']} V" if c['initial_ocv_v'] is not None else c['initial_soc']
    solution = sim.solve(initial_soc=initial_value, calc_esoh=False, callbacks=progress)
    points = []
    step_results = [
        dict(row, status='skipped' if (row['cycle'], row['step_number']) in progress.ended_steps else 'not_run',
             termination='initial_condition_skip' if (row['cycle'],
                                                      row['step_number']) in progress.ended_steps else 'not_run')
        for row in preview['steps']]
    subs = []
    actual = []
    for cycle_i, cycle in zip(progress.cycle_numbers, solution.cycles):
        if cycle is None: continue
        for step_i, sub in enumerate(cycle.steps, 1):
            index = (cycle_i - 1) * (preview['total_steps'] // c['cycles']) + step_i - 1
            if sub is None or isinstance(sub, pybamm.EmptySolution): continue
            subs.append(sub)
            actual.append((index, sub))
    reference_capacity = float(parameters['Nominal cell capacity [A.h]'])

    def scalar(sub, key, t):
        v = np.asarray(sub[key](t)).reshape(-1)
        if v.size != 1 or not np.isfinite(v).all():
            raise ValueError('nonfinite_result')
        return float(v[0])

    if not actual: raise ValueError('all_steps_skipped')
    soh = electrode_soh(pybamm, model, parameters, actual[0][1], initial_value)
    ledger_initial_soc = c['initial_soc']
    if c['initial_ocv_v'] is not None:
        if soh['status'] != 'available': raise ValueError('initial_ocv_soc_unavailable')
        ledger_initial_soc = soh['initial_soc']
    variables = metadata(c)
    for index, sub in actual:
        t0 = float(sub.t[0]);
        end = float(sub.t[-1])
        times = np.append(np.arange(t0, end, step_results[index]['period_s']), end)
        if len(points) + len(times) > 12050: raise ValueError('output_limit')
        series = extract_scalars(sub, times, c, variables)
        signed = np.asarray(sub['Discharge capacity [A.h]'](times)).reshape(-1)
        for j, t in enumerate(times):
            point = dict(time_s=float(t), soc=ledger_initial_soc - float(signed[j]) / reference_capacity,
                         segment_id=index)
            for key, values in series.items(): point[key] = float(values[j])
            for key in c['output']['variables']:
                if key not in point: point[key] = None
            for name, key, func in [('electrolyte_min_mol_m3', 'Electrolyte concentration [mol.m-3]', np.min)] + (
            [] if composite else [
                ('negative_surface_max_mol_m3', 'Negative particle surface concentration [mol.m-3]', np.max)]):
                values = np.asarray(sub[key](t))
                if not np.isfinite(values).all(): raise ValueError('nonfinite_result')
                point[name] = float(func(values))
            points.append(point)
        step_results[index].update(status='completed', start_s=t0, end_s=end, termination=str(sub.termination))
    if not points:
        raise ValueError('all_steps_skipped')
    if any(s['status'] == 'skipped' and not s['skip_ok'] for s in step_results):
        raise ValueError('initial condition infeasible: forbidden skip')
    last = points[-1]
    first_sub = subs[0];
    last_sub = subs[-1]
    start_time = float(first_sub.t[0]);
    end_time = float(last_sub.t[-1])
    initial_state = {'requested_soc': c['initial_soc'] if c['initial_ocv_v'] is None else None,
                     'requested_ocv_v': c['initial_ocv_v'], 'ledger_initial_soc': ledger_initial_soc}
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
    partial = progress.failed or any(s['status'] == 'not_run' or (s['status'] == 'completed' and
                                                                  s[
                                                                      'termination'] != 'final time' and '[experiment]' not in
                                                                  s['termination']) for s in step_results)
    scalar_parameters = {k: float(v) for k, v in parameters.items() if isinstance(v, (int, float)) and math.isfinite(v)}
    for key in ('time_s', 'soc'): variables[key].update(status='available', reason='')
    diagnostics = {}
    for name, (key, label, unit) in DIAGNOSTICS.items():
        values = [p.get(name) for p in points]
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            diagnostics[name] = dict(source_variable=key, label=label, unit=unit, initial=values[0], final=values[-1],
                                     minimum=min(values), maximum=max(values))
    spatial = extract_distributions(actual, points, c)
    balances = balance_summary(points, ledger_initial_soc)
    descriptor = json.dumps(scalar_parameters, sort_keys=True, allow_nan=False)
    return dict(schema_version='3.1', record_type='physics', id=request['result_id'], project_id=request['project_id'],
                created_at=request['created_at'], name=c['name'], source_type='simulation',
                validation_status='not_validated',
                engine=dict(id='pybamm_' + c['model'].lower(), version=pybamm.__version__,
                            label='PyBaMM ' + c['model']),
                adapter_version=PHYSICS_VERSION, capability_catalog_version=CATALOG_VERSION,
                input_sha256=hashlib.sha256(json.dumps(c, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                input=c, design_snapshot=design,
                model_options=options, protocol_preview=preview, progress_events=progress.events,
                result_variables=variables, distributions=spatial, electrode_soh=soh, performance=balances,
                citation_export=citation_export(pybamm),
                experiment_metadata=dict(
                    initial_start_time=solution.initial_start_time.isoformat() if solution.initial_start_time else None,
                    tags=[s.tags for s in sim.experiment.steps],
                    periods_s=[s.period for s in sim.experiment.steps],
                    temperatures_k=[s.temperature for s in sim.experiment.steps]),
                parameter_provenance=dict(name=c['parameter_set'], package_version=pybamm.__version__,
                                          citations=citations,
                                          source='https://docs.pybamm.org/en/pybamm-v26.10.0.0/source/api/parameters/parameter_sets.html',
                                          overrides=updates, numeric_parameters=scalar_parameters,
                                          numeric_parameters_sha256=hashlib.sha256(descriptor.encode()).hexdigest()),
                initial_state=initial_state,
                lithium_balance=dict(initial_mol=initial_li, final_mol=final_li,
                                     relative_change=(final_li - initial_li) / initial_li),
                numerical=dict(solver=c['solver'], mesh_points=var_pts, rtol=c['rtol'], atol=c['atol'],
                               elapsed_s=time.perf_counter() - started,
                               initialization='PyBaMM initial_soc / electrode SOH',
                               numeric_parameter_snapshot_stage='before initial_soc initialization; actual initial state is recorded separately'),
                diagnostic_summary=diagnostics,
                diagnostic_basis='Native signed PyBaMM variables; extrema over exported sample times. Isothermal heat sources are calculated; temperature is fixed. Heat of mixing and external end-face contact losses are excluded.',
                units=dict({name: value['unit'] for name, value in variables.items()}, time_s='s', voltage_v='V',
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
    parser.add_argument('--progress', type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding='utf-8'))
        payload = {'ok': True, 'result': solve(request, args.progress)}
    except Exception as error:
        # No arbitrary exception text is sent to the browser (paths/auth/env can appear in third-party errors).
        reason = str(error).lower()
        code = 'initial_condition_infeasible' if 'initial' in reason and (
                'infeasible' in reason or 'non-positive' in reason or 'termination' in reason) else 'solver_failed'
        if 'all steps' in reason or 'all_steps_skipped' in reason:
            code = 'all_steps_skipped'
        payload = {'ok': False, 'error_code': code, 'error_type': type(error).__name__}
        import traceback
        traceback.print_exc()
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8');
    temp.replace(args.output)


if __name__ == '__main__':
    main()
