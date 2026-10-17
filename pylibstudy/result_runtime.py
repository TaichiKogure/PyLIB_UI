"""Pinned-worker extraction of native scalar, spatial and electrode-SOH data."""
import math

from .result_catalog import SCALARS, CORE, DISTRIBUTIONS, RESULT_VERSION


def metadata(config):
    return {key: dict(source_variable=source, label=label, unit=unit, dimensions=0,
                      status='pending' if key in CORE or key in config['output']['variables'] else 'not_selected',
                      reason='未選択' if key not in CORE and key not in config['output']['variables'] else '')
            for key, (source, label, unit) in SCALARS.items()}


def scalar_series(sub, times, key):
    import numpy as np
    value = np.asarray(sub[key](times), dtype=float).reshape(-1)
    if value.size != len(times) or not np.isfinite(value).all():
        raise ValueError('scalar_shape_or_nonfinite')
    return value


def extract_scalars(sub, times, config, meta):
    result = {}
    for key, item in meta.items():
        if item['status'] == 'not_selected' or key in {'time_s', 'soc'}: continue
        try:
            values = scalar_series(sub, times, item['source_variable'])
            if key == 'temperature_c': values = values - 273.15
            result[key] = values
            if item['status'] != 'unavailable': item.update(status='available', reason='')
        except (KeyError, ValueError, NotImplementedError):
            if key in CORE: raise
            item.update(status='unavailable',
                        reason='このモデル・物性・試験で変数が存在しないか、有限のスカラー系列として取得できません。')
    return result


def electrode_soh(pybamm, model, parameters, sub, initial_value):
    """A voltage-window equilibrium calculation, never a measured SOH percentage."""
    composite = model.options['particle phases'] == ('2', '1')
    try:
        if composite:
            raw = pybamm.lithium_ion.ElectrodeSOHComposite.solve_full(initial_value, parameters, param=model.param,
                                                                      options=model.options)
            capacities = [float(parameters.evaluate(model.param.n.prim.Q_init)),
                          float(parameters.evaluate(model.param.n.sec.Q_init))]
            qn = sum(capacities)
            qp = float(parameters.evaluate(model.param.p.prim.Q_init))
            q = sum(capacities[i - 1] * (float(raw[f'x_100_{i}']) - float(raw[f'x_0_{i}'])) for i in (1, 2))
            initial_soc = sum(
                capacities[i - 1] * (float(raw[f'x_init_{i}']) - float(raw[f'x_0_{i}'])) for i in (1, 2)) / q
            positive_window = qp * (float(raw['y_0_1']) - float(raw['y_100_1']))
            qli = float(sub['Total lithium capacity in particles [A.h]'](float(sub.t[0])))
        else:
            inputs = {key: float(sub[name](float(sub.t[0]))) for key, name in [
                ('Q_n', 'Negative electrode capacity [A.h]'), ('Q_p', 'Positive electrode capacity [A.h]'),
                ('Q_Li', 'Total lithium capacity in particles [A.h]')]}
            raw = pybamm.lithium_ion.ElectrodeSOHSolver(parameters, param=model.param, options=model.options).solve(
                inputs)
            q, qn, qp, qli = (float(raw[k]) for k in ('Q', 'Q_n', 'Q_p', 'Q_Li'))
            x_init = float(sub['Negative electrode stoichiometry'](float(sub.t[0])))
            initial_soc = (x_init - float(raw['x_0'])) / (float(raw['x_100']) - float(raw['x_0']))
            positive_window = qp * (float(raw['y_0']) - float(raw['y_100']))
        numeric = {key: float(value) for key, value in raw.items() if
                   isinstance(value, (int, float)) and math.isfinite(value)}
        if not all(math.isfinite(x) for x in [q, qn, qp, qli, initial_soc]) or q <= 0: raise ValueError('invalid_esoh')
        return dict(status='available',
                    source='PyBaMM ElectrodeSOHComposite.solve_full' if composite else 'PyBaMM ElectrodeSOHSolver',
                    capacity_ah=q, negative_capacity_ah=qn, positive_capacity_ah=qp, cyclable_lithium_ah=qli,
                    initial_soc=initial_soc, positive_window_capacity_ah=positive_window,
                    electrode_capacity_mismatch_ah=positive_window - q,
                    voltage_window_v=[float(parameters['Lower voltage cut-off [V]']),
                                      float(parameters['Upper voltage cut-off [V]'])],
                    native_variables=numeric,
                    note='指定電圧窓と文献物性による平衡容量・化学量論。定格容量・実測容量・寿命SOH(%)とは異なります。複合相・ヒステリシスの初期化はPyBaMMの定義に従います。')
    except Exception:
        return dict(status='unavailable',
                    reason='この条件で電極SOH補助モデルを解けませんでした。容量や化学量論を推定値で補いません。')


