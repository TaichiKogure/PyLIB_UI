"""Trusted protocol-to-PyBaMM factories and sanitized callback progress."""
import json
import time
from datetime import datetime

from .protocol import expand_protocol, preview_protocol


def build_experiment(pybamm, config, design):
    import numpy as np
    preview = preview_protocol(config, design)
    cycles = []

    class RelaxationControl(pybamm.external_circuit.FunctionControl):
        def set_initial_conditions(self, variables):
            self.initial_conditions[variables['Current variable [A]']] = pybamm.Scalar(0)

    class RelaxationStep(pybamm.step.CustomStepImplicit):
        def basic_repr(self):
            return super().basic_repr() + '|' + self.description

        def get_submodel(self, model):
            return RelaxationControl(model.param, self.current_rhs_function, model.options, control='differential')

        def copy(self):
            return RelaxationStep(self.current_rhs_function, control='differential', **self.kwargs)

    class RegisteredExplicitStep(pybamm.step.CustomStepExplicit):
        def basic_repr(self):
            return super().basic_repr() + '|' + self.description

        def copy(self):
            return RegisteredExplicitStep(self.current_value_function, **self.kwargs)

    for cycle_i, cycle in enumerate(expand_protocol(config)):
        steps = []
        for step_i, item in enumerate(cycle):
            s = item['step']
            common = dict(duration=item['duration_s'], period=item['period_s'],
                          skip_ok=s.get('skip_ok', False), tags=s.get('tags', []),
                          temperature=s.get('temperature_c', config['ambient_temp_c']) + 273.15)
            if config['start_time'] and cycle_i == 0 and step_i == 0:
                common['start_time'] = datetime.fromisoformat(config['start_time'])
            limits = [pybamm.step.VoltageTermination(config['min_voltage_v'], operator='<'),
                      pybamm.step.VoltageTermination(config['max_voltage_v'], operator='>')]
            kind = s['kind']
            if kind == 'cv':
                cutoff = s.get('stop_current_a', s.get('stop_c_rate', 0) * preview['c_rate_reference_ah'])
                steps.append(
                    pybamm.step.voltage(s['voltage_v'], termination=limits + [pybamm.step.CurrentTermination(cutoff)],
                                        **common))
                continue
            if kind in {'cc', 'c_rate', 'rest'}:
                value = s.get('current_a', s.get('c_rate', 0)) if kind != 'rest' else 0
                factory = pybamm.step.c_rate if kind == 'c_rate' else pybamm.step.current
            elif kind == 'profile':
                value = np.asarray(s['points'], dtype=float)
                factory = pybamm.step.current
            else:
                value = s['power_w'] if kind == 'cp' else s['resistance_ohm']
                mode = s.get('control', 'implicit')
                if mode == 'implicit':
                    factory = pybamm.step.power if kind == 'cp' else pybamm.step.resistance
                else:
                    # A fixed, auditable control law, never caller-provided source.
                    target = (lambda v, p=value: p / v['Voltage [V]']) if kind == 'cp' else (
                        lambda v, r=value: v['Voltage [V]'] / r)
                    if mode == 'explicit':
                        factory = RegisteredExplicitStep
                        value = target
                    else:
                        tau = s.get('control_tau_s', 1)
                        value = lambda v, target=target, tau=tau: (target(v) - v['Current [A]']) / tau
                        factory = RelaxationStep
                    common.update(
                        description=f'{kind}/{mode}/{s.get("power_w", s.get("resistance_ohm"))}/{s.get("control_tau_s", 1)}',
                        direction='discharge' if (s.get('power_w', s.get('resistance_ohm'))) > 0 else 'charge')
                limits += [pybamm.step.CurrentTermination(25.000001, operator='>'),
                           pybamm.step.CurrentTermination(-25.000001, operator='<')]
            if s.get('stop_voltage_v') is not None:
                sign = s.get('current_a', s.get('c_rate', s.get('power_w', s.get('resistance_ohm', 0))))
                limits.append(pybamm.step.VoltageTermination(s['stop_voltage_v'], operator='<' if sign > 0 else '>'))
            if kind in {'cp', 'cr'} and s.get('control') == 'differential': common['control'] = 'differential'
            steps.append(factory(value, termination=limits, **common))
        cycles.append(tuple(steps))
    return pybamm.Experiment(cycles), preview


def progress_callback(pybamm, preview, path=None):
    class Progress(pybamm.callbacks.Callback):
        def __init__(self):
            self.events = []
            self.completed = 0
            self.cycle_numbers = []
            self.ended_steps = set()
            self.failed = False
            self.step_start_s = 0
            self.started = time.monotonic()

        def emit(self, event, logs):
            cycle, cycles = logs.get('cycle number', (0, preview['cycles']))
            step, steps = logs.get('step number', (0, len(preview['steps']) // preview['cycles']))
            if event == 'step_end':
                self.completed += 1
                self.ended_steps.add((cycle, step))
            item = dict(sequence=len(self.events) + 1, event=event, cycle=cycle, cycles=cycles,
                        step=step, steps_per_cycle=steps, completed_steps=self.completed,
                        total_steps=preview['total_steps'], elapsed_s=time.monotonic() - self.started,
                        simulated_time_s=float(logs.get('experiment time', 0)))
            self.events.append(item)
            if path:
                try:
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(item, allow_nan=False), encoding='utf-8')
                    temp.replace(path)
                except OSError:
                    pass  # Progress is best effort; solver/result persistence is authoritative.

        def on_experiment_start(self, logs):
            self.emit('experiment_start', logs)

        def on_cycle_start(self, logs):
            self.emit('cycle_start', logs)

        def on_step_start(self, logs):
            self.step_start_s = float(logs.get('experiment time', 0))
            self.emit('step_start', logs)

        def on_step_end(self, logs):
            cycle, _ = logs['cycle number']
            step, per_cycle = logs['step number']
            expected = preview['steps'][(cycle - 1) * per_cycle + step - 1]
            if float(logs['experiment time']) <= self.step_start_s + 1e-9 and not expected['skip_ok']:
                raise ValueError('initial condition infeasible: forbidden skip')
            self.emit('step_end', logs)

        def on_cycle_end(self, logs):
            self.cycle_numbers.append(logs['cycle number'][0])
            self.emit('cycle_end', logs)

        def on_experiment_end(self, logs):
            self.emit('postprocess', logs)

        def on_experiment_error(self, logs):
            self.failed = True
            self.emit('solver_error', logs)

        def on_experiment_infeasible_time(self, logs):
            self.failed = True
            self.emit('infeasible_time', logs)

        def on_experiment_infeasible_event(self, logs):
            self.failed = True
            self.emit('infeasible_event', logs)

    return Progress()
