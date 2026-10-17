"""P1 browser tests against an isolated server with real preview/validation APIs."""
import unittest
from pathlib import Path

from playwright.sync_api import expect
from verify_model_tabs import ModelTabTests


class P1BrowserTests(unittest.TestCase):
    setUpClass = classmethod(ModelTabTests.setUpClass.__func__)
    tearDownClass = classmethod(ModelTabTests.tearDownClass.__func__)
    setUp = ModelTabTests.setUp
    tearDown = ModelTabTests.tearDown

    def test_spm_templates_preview_and_preserved_input(self):
        self.page.locator('#tab-SPM').click()
        expect(self.page.locator('#physics-model')).to_have_value('SPM')
        self.page.locator('#physics-template').select_option('hppc')
        self.page.locator('#physics-template-apply').click()
        expect(self.page.locator('#physics-steps>.physics-step-card')).to_have_count(1)
        self.page.locator('#physics-cycles').fill('2')
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(16)
        expect(self.page.locator('#physics-preview-status')).to_contain_text('5.0000 Ah')
        self.page.locator('#physics-panel').screenshot(path='docs/evidence/p1/protocol-desktop.png')
        expect(self.page.locator('#physics-preview')).to_contain_text('-1.0000 / -0.2000')
        before = self.page.evaluate('readPhysics()')
        self.page.locator('#tab-design').click()
        self.page.locator('#tab-SPM').click()
        self.assertEqual(self.page.evaluate('readPhysics()'), before)
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(16)
        self.page.locator('#physics-cycles').fill('3')
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(0)
        expect(self.page.locator('#physics-preview-status')).to_contain_text('条件が変わりました')

    def test_nested_controls_metadata_restore_without_loss(self):
        self.page.evaluate('''async () => restorePhysics({input: {...physical.config.defaults,
            model: 'SPM', cycles: 2, start_time: '2026-10-17T09:00:00+09:00', protocol: [
                {kind: 'repeat', count: 2, steps: [{kind: 'cp', power_w: 3.7, control: 'differential',
                    control_tau_s: 2, duration_s: 20, period_s: 1, temperature_c: 30, tags: ['pulse'], skip_ok: true},
                    {kind: 'profile', points: [[0,1],[10,0]], temperature_c: 30, tags: ['wave']}]}]}})''')
        before = self.page.evaluate('readPhysics()')
        self.assertEqual(before['protocol'][0]['steps'][0]['control_tau_s'], 2)
        self.assertEqual(before['protocol'][0]['steps'][1]['tags'], ['wave'])
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(8)
        expect(self.page.locator('#physics-preview')).to_contain_text('differential')
        self.page.locator('#tab-DFN').click()
        self.page.locator('#tab-SPM').click()
        self.assertEqual(self.page.evaluate('readPhysics()'), before)
        self.page.locator('#physics-parameter_set').select_option('Chen2020_composite')
        expect(self.page.locator('#tab-SPM')).to_be_disabled()
        expect(self.page.locator('#physics-model')).to_have_value('DFN')

    def test_profile_mode_does_not_erase_step_editor_and_limits_rejected(self):
        before = self.page.evaluate('readPhysics().protocol')
        self.page.locator('#physics-protocol-mode').select_option('profile')
        self.page.locator('#physics-profile').fill('0,1\n10,-1')
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(1)
        self.page.locator('#physics-protocol-mode').select_option('steps')
        self.assertEqual(self.page.evaluate('readPhysics().protocol'), before)
        self.page.evaluate(
            '''() => { $('physics-steps').replaceChildren(); physicsStep({kind:'c_rate', c_rate:100, duration_s:10}); }''')
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview-status')).to_contain_text('25 A')

    def test_real_job_progress_result_and_restore(self):
        self.page.evaluate('''async () => restorePhysics({input:{...physical.config.defaults, model:'SPM',
            name:'P1 browser live', cycles:2, protocol:[{kind:'c_rate',c_rate:0.2,duration_s:10}, {kind:'rest',duration_s:5}]}})''')
        self.page.locator('#physics-run').click()
        expect(self.page.locator('#physics-jobs')).to_contain_text('P1 browser live', timeout=30000)
        expect(self.page.locator('#result-title')).to_have_text('P1 browser live', timeout=60000)
        expect(self.page.locator('#physics-jobs')).to_contain_text('到達 4/4')
        self.assertEqual(self.page.evaluate('state.current.step_results.length'), 4)
        expect(self.page.locator('#chart svg')).to_have_count(1)
        self.page.locator('#restore').click()
        expect(self.page.locator('#physics-cycles')).to_have_value('2')
        expect(self.page.locator('#physics-model')).to_have_value('SPM')

    def test_mobile_repeat_controls_and_preview(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('#tab-SPM').click()
        self.page.locator('#physics-template').select_option('gitt')
        self.page.locator('#physics-template-apply').click()
        self.page.locator('#physics-add-repeat').click()
        self.page.locator('#physics-preview-button').click()
        expect(self.page.locator('#physics-preview tbody tr')).to_have_count(8)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#physics-panel').screenshot(path='docs/evidence/p1/protocol-mobile.png')


if __name__ == '__main__':
    Path('docs/evidence/p1').mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(P1BrowserTests))
    raise SystemExit(not result.wasSuccessful())