def extract_distributions(actual, points, config):
    import numpy as np
    selected = config['output']['distributions']
    point_ids = sorted(
        set(np.linspace(0, len(points) - 1, min(len(points), config['output']['frames']), dtype=int).tolist()))
    sources = dict(actual)
    output = {}
    for name, (source, label, unit, coordinate) in DISTRIBUTIONS.items():
        item = dict(source_variable=source, label=label, unit=unit, dimensions=1, coordinate=coordinate,
                    coordinate_unit='m', status='not_selected', reason='未選択')
        output[name] = item
        if name not in selected: continue
        frames = []
        try:
            coords = None
            for index in point_ids:
                point = points[index]
                variable = sources[point['segment_id']][source]
                if variable.dimensions != 1: raise ValueError('not_1d')
                native = np.asarray(variable.mesh.nodes, dtype=float)
                values = np.asarray(variable(float(point['time_s']), **{coordinate: native}), dtype=float).reshape(-1)
                if len(values) != len(native) or not np.isfinite(values).all() or not np.isfinite(native).all():
                    raise ValueError('spatial_shape_or_nonfinite')
                indices = np.unique(
                    np.linspace(0, len(native) - 1, min(len(native), config['output']['max_nodes']), dtype=int))
                sampled = native[indices].tolist()
                if coords is not None and coords != sampled: raise ValueError('changing_mesh')
                coords = sampled
                frames.append(dict(point_index=index, time_s=point['time_s'], segment_id=point['segment_id'],
                                   values=values[indices].tolist()))
            item.update(status='available', reason='', coordinates=coords, original_node_count=len(native),
                        node_indices=indices.tolist(), frames=frames, shape=[len(frames), len(coords)],
                        domains=variable.domains,
                        sampling='uniform output-point indices including endpoints; native mesh node selection, no spatial extrapolation',
                        note='x=電極厚さ方向、r=球形粒子の半径。r系列はx平均。SPMのx分布・等温/集中熱の温度分布は縮約モデルの一様値です。')
        except (KeyError, ValueError, NotImplementedError, AttributeError):
            item.update(status='unavailable',
                        reason='このモデルで対応する1次元変数・座標を取得できません。複合負極は主相/副相を個別に選択してください。')
    return dict(version=RESULT_VERSION, variables=output, max_values=61 * 80 * len(DISTRIBUTIONS),
                frame_selection=point_ids, coordinate_basis='native physical mesh coordinates in metres')


def citation_export(pybamm):
    """Use the pinned package's registered keys and bundled BibTeX without adding dependencies."""
    import hashlib
    import re
    from pathlib import Path
    try:
        source = (Path(pybamm.__file__).parent / 'CITATIONS.bib').read_bytes()
        text = source.decode('utf-8')
        starts = list(re.finditer(r'(?m)^@\w+\s*\{\s*([^,\s]+)\s*,', text))
        entries = {m.group(1): text[m.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
                   for i, m in enumerate(starts)}
        # Fixed 26.10.1.0 implementation: absent pybtex keeps registered keys in _unknown_citations.
        keys = sorted(k for k in (set(pybamm.citations._papers_to_cite) | set(pybamm.citations._unknown_citations))
                      if re.fullmatch(r'[A-Za-z0-9:_-]{1,100}', k))
        known = [k for k in keys if k in entries]
        return dict(status='available' if known else 'unavailable', bibtex='\n\n'.join(entries[k] for k in known),
                    keys=known, unresolved_keys=[k for k in keys if k not in entries],
                    method='registered keys from isolated pinned worker; verbatim entries in bundled CITATIONS.bib',
                    package_catalog_sha256=hashlib.sha256(source).hexdigest())
    except (OSError, AttributeError, UnicodeError):
        return dict(status='unavailable', bibtex=None,
                    reason='固定環境の登録済み引用と付属BibTeXを取得できません。物性出典キーは別途保持します。')
