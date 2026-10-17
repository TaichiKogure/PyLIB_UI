"""Native parameter construction, missing-property preflight and complete provenance."""
import math
from .materials import fingerprint, expression_tree, snapshot
from pathlib import Path
import sys
import ast
import operator
import hashlib
from copy import deepcopy


def bpx_parameters(pybamm, obj):
    # Isolated optional packages do not replace the pinned solver environment.
    vendor = Path(__file__).parents[1] / 'vendor/bpx'
    if str(vendor) not in sys.path: sys.path.append(str(vendor))
    from bpx import Function
    from importlib.metadata import version
    if version('bpx') != '1.1.1': raise ValueError('bpx_version_mismatch')
    original = Function.to_python_function

    def interpret(self, preamble=None):
        tree = expression_tree(str(self))
        functions = {n: getattr(pybamm if preamble else math, n) for n in ('exp', 'tanh', 'cosh')}
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
               ast.Pow: operator.pow}

        def run(node, x):
            if isinstance(node, ast.Expression): return run(node.body, x)
            if isinstance(node, ast.Constant): return node.value
            if isinstance(node, ast.Name): return x
            if isinstance(node, ast.UnaryOp): return -run(node.operand, x) if isinstance(node.op, ast.USub) else run(
                node.operand, x)
            if isinstance(node, ast.BinOp): return ops[type(node.op)](run(node.left, x), run(node.right, x))
            if isinstance(node, ast.Call): return functions[node.func.id](run(node.args[0], x))
            raise ValueError('unsupported_bpx_expression')

        return lambda x: run(tree, x)

    # Native BPX conversion uses this parser hook; uploaded text is never compiled.
    Function.to_python_function = interpret
    import pybamm.parameters.bpx as converter
    original_table = converter._interpolant_func

    def bounded_table(var, name, x, y):
        return pybamm.Interpolant(x, y, var, name=name, interpolator='linear', extrapolate=False)

    converter._interpolant_func = bounded_table
    try:
        parameters = pybamm.ParameterValues.create_from_bpx_obj(deepcopy(obj))
    finally:
        Function.to_python_function = original
        converter._interpolant_func = original_table
    return parameters


def build_parameters(pybamm, c):
    p = bpx_parameters(pybamm, c['material_settings']['bpx']) if c[
                                                                     'parameter_set'] == 'BPX' else pybamm.ParameterValues(
        c['parameter_set'])
    changes = c['material_settings']['overrides']
    diff = {}
    for key, value in changes.items():
        old = p.get(key)
        old = float(old) if isinstance(old, (int, float)) else dict(kind='bundled_function',
                                                                    name=getattr(old, '__name__', type(
                                                                        old).__name__)) if old is not None else None
        diff[key] = dict(before=old, after=value)
        if isinstance(value, dict):
            import numpy as np
            points = np.asarray(value['points'])

            def ocp(sto, points=points, name=key):
                return pybamm.Interpolant(points[:, 0], points[:, 1], sto, name=name, extrapolate=False)

            p.update({key: ocp}, check_already_exists=False)
        else:
            p.update({key: value}, check_already_exists=False)
    raw = c['material_settings'].get('bpx_original_text')
    return p, dict(base_set=c['parameter_set'],
                   source=c['material_settings']['source'] or 'PyBaMM bundled literature set',
                   differences=diff, snapshot_sha256=fingerprint(c['material_settings']),
                   base_inventory_sha256=fingerprint(snapshot()['sets'][c['parameter_set']]) if c[
                                                                                                    'parameter_set'] != 'BPX' else None,
                   bpx_original_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest() if raw is not None else None,
                   bpx_structured_sha256=fingerprint(c['material_settings']['bpx']) if c[
                                                                                           'parameter_set'] == 'BPX' else None,
                   validation_status='not_validated',
                   note='独自物性は文献基準セットへの明示差分。対象セルの実測校正は未実施。')


def preflight(pybamm, model, parameters):
    """Process every required model parameter before solving; never fill absent data."""
    missing = []
    for symbol in model.parameters:
        if isinstance(symbol, (pybamm.Parameter, pybamm.FunctionParameter)) and symbol.name not in parameters:
            missing.append(symbol.name)
    # Native processing simplifies zero terms before requiring their parameters.
    # A scan alone incorrectly rejects composite models with unused density nodes.
    try:
        parameters.process_model(model, inplace=False, delayed_variable_processing=True)
    except KeyError:
        raise ValueError('missing_material_parameters: ' + ', '.join(sorted(set(missing)))) from None


def half_cell_soh(pybamm, model, parameters, sub, initial_value):
    from pybamm.models.full_battery_models.lithium_ion.electrode_soh_half_cell import get_min_max_stoichiometries
    limits = get_min_max_stoichiometries(parameters, options=model.options)
    lo, hi = float(limits['x_0']), float(limits['x_100'])
    q = float(parameters.evaluate(model.param.p.prim.Q_init))
    sto = float(sub['Positive electrode stoichiometry'](float(sub.t[0])))
    capacity = q * (lo - hi)
    if capacity <= 0 or not all(math.isfinite(v) for v in [lo, hi, q, sto, capacity]): raise ValueError(
        'invalid_half_cell_soh')
    return dict(status='available', source='PyBaMM half-cell equilibrium stoichiometries', capacity_ah=capacity,
                negative_capacity_ah=None, positive_capacity_ah=q, cyclable_lithium_ah=None,
                initial_soc=(sto - lo) / (hi - lo), positive_window_capacity_ah=capacity,
                electrode_capacity_mismatch_ah=0.,
                voltage_window_v=[float(parameters['Lower voltage cut-off [V]']),
                                  float(parameters['Upper voltage cut-off [V]'])],
                native_variables=dict(positive_sto_soc0=lo, positive_sto_soc100=hi, positive_sto_initial=sto),
                note='Li金属対極の正極半セル平衡容量。全セルのLi在庫・SOH%とは異なります。')
