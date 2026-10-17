"""Check every P0 registered combination using isolated real worker jobs."""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.capabilities import COMBINATIONS as ALL_COMBINATIONS, CONFIG_SCHEMA_VERSION

COMBINATIONS = tuple(c for c in ALL_COMBINATIONS if c['parameter_set'] in {'Chen2020', 'Chen2020_composite'})
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.storage import RunRepository


def main():
    report = {'scope': 'All current registered routes, real pinned solvers; no measured-cell accuracy validation',
              'cases': []}
    with tempfile.TemporaryDirectory(prefix='p0-solver-', dir=Path('.test_tmp').resolve()) as directory:
        repo = RunRepository(Path(directory) / 'runs.sqlite3')
        jobs = PhysicsJobs(repo)
        try:
            assert jobs.availability['available'], jobs.availability
            report['environment'] = jobs.availability
            for combination in COMBINATIONS:
                config = dict(combination, dt_s=5, protocol=[dict(kind='cc', current_a=1, duration_s=20)])
                if combination['parameter_set'] == 'Chen2020_composite' and combination['thermal'] == 'lumped':
                    config['thermal_settings'] = dict(capacity_mode='user', cell_heat_capacity_j_k=50,
                                                      source='synthetic verification fixture')
                job = jobs.submit(config)
                deadline = time.monotonic() + 130
                while time.monotonic() < deadline:
                    current = jobs.get(job['id'], 'default')
                    if current['status'] in TERMINAL: break
                    time.sleep(.1)
                assert current['status'] == 'completed', current
                result = repo.get(job['result_id'])
                assert result['numerical']['solver'] == combination['solver']
                assert result['input']['config_schema_version'] == CONFIG_SCHEMA_VERSION
                expected = hashlib.sha256(
                    json.dumps(result['input'], sort_keys=True, allow_nan=False).encode()).hexdigest()
                assert result['input_sha256'] == expected
                assert result['model_options']['thermal'] == combination['thermal']
                assert all(p['current_a'] > 0 for p in result['points'])
                assert abs(result['summary']['duration_s'] - 20) < 1e-6
                report['cases'].append(dict(combination=combination, status=current['status'],
                                            summary=result['summary'], model_options=result['model_options'],
                                            input_sha256=result['input_sha256']))
                print(str(combination) + ': completed', flush=True)
        finally:
            jobs.close()
    report['passed'] = True
    path = Path('docs/evidence/p0/registered-combinations.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
