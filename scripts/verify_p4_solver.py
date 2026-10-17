"""P4 real isolated workers, persistence, capacity and stoichiometry checks."""
import argparse, copy, json, time, tempfile, sys, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.storage import RunRepository
from pylibstudy.materials import CHOICES, fingerprint


def main():
    parser = argparse.ArgumentParser();
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/p4'));
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(scope='Native pinned numerical checks and isolated persistence; no measured-cell calibration',
                  cases={})
    with tempfile.TemporaryDirectory(prefix='p4-', dir=Path('.test_tmp').resolve()) as temp:
        repo = RunRepository(Path(temp) / 'runs.sqlite3');
        jobs = PhysicsJobs(repo)

        def run(name, changes):
            c = dict(name=name,
                     protocol=[dict(kind='c_rate', c_rate=.2, duration_s=20), dict(kind='rest', duration_s=5),
                               dict(kind='c_rate', c_rate=-.2, duration_s=20)], dt_s=1)
            c.update(copy.deepcopy(changes));
            job = jobs.submit(c)
            deadline = time.monotonic() + 200
            while time.monotonic() < deadline:
                current = jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.05)
            assert current['status'] == 'completed', (name, current)
            r = repo.get(job['result_id']);
            assert r
            assert r == RunRepository(repo.path).get(r['id'])
            assert all(math.isfinite(p['voltage_v']) for p in r['points'])
            assert r['electrode_soh']['status'] == 'available', (name, r['electrode_soh'])
            assert abs(r['electrode_soh']['initial_soc'] - .5) < .002 if c.get('initial_ocv_v') is None else abs(
                r['points'][0]['soc'] - r['electrode_soh']['initial_soc']) < 1e-8
            assert abs(r['electrode_soh']['electrode_capacity_mismatch_ah']) < 1e-4
            polynomial = c.get('material_settings', {}).get('particle') in ('quadratic profile', 'quartic profile')
            if c.get('parameter_set') != 'Xu2019': assert abs(r['lithium_balance']['relative_change']) < (
                1e-4 if polynomial else 1e-5)
            for p in r['points']:
                if abs(p['current_a']) > 1e-10: assert abs(
                    abs(p['current_a']) - .2 * r['summary']['c_rate_reference_ah']) < 1e-7
            assert r['material_provenance']['snapshot_sha256'] == fingerprint(r['input']['material_settings'])
            for key, value in r['initial_state'].items():
                if 'stoichiometry' in key: assert 0 <= value <= 1
            (args.output / (name + '.json')).write_text(json.dumps(r, ensure_ascii=False, allow_nan=False, indent=2),
                                                        encoding='utf-8')
            report['cases'][name] = dict(summary=r['summary'], electrode_soh=r['electrode_soh'],
                                         lithium_balance=r['lithium_balance'], input=r['input'])
            print(name + ': passed', flush=True)
            return r

        try:
            assert jobs.availability['available'], jobs.availability
            for name, limits in [('Prada2013', (2., 3.6)), ('NCA_Kim2011', (2.7, 4.2))]:
                for model in ('SPM', 'SPMe', 'DFN'): run(name + '_' + model,
                                                         dict(parameter_set=name, model=model, min_voltage_v=limits[0],
                                                              max_voltage_v=limits[1]))
            half = run('half_cell',
                       dict(parameter_set='Xu2019', model='DFN', min_voltage_v=3.5, reference_electrode_fraction=None))
            assert half['lithium_balance']['scope'] == 'open_half_cell'
            run('half_cell_ocv',
                dict(parameter_set='Xu2019', model='DFN', min_voltage_v=3.5, reference_electrode_fraction=None,
                     initial_ocv_v=3.8))
            for particle in CHOICES['particle']:
                normal = run('particle_' + particle.replace(' ', '_'), dict(material_settings=dict(particle=particle)))
                if particle in ('quadratic profile', 'quartic profile'):
                    fine = run('particle_' + particle.replace(' ', '_') + '_fine',
                               dict(mesh='fine', material_settings=dict(particle=particle)))
                    assert abs(fine['lithium_balance']['relative_change']) < .4 * abs(
                        normal['lithium_balance']['relative_change'])
            for transport in CHOICES['transport']:
                overrides = {}
                if transport == 'tortuosity factor':
                    overrides = {'Separator tortuosity factor (electrolyte)': 2.}
                    for side in ('Negative', 'Positive'):
                        for phase in ('electrolyte', 'electrode'): overrides[
                            f'{side} electrode tortuosity factor ({phase})'] = 2.
                run('transport_' + transport.replace(' ', '_'), dict(
                    material_settings=dict(transport=transport, overrides=overrides,
                                           source='synthetic transport check, not measured')))
            for ocp in CHOICES['silicon_ocp']:
                overrides = {}
                if ocp != 'current sigmoid':
                    overrides['Secondary: Initial hysteresis state in negative electrode'] = 0.
                    if ocp == 'one-state hysteresis':
                        for direction in ('lithiation', 'delithiation'): overrides[
                            f'Secondary: Negative particle {direction} hysteresis decay rate'] = 50.
                    else:
                        overrides['Secondary: Negative particle hysteresis decay rate'] = 50.
                        overrides['Secondary: Negative particle hysteresis switching factor'] = 1.
                r = run('silicon_' + ocp.replace(' ', '_'), dict(model='DFN', parameter_set='Chen2020_composite',
                                                                 material_settings=dict(silicon_ocp=ocp,
                                                                                        source='synthetic hysteresis rates, uncalibrated',
                                                                                        overrides=overrides)))
                assert r['material_provenance']['differences'] if overrides else True
            for setting in ('diffusivity', 'exchange_current'):
                overrides = {}
                for side in ('Negative', 'Positive'):
                    for direction in ('lithiation', 'delithiation'):
                        key = f'{side} particle {direction} diffusivity [m2.s-1]' if setting == 'diffusivity' else f'{side} electrode {direction} exchange-current density [A.m-2]'
                        overrides[key] = 1e-14 if setting == 'diffusivity' else 3.
                run('directional_' + setting, dict(
                    material_settings={setting: 'current sigmoid', 'overrides': overrides,
                                       'source': 'synthetic direction check; not fitted'}))
            r = run('custom_capacity', dict(material_settings=dict(source='synthetic explicit capacity',
                                                                   overrides={'Nominal cell capacity [A.h]': 4.})))
            assert r['summary']['c_rate_reference_ah'] == 4
            import subprocess
            # A data-only OCP table derived from the bundled reference retains full stoichiometry range.
            cmd = "import pybamm,json,numpy as np;p=pybamm.ParameterValues('Chen2020');x=np.linspace(0,1,301);print(json.dumps([[float(s),float(p['Positive electrode OCP [V]'](s))] for s in x]))"
            points = json.loads(
                subprocess.check_output([str(jobs.python), '-c', cmd], env=jobs.environment(), text=True))
            interpolated = run('ocp_table', dict(
                material_settings=dict(source='sampled bundled Chen2020 OCP; interpolation check', overrides={
                    'Positive electrode OCP [V]': dict(kind='ocp_table', points=points)})))
            reference = json.loads((args.output / 'particle_Fickian_diffusion.json').read_text(encoding='utf-8'))
            assert max(
                abs(a['voltage_v'] - b['voltage_v']) for a, b in zip(interpolated['points'], reference['points'])) < .01
            changed = run('custom_diffusivity', dict(material_settings=dict(source='synthetic sensitivity check',
                                                                            overrides={
                                                                                'Positive particle diffusivity [m2.s-1]': 1e-15})))
            assert max(
                abs(a['voltage_v'] - b['voltage_v']) for a, b in zip(changed['points'], reference['points'])) > 1e-6
            obj = json.loads(Path('pylibstudy/data/bpx_reference.json').read_text(encoding='utf-8'))
            before = fingerprint(obj)
            r = run('bpx_reference', dict(model='DFN', parameter_set='BPX', min_voltage_v=2.7, material_settings=dict(
                source='pybamm-data v1.0.2; official BPX reference, thermal estimates', bpx=obj,
                bpx_original_text=Path('pylibstudy/data/bpx_reference.json').read_text(encoding='utf-8'))))
            assert fingerprint(r['input']['material_settings']['bpx']) == before
            assert r['summary']['c_rate_reference_ah'] == 12.5
            assert r['material_provenance'][
                       'bpx_original_sha256'] == 'cea07ea4fff9d667c2ad3fc430e699bb962a941051004dce52fddcd2d44ace3f'
            report['passed'] = True
        finally:
            jobs.close()
            (args.output / 'solver-integration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                                 encoding='utf-8')
    print('P4 passed:', len(report['cases']), flush=True)


if __name__ == '__main__': main()
