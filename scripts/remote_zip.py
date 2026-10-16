"""Read selected public ZIP members with bounded HTTP Range requests.

No archive extraction to arbitrary paths and no pickle/code execution.
ZIP member CRC is checked by zipfile; a member hash does not verify the
upstream whole-archive hash when only selected ranges are downloaded.
"""
import io
from urllib.request import Request, urlopen


class RemoteZipFile(io.RawIOBase):
    def __init__(self, url, size, max_read=64 * 1024 * 1024):
        self.url = url
        self.size = size
        self.max_read = max_read
        self.position = 0
        self.cache = []
        self.requests = []

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if not 0 <= self.position <= self.size:
            raise ValueError('Archive seek outside range')
        return self.position

    def read(self, count=-1):
        start = self.position
        end = min(self.size, start + count) if count >= 0 else self.size
        if end <= start:
            return b''
        if end - start > self.max_read:
            raise ValueError('Archive range read limit exceeded')
        for cached_start, raw in self.cache:
            if cached_start <= start and end <= cached_start + len(raw):
                self.position = end
                return raw[start - cached_start:end - cached_start]
        headers = {'User-Agent': 'PyLiBStudy-Research/0.6', 'Range': f'bytes={start}-{end - 1}',
                   'Accept-Encoding': 'identity'}
        with urlopen(Request(self.url, headers=headers), timeout=60) as response:
            content_range = response.headers.get('Content-Range', '')
            expected = f'bytes {start}-{end - 1}/{self.size}'
            if response.status != 206 or content_range != expected:
                raise ValueError('Server did not return the requested byte range')
            raw = response.read(end - start + 1)
        if len(raw) != end - start:
            raise ValueError('Archive range length mismatch')
        self.position = end
        self.requests.append({'start': start, 'end': end - 1, 'bytes': len(raw)})
        self.cache.append((start, raw))
        return raw
