"""Exercise real PyBaMM processes for timeout, cancellation and shutdown recovery."""
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylib_ui.jobs import PhysicsJobs, TERMINAL
from pylib_ui.storage import RunRepository


def wait(jobs, jid, states, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        j = jobs.get(jid, 'default')
        if j['status'] in states: return j
        time.sleep(.05)
    raise AssertionError('wait exceeded')


def main():
    report = {'scope': 'Real solver subprocess lifecycle; no measured-data validation', 'cases': {}}
    with tempfile.TemporaryDirectory(prefix='step3-lifecycle-', dir=Path('.test_tmp').resolve()) as tmp:
        repo = RunRepository(Path(tmp) / 'runs.sqlite3');
        jobs = PhysicsJobs(repo)
        config = dict(model='DFN', mesh='fine', rtol=1e-8, atol=1e-8, dt_s=5,
                      protocol=[dict(kind='profile', points=[[10 * i, 1 if i % 2 == 0 else -1] for i in range(2000)])])
        try:
            job = jobs.submit(dict(config, timeout_s=5));
            result = wait(jobs, job['id'], TERMINAL)
            assert result['status'] == 'timeout', result
            assert repo.get(job['result_id']) is None
            report['cases']['timeout'] = dict(status=result['status'], elapsed_s=result['elapsed_s'],
                                              result_saved=False)
            job = jobs.submit(dict(config, timeout_s=120));
            wait(jobs, job['id'], {'running'})
            jobs.cancel(job['id'], 'default');
            result = wait(jobs, job['id'], TERMINAL)
            assert result['status'] == 'cancelled' and repo.get(job['result_id']) is None
            report['cases']['cancel'] = dict(status=result['status'], result_saved=False)
            job = jobs.submit(dict(config, timeout_s=120));
            wait(jobs, job['id'], {'running'})
        finally:
            jobs.close()
        again = PhysicsJobs(RunRepository(repo.path))
        try:
            result = again.get(job['id'], 'default')
            assert result['status'] == 'interrupted' and repo.get(job['result_id']) is None
            report['cases']['restart'] = dict(status=result['status'], result_saved=False)
        finally:
            again.close()
    report['passed'] = True
    path = Path('docs/evidence/step03/worker-lifecycle.json')
    path.parent.mkdir(parents=True, exist_ok=True);
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
