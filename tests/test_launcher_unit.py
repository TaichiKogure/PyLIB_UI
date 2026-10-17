"""Launcher argument and identity checks; no network, browser or server execution."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from pylibstudy.launcher import main

ROOT = Path(__file__).resolve().parents[1]


class LauncherUnitTests(unittest.TestCase):
    def identity_response(self, identity):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(identity).encode()
        return opener

    def test_existing_server_reused_without_browser(self):
        opener = self.identity_response({'app': 'PyLiBStudy', 'root': str(ROOT)})
        with patch('pylibstudy.launcher.build_opener', return_value=opener), \
                patch('pylibstudy.server.main') as serve, \
                patch('pylibstudy.launcher.webbrowser.open') as browser:
            main(['-Port', '8765', '-NoBrowser'])
            serve.assert_not_called()
            browser.assert_not_called()

    def test_foreign_identity_not_reused(self):
        opener = self.identity_response({'app': 'OtherApp', 'root': str(ROOT)})
        with patch('pylibstudy.launcher.build_opener', return_value=opener), \
                patch('pylibstudy.server.main') as serve:
            main(['--no-browser'])
            serve.assert_called_once_with(['--port', '8765', '--no-browser'])

    def test_isolated_data_skips_reuse(self):
        with patch('pylibstudy.launcher.build_opener') as opener, \
                patch('pylibstudy.server.main') as serve:
            main(['--data-dir', str(ROOT / '.test_tmp'), '--no-browser'])
            opener.assert_not_called()
            serve.assert_called_once_with(['--port', '8765', '--no-browser',
                                           '--data-dir', str(ROOT / '.test_tmp')])
