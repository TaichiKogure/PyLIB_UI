"""Contract and lifecycle checks; fake sleep worker only for cancellation/timeout."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError

from pylib_ui.physics import DEFAULTS, validate_request, validate_design
from pylib_ui.design import evaluate_design
from pylib_ui.jobs import PhysicsJobs, TERMINAL
from pylib_ui.storage import RunRepository
import test_simulation


class ContractTests(unittest.TestCase):
    def test_invalid_protocols_and_nonfinite_inputs(self):
        for changes in [[], {'extra': 1}, {'model': 'SPM'}, {'rtol': True}, {'initial_soc': float('nan')},
                        {'protocol': []}, {'protocol': [{'kind': 'cc', 'current_a': '1', 'duration_s': 10}]},
                        {'protocol': [{'kind': 'cv', 'voltage_v': 4.2, 'duration_s': 10, 'stop_current_a': 0}]},
                        {'protocol': [{'kind': 'profile', 'points': [[1, 1], [2, 1]]}]},
                        {'protocol': [{'kind': 'profile', 'points': [[0, 1], [0, 2]]}]},
                        {'protocol': [{'kind': 'profile', 'points': [[0, 1], [2, float('inf')]]}]},
                        {'protocol': [{'kind': 'rest', 'duration_s': 10000}], 'dt_s': .1},
                        {'parameter_set': 'Chen2020_composite'}, {'timeout_s': 0}, {'design_id': {}},
                        {'min_voltage_v': 4, 'max_voltage_v': 3.5}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_request(changes)
        c = validate_request({})
        c['protocol'][0]['current_a'] = 20
        self.assertEqual(DEFAULTS['protocol'][0]['current_a'], 1)

    def test_material_gates_and_design_mapping(self):
        base = validate_request({});
        validate_design(base, evaluate_design({}))
        for design in [evaluate_design({'positive_material': 'LFP_demo'}),
                       evaluate_design({'positive_material': 'NCA_demo'}),
                       evaluate_design({'electrolyte_fill': .5}),
                       evaluate_design({'negative_graphite': .86, 'negative_si': .1})]:
            with self.assertRaises(ValueError): validate_design(base, design)
        composite = validate_request({'model': 'DFN', 'parameter_set': 'Chen2020_composite'})
        validate_design(composite, evaluate_design({'negative_graphite': .86, 'negative_si': .1}))
        with self.assertRaises(ValueError): validate_design(composite, evaluate_design(
            {'negative_graphite': .86, 'negative_si': .1, 'negative_additive': 'SiOx_demo'}))


class SleepJobs(PhysicsJobs):
    def probe(self): return {'available': True, 'message': 'test double; not solver validation'}

    def worker_command(self, request, output): return [sys.executable, '-c', 'import time;time.sleep(30)']


class LifecycleTests(unittest.TestCase):
    def wait_state(self, jobs, jid, states, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            j = jobs.get(jid, 'default')
            if j['status'] in states: return j
            time.sleep(.03)
        self.fail('job did not reach ' + str(states))

    def test_queued_cancel_and_restart_recovery_and_single_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = RunRepository(Path(tmp) / 'runs.sqlite3');
            jobs = SleepJobs(repo, start=False)
            try:
                a = jobs.submit({});
                b = jobs.submit({})
                self.assertEqual(jobs.cancel(a['id'], 'default')['status'], 'cancelled')
                with self.assertRaises(ValueError):
                    SleepJobs(repo, start=False)
                other = repo.create_project('別')['id']
                with self.assertRaises(ValueError):
                    jobs.cancel(b['id'], other)
            finally:
                jobs.close()
            restarted = SleepJobs(repo, start=False)
            try:
                self.assertEqual(restarted.get(a['id'], 'default')['status'], 'cancelled')
                self.assertEqual(restarted.get(b['id'], 'default')['status'], 'interrupted')
                self.assertIsNone(repo.get(b['result_id']))
                # Simulate abrupt termination recovery (a queued row survived without close).
                c = restarted.submit({});
                c['status'] = 'running';
                repo.put_job(c)
            finally:
                restarted.close()
            c['status'] = 'running';
            repo.put_job(c)
            again = SleepJobs(repo, start=False)
            try:
                self.assertEqual(again.get(c['id'], 'default')['status'], 'interrupted')
            finally:
                again.close()

    def test_running_cancel_timeout_and_no_false_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = RunRepository(Path(tmp) / 'runs.sqlite3');
            jobs = SleepJobs(repo)
            try:
                a = jobs.submit({});
                self.wait_state(jobs, a['id'], {'running'})
                jobs.cancel(a['id'], 'default')
                self.assertEqual(self.wait_state(jobs, a['id'], TERMINAL)['status'], 'cancelled')
                b = jobs.submit({'timeout_s': 5})
                self.assertEqual(self.wait_state(jobs, b['id'], TERMINAL)['status'], 'timeout')
                self.assertEqual(repo.list(), [])
            finally:
                jobs.close()

    def test_missing_interpreter_rejects_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = RunRepository(Path(tmp) / 'runs.sqlite3');
            jobs = PhysicsJobs(repo, Path(tmp) / 'missing.exe', start=False)
            try:
                self.assertFalse(jobs.availability['available'])
                with self.assertRaises(ValueError):
                    jobs.submit({})
            finally:
                jobs.close()


class PhysicsHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_config_jobs_static_and_rejected_requests(self):
        for path in ['/physics.js', '/api/physics/config', '/api/jobs']:
            with self.request(path) as response: self.assertEqual(response.status, 200)
        for path, data in [('/api/jobs', {'input': {'model': 'invalid'}}), ('/api/jobs/cancel', {'id': 'missing'}),
                           ('/api/jobs', {'input': {}, 'project_id': 'missing'}),
                           ('/api/jobs', {'input': {}, 'command': 'bad'})]:
            with self.assertRaises(HTTPError) as error: self.request(path, data)
            self.assertEqual(error.exception.code, 400);
            error.exception.close()


if __name__ == '__main__': unittest.main()
