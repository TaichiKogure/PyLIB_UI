"""P2 browser checks using a fresh native solver run and isolated storage."""
import copy
import json
import time
import unittest
from pathlib import Path

from playwright.sync_api import expect
from verify_model_tabs import ModelTabTests
from pylibstudy.jobs import TERMINAL
from pylibstudy.result_catalog import DISTRIBUTIONS


class P2BrowserTests(unittest.TestCase):
    output = Path('docs/evidence/p2')
    tearDownClass = classmethod(ModelTabTests.tearDownClass.__func__)
    setUp = ModelTabTests.setUp
    tearDown = ModelTabTests.tearDown

    @classmethod
    def setUpClass(cls):
        ModelTabTests.setUpClass.__func__(cls)
        cls.output.mkdir(parents=True, exist_ok=True)
        job = cls.server.jobs.submit(dict(name='P2 browser native SPMe', model='SPMe', protocol=[
            dict(kind='rest', duration_s=30), dict(kind='cc', current_a=1, duration_s=60),
            dict(kind='rest', duration_s=30)],
                                          output=dict(distributions=list(DISTRIBUTIONS), frames=9, max_nodes=15)))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = cls.server.jobs.get(job['id'], 'default')
            if current['status'] in TERMINAL: break
            time.sleep(.1)
        assert current['status'] == 'completed', current
        cls.native_run = cls.server.service.repository.get(job['result_id'])
        (cls.output / 'browser-native-run.json').write_text(json.dumps(cls.native_run, ensure_ascii=False, indent=2),
                                                            encoding='utf-8')
        text = 'time_s,voltage_v,current_a,temperature_c\n' + '\n'.join(
            f"{p['time_s']},{p['voltage_v'] + .01},{p['current_a']},{p['temperature_c']}" for p in
            cls.native_run['points'] if p['segment_id'] == 1)
        cls.dataset = cls.server.service.preview_import(dict(name='Synthetic solver +0.01 V fixture', text=text,
                                                             source_type='synthetic_demo',
                                                             source='Verification fixture derived from solver plus 0.01 V; not measured data',
                                                             mapping={k: dict(column=k, unit=u) for k, u in
                                                                      [('time_s', 's'), ('voltage_v', 'V'),
                                                                       ('current_a', 'A'), ('temperature_c', 'degC')]}))
        cls.server.service.save(cls.dataset['id'])
        cls.other = cls.server.service.repository.create_project('P2 isolation')['id']

    def open_run(self):
        self.page.evaluate('async id => showResult(await api(`/api/results/${id}`))', self.native_run['id'])
        self.page.locator('#result-explorer>summary').click()
        expect(self.page.locator('#result-postprocess')).to_be_enabled()

    def test_profiles_units_time_and_native_loss_components(self):
        self.open_run()
        self.page.locator('#result-variable').select_option('electrolyte_ohmic_loss_v')
        self.assertEqual(self.page.evaluate('state.variable'), 'electrolyte_ohmic_loss_v')
        self.page.locator('#result-loss-details>summary').click()
        expect(self.page.locator('#result-loss-chart svg')).to_have_count(1)
        self.page.locator('#result-time').fill('10')
        expect(self.page.locator('#result-time-label')).to_contain_text('区間 1')
        self.page.locator('#result-spatial-details>summary').click()
        expect(self.page.locator('#result-spatial-chart svg')).to_have_count(1)
        self.page.locator('#result-spatial-variable').select_option('negative_particle_r')
        first = self.page.locator('#result-spatial-chart path').get_attribute('d')
        self.page.locator('#result-spatial-time').fill('5')
        self.assertNotEqual(first, self.page.locator('#result-spatial-chart path').get_attribute('d'))
        expect(self.page.locator('#result-spatial-label')).to_contain_text('保存単位m、表示μm')
        expect(self.page.locator('#result-performance')).to_contain_text('eSOH平衡容量')
        expect(self.page.locator('#spatial-csv')).to_be_visible()
        for selector in ('#spatial-csv', '#citations-bib'):
            response = self.page.request.get(self.url + self.page.locator(selector).get_attribute('href'))
            self.assertEqual(response.status, 200)
            self.assertTrue(response.body())
        self.page.locator('#result-explorer').screenshot(path=str(self.output / 'result-desktop.png'))

    def test_postprocess_save_export_and_reload(self):
        self.open_run()
        self.page.locator('#result-smoothing').evaluate('(e)=>e.closest("details").open=true')
        self.page.locator('#result-smoothing').fill('3')
        self.page.locator('#result-postprocess').click()
        expect(self.page.locator('#result-analysis-status')).to_contain_text('保存済み解析')
        expect(self.page.locator('#result-derivative-chart svg')).to_have_count(1)
        expect(self.page.locator('#result-gitt-table tbody tr')).to_have_count(1)
        record = self.page.evaluate('resultView.analysis')
        self.assertTrue(any(p['resistance_ohm'] is not None for p in record['pulses']))
        csv = self.page.request.get(self.url + self.page.locator('#result-analysis-csv').get_attribute('href'))
        self.assertIn('dq_dv_ah_v', csv.text())
        download = self.page.request.get(self.url + self.page.locator('#result-analysis-json').get_attribute('href'))
        self.assertEqual(download.status, 200);
        self.assertEqual(download.json(), record)
        self.page.reload()
        expect(self.page.locator('#run')).to_be_enabled()
        self.open_run()
        self.page.locator('#result-analysis-history').select_option(record['id'])
        self.page.locator('#result-analysis-open').click()
        expect(self.page.locator('#result-analysis-status')).to_contain_text(record['id'])
        self.assertEqual(self.page.evaluate('resultView.analysis'), record)

    def test_known_residual_explicit_segments_and_mobile(self):
        self.open_run()
        self.page.locator('#result-residual-details>summary').click()
        self.page.locator('#result-sim-segment').select_option('1')
        self.page.locator('#result-measured').select_option(self.dataset['id'])
        self.page.locator('#result-compare').click()
        expect(self.page.locator('#result-analysis-status')).to_contain_text('保存済み解析')
        record = self.page.evaluate('resultView.analysis')
        self.assertAlmostEqual(record['metrics']['rmse'], .01)
        self.assertEqual(record['source_snapshots'][1]['source_type'], 'synthetic_demo')
        expect(self.page.locator('#result-condition-table')).to_contain_text('手動確認が必要')
        expect(self.page.locator('#result-residual-metrics')).to_contain_text('RMSE')
        expect(self.page.locator('#result-residual-chart svg')).to_have_count(1)
        self.page.set_viewport_size(dict(width=390, height=844))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#result-explorer').screenshot(path=str(self.output / 'result-mobile.png'))
        with self.server.service.repository.connect() as connection:
            count = connection.execute('SELECT COUNT(*) FROM result_analyses').fetchone()[0]
        self.assertGreaterEqual(count, 1)
        response = self.page.request.get(f"{self.url}/api/analyses/{record['id']}?project_id={self.other}")
        self.assertEqual(response.status, 400)
        self.page.select_option('#project', self.other)
        expect(self.page.locator('#result-explorer')).to_be_hidden()
        expect(self.page.locator('#result-analysis-json')).to_be_hidden()
        self.assertIsNone(self.page.evaluate('state.current'))

    def test_output_settings_and_legacy_restore(self):
        self.page.evaluate(
            'async () => restorePhysics({input:{...physical.config.defaults,config_schema_version:"1.1",output:undefined,initial_soc:.37}})')
        self.assertEqual(self.page.evaluate('readPhysics().output'),
                         self.page.evaluate('physical.config.defaults.output'))
        self.page.locator('#physics-result-settings>summary').click()
        self.page.locator('#physics-initial_ocv_v').fill('3.8')
        expect(self.page.locator('#physics-initial_soc')).to_be_disabled()
        self.page.locator('#physics-reference_electrode_fraction').fill('0.25')
        self.page.locator('#physics-output-frames').fill('5')
        self.page.locator('#physics-output-max_nodes').fill('10')
        before = self.page.evaluate('readPhysics()')
        self.page.evaluate('async input => restorePhysics({input})', before)
        self.assertEqual(self.page.evaluate('readPhysics()'), before)
        response = self.page.request.post(self.url + '/api/physics/preview',
                                          data=json.dumps({'output': {'variables': ['unregistered']}}),
                                          headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)

    def test_legacy_result_and_save_enables_postprocess(self):
        legacy = json.loads(Path('docs/evidence/step03/spme_normal.json').read_text(encoding='utf-8'))
        self.page.evaluate('run=>showResult(run)', legacy)
        self.page.locator('#result-explorer>summary').click()
        self.page.locator('#result-spatial-details>summary').click()
        expect(self.page.locator('#result-spatial-label')).to_contain_text('旧結果')
        expect(self.page.locator('#spatial-csv')).to_be_hidden()
        dataset = copy.deepcopy(self.dataset)
        dataset['id'] = 'unsaved-p2-import'
        self.server.service.recent[dataset['id']] = dataset
        self.server.service.originals[dataset['id']] = self.server.service.original(self.dataset['id'])
        self.page.evaluate('run=>showResult(run)', dataset)
        expect(self.page.locator('#result-postprocess')).to_be_disabled()
        self.page.locator('#save').click()
        expect(self.page.locator('#result-postprocess')).to_be_enabled()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(P2BrowserTests))
    raise SystemExit(not result.wasSuccessful())
