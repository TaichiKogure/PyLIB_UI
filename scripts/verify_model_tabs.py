r"""Browser regression checks for model navigation, using an isolated database.

Run with a Python environment containing Playwright and an installed Edge browser:
    .\.venv\Scripts\python.exe scripts\verify_model_tabs.py
"""
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.server import create_server


class ModelTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='model-tabs-',
                                                    dir=Path(__file__).resolve().parents[1] / 'data')
        cls.server = create_server(0, cls.directory.name)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1440, 'height': 1000})
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        expect(self.page.locator('#run')).to_be_enabled(timeout=30000)

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def assert_tab(self, model):
        tab = self.page.locator('#tab-' + model)
        expect(tab).to_have_attribute('aria-selected', 'true')
        expect(tab).to_have_attribute('tabindex', '0')
        expect(self.page.locator('[data-model-tab][aria-selected="true"]')).to_have_count(1)
        panel = 'physics' if model in ('SPMe', 'DFN') else model
        for name in ('physics', 'synthetic', 'design', 'cathodes'):
            if name == panel:
                expect(self.page.locator('#' + name + '-panel')).to_be_visible()
            else:
                expect(self.page.locator('#' + name + '-panel')).to_be_hidden()
        if panel == 'physics':
            expect(self.page.locator('#physics-model')).to_have_value(model)
            expect(self.page.locator('#physics-panel')).to_have_attribute('aria-labelledby', 'tab-' + model)
            expect(self.page.locator('#physics-title')).to_contain_text(model)

    def test_clicks_preserve_independent_settings_without_calculation(self):
        posts = []
        self.page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        self.assert_tab('SPMe')
        self.page.locator('#physics-initial_soc').fill('0.61')
        expect(self.page.locator('#active-configuration')).to_contain_text('61%')
        physics_input = self.page.evaluate('readPhysics()')
        self.page.locator('#tab-synthetic').click()
        self.assert_tab('synthetic')
        self.page.locator('[name="capacity_ah"]').fill('6.2')
        self.page.locator('#simulation-form [name="initial_soc"]').fill('0.42')
        expect(self.page.locator('#active-configuration')).to_contain_text('6.2 Ah')
        expect(self.page.locator('#active-configuration')).to_contain_text('42%')
        self.page.locator('#tab-design').click()
        self.assert_tab('design')
        self.page.locator('#design-form [name="name"]').fill('Navigation test design')
        self.page.locator('#tab-DFN').click()
        self.assert_tab('DFN')
        self.assertEqual(self.page.evaluate('readPhysics()'), {**physics_input, 'model': 'DFN'})
        expect(self.page.locator('#physics-initial_soc')).to_have_value('0.61')
        self.page.locator('#tab-synthetic').click()
        expect(self.page.locator('[name="capacity_ah"]')).to_have_value('6.2')
        expect(self.page.locator('#simulation-form [name="initial_soc"]')).to_have_value('0.42')
        self.page.locator('#tab-design').click()
        expect(self.page.locator('#design-form [name="name"]')).to_have_value('Navigation test design')
        self.page.locator('#tab-SPMe').click()
        self.assert_tab('SPMe')
        self.assertFalse(
            any(url.endswith(('/api/jobs', '/api/simulate', '/api/save', '/api/designs')) for url in posts), posts)

    def test_keyboard_navigation(self):
        tab = self.page.locator('#tab-SPMe')
        tab.focus()
        for key, model in [('ArrowRight', 'DFN'), ('ArrowRight', 'synthetic'), ('End', 'cathodes'),
                           ('Home', 'SPMe'), ('ArrowLeft', 'cathodes')]:
            self.page.keyboard.press(key)
            self.assert_tab(model)
            expect(self.page.locator('#tab-' + model)).to_be_focused()

    def test_model_selector_and_composite_compatibility(self):
        self.page.locator('#physics-model').select_option('DFN')
        self.assert_tab('DFN')
        self.page.locator('#physics-model').select_option('SPMe')
        self.assert_tab('SPMe')
        self.page.locator('#physics-parameter_set').select_option('Chen2020_composite')
        self.assert_tab('DFN')
        expect(self.page.locator('#tab-SPMe')).to_be_disabled()
        self.page.locator('#tab-DFN').focus()
        self.page.keyboard.press('Home')
        self.assert_tab('DFN')
        self.page.keyboard.press('ArrowRight')
        self.assert_tab('synthetic')
        self.page.keyboard.press('ArrowLeft')
        self.assert_tab('DFN')
        self.page.locator('#physics-parameter_set').select_option('Chen2020')
        expect(self.page.locator('#tab-SPMe')).to_be_enabled()
        self.page.locator('#tab-SPMe').click()
        self.assert_tab('SPMe')

    def test_physics_restore_opens_matching_model(self):
        for model, parameter_set in [('DFN', 'Chen2020_composite'), ('SPMe', 'Chen2020')]:
            self.page.locator('#tab-design').click()
            self.page.evaluate('''([model, parameter_set]) => restorePhysics({
                input: {
                    ...physical.config.defaults, model, parameter_set, initial_soc: 0.37,
                    protocol: [{kind: "profile", points: [[0, 1], [10, 0]]}]
                }
            })''', [model, parameter_set])
            self.assert_tab(model)
            expect(self.page.locator('#physics-initial_soc')).to_have_value('0.37')
            expect(self.page.locator('#physics-profile')).to_have_value('0,1\n10,0')

    def test_thermal_controls_and_summary_follow_configuration(self):
        for thermal in ('lumped', 'isothermal'):
            self.page.locator('#physics-thermal').select_option(thermal)
            if thermal == 'lumped':
                expect(self.page.locator('#physics-initial_temp_c')).to_be_enabled()
                expect(self.page.locator('#physics-heat_transfer_w_m2_k')).to_be_enabled()
                label = '\u96c6\u4e2d\u71b1'
            else:
                expect(self.page.locator('#physics-initial_temp_c')).to_be_disabled()
                expect(self.page.locator('#physics-heat_transfer_w_m2_k')).to_be_disabled()
                label = '\u7b49\u6e29'
            expect(self.page.locator('#physics-thermal-note')).to_contain_text(label)
            expect(self.page.locator('#active-configuration')).to_contain_text(label)

    def test_synthetic_restore_and_curve_survive_switching(self):
        self.page.locator('#tab-synthetic').click()
        expect(self.page.locator('#synthetic-panel')).to_be_visible()
        self.page.locator('#simulation-form [name="duration_min"]').fill('1')
        self.page.locator('#run').click()
        expect(self.page.locator('#chart svg')).to_have_count(1)
        run_id = self.page.evaluate('state.current.id')
        self.page.locator('[name="capacity_ah"]').fill('7')
        self.page.locator('#tab-DFN').click()
        self.assert_tab('DFN')
        self.assertEqual(self.page.evaluate('state.current.id'), run_id)
        expect(self.page.locator('#chart svg')).to_have_count(1)
        expect(self.page.locator('#curve-workspace')).to_have_class('workspace results-only')
        self.assertTrue(
            self.page.evaluate('$("chart").querySelector("svg").viewBox.baseVal.width === $("chart").clientWidth'))
        self.page.locator('#restore').click()
        self.assert_tab('synthetic')
        expect(self.page.locator('[name="capacity_ah"]')).to_have_value('5')
        expect(self.page.locator('#curve-workspace')).to_have_class('workspace')
        self.assertTrue(
            self.page.evaluate('$("chart").querySelector("svg").viewBox.baseVal.width === $("chart").clientWidth'))

    def test_apply_saved_design_opens_synthetic_settings(self):
        self.page.locator('#tab-design').click()
        expect(self.page.locator('#design-panel')).to_be_visible()
        expect(self.page.locator('#design-save')).to_be_enabled()
        self.page.locator('#design-save').click()
        expect(self.page.locator('#design-apply')).to_be_enabled()
        self.page.locator('#design-apply').click()
        self.assert_tab('synthetic')
        self.assertIsNotNone(self.page.evaluate('designing.binding'))

    def test_panel_links_reveal_target(self):
        self.page.locator('.steps a[href="#design-panel"]').click()
        self.assert_tab('design')
        self.page.locator('.steps a[href="#physics-panel"]').click()
        self.assert_tab('SPMe')
        self.page.goto(self.url + '/#design-panel')
        expect(self.page.locator('#run')).to_be_enabled()
        self.assert_tab('design')
        self.page.evaluate('location.hash = "#synthetic-panel"')
        self.assert_tab('synthetic')

    def test_selected_tab_is_visible_on_mobile(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        for model in ('synthetic', 'DFN', 'design', 'SPMe'):
            self.page.locator('#tab-' + model).click()
            self.assert_tab(model)
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)


if __name__ == '__main__':
    unittest.main(verbosity=2)
