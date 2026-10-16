"""Verify source cache; optionally fetch missing pinned public files.

Default is offline verification. --download-missing downloads the seven selected
files, checking size and SHA-256 before adoption. The 14.4 GB Wan archive is read
only by HTTP Range, for its directory and the two specified small CSV members.
"""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylibstudy.cathodes import catalog
from remote_zip import RemoteZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-missing', action='store_true')
    args = parser.parse_args()
    cache = ROOT / 'data/reference/cathodes/sources'
    cache.mkdir(parents=True, exist_ok=True)
    data = catalog()
    manifest = json.loads((ROOT / 'pylibstudy/reference/acquisition.json').read_text(encoding='utf-8'))[
        'wan2026_remote_zip']
    files = {s['file']: s for c in data['curves'] for s in c['sources']}
    negative = data['negative_reference']['source']
    files[negative['file']] = negative
    zip_members = {v['file']: v for v in manifest['members']}
    remote = archive = None
    verified = []
    try:
        for filename, source in files.items():
            path = cache / filename
            if Path(filename).name != filename or not path.resolve().is_relative_to(cache.resolve()):
                raise ValueError('Invalid cache filename')
            if path.exists():
                raw = path.read_bytes()
            elif not args.download_missing:
                raise ValueError(f'Missing cached file: {filename}; use --download-missing for retrieval')
            elif filename in zip_members:
                if archive is None:
                    metadata = manifest['archive']
                    remote = RemoteZipFile(metadata['links']['self'], metadata['size'])
                    archive = zipfile.ZipFile(remote)
                member = zip_members[filename]
                info = archive.getinfo(member['member'])
                if info.file_size != member['bytes'] or info.CRC != member['crc32']:
                    raise ValueError('ZIP member metadata changed; do not adopt automatically')
                raw = archive.read(info)
            else:
                url = source['url']
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or parsed.hostname not in {'raw.githubusercontent.com',
                                                                       'media.springernature.com'}:
                    raise ValueError('Unexpected pinned source URL')
                if source['bytes'] > 64 * 1024 * 1024:
                    raise ValueError('Source exceeds bounded download size')
                with urlopen(Request(url, headers={'User-Agent': 'PyLiBStudy-Research/0.6'}), timeout=60) as response:
                    raw = response.read(source['bytes'] + 1)
            if len(raw) != source['bytes'] or hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise ValueError(f'Source changed or incomplete: {filename}; original cache preserved')
            if not path.exists():
                # Only verified complete bytes become the source cache.
                with path.open('xb') as target:
                    target.write(raw)
            verified.append(filename)
    finally:
        if archive is not None:
            archive.close()
        if remote is not None:
            remote.close()
    print(json.dumps({'verified_files': verified, 'catalog_sha256': data['sha256'],
                      'whole_wan_archive_checksum_verified': False}, indent=2))


if __name__ == '__main__':
    main()
