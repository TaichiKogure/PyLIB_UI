"""Windows entrypoint regression: identity and repeated double-click reuse."""
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import threading
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

from pylibstudy.server import create_server

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows batch entrypoint')
    def test_cold_start_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            # Isolated data directory: never acquire the user's job/database ownership.
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen(
                    ['cmd.exe', '/d', '/c', str(ROOT / 'start.cmd'), '-NoBrowser',
                     '-Port', str(port), '-DataDir', directory], cwd=directory,
                    stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/api/identity', timeout=1) as response:
                                self.assertEqual(json.load(response)['root'], str(ROOT))
                            break
                        except URLError:
                            if time.monotonic() >= deadline or process.poll() is not None:
                                output.seek(0)
                                self.fail(f'Batch startup failed: {output.read()!r}')
                            time.sleep(.1)
                    with urlopen(f'http://127.0.0.1:{port}/api/config', timeout=5) as response:
                        self.assertIn('models', json.load(response))
                    self.assertTrue((Path(directory) / 'runs.sqlite3').exists())
                finally:
                    # Kill only the exact process tree created by this test.
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=10)
                    process.wait(timeout=10)

    def test_identity_and_existing_server_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(0, Path(directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                with urlopen(url + '/api/identity', timeout=5) as response:
                    self.assertEqual(json.load(response), {'app': 'PyLiBStudy', 'root': str(ROOT)})
                if os.name == 'nt':
                    # Exercise the same .cmd chain used by the generated shortcut.
                    for _ in range(2):
                        result = subprocess.run(
                            ['cmd.exe', '/d', '/c', str(ROOT / 'start.cmd'),
                             '-NoBrowser', '-Port', str(server.server_port)],
                            cwd=directory, capture_output=True, timeout=20)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn(b'already running', result.stdout)
                    with urlopen(url + '/api/identity', timeout=5) as response:
                        self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
