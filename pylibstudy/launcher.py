"""Visible local launcher without PowerShell execution-policy changes."""
import argparse
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start PyLiBStudy locally')
    parser.add_argument('--port', '-Port', type=int, default=8765)
    parser.add_argument('--no-browser', '-NoBrowser', action='store_true')
    parser.add_argument('--data-dir', '-DataDir', type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    root = Path(__file__).resolve().parents[1]
    url = f'http://127.0.0.1:{args.port}'
    if args.data_dir is None:
        # Fixed loopback URL, no inherited proxy, bounded identity response.
        try:
            with build_opener(ProxyHandler({})).open(url + '/api/identity', timeout=1.5) as response:
                identity = json.loads(response.read(4096))
            if (isinstance(identity, dict) and identity.get('app') == 'PyLiBStudy'
                    and isinstance(identity.get('root'), str)
                    and Path(identity['root']) == root):
                print(f'PyLiBStudy is already running: {url}', flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                return
        except (URLError, OSError, ValueError):
            pass
    # Foreign/occupied ports produce the normal bind error; never stop their process.
    from .server import main as serve
    server_args = ['--port', str(args.port)]
    if args.no_browser:
        server_args.append('--no-browser')
    if args.data_dir is not None:
        server_args.extend(['--data-dir', str(args.data_dir)])
    serve(server_args)


if __name__ == '__main__':
    main()
