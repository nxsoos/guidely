"""Private Supabase Storage. Only signed object capabilities reach the browser."""
from pathlib import Path
from urllib.parse import quote
import httpx
from .documents import MAX_UPLOAD
from .errors import AppError


class Storage:
    def __init__(self, settings):
        self.settings = settings
        if settings.test_mode:
            self.directory = settings.data_dir / 'test-uploads'
            self.directory.mkdir(parents=True, exist_ok=True)
        elif not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.')

    def request(self, method, path, **kwargs):
        try:
            with httpx.Client(timeout=20) as client:
                response = client.request(method, self.settings.supabase_url + '/storage/v1/' + path,
                    headers={'apikey': self.settings.supabase_key, 'Authorization': 'Bearer ' + self.settings.supabase_key}, **kwargs)
            if not response.is_success:
                raise AppError(502, 'storage_failure', 'Storage request failed. Retry or check bucket configuration.')
            return response
        except httpx.RequestError:
            raise AppError(503, 'storage_unavailable', 'Document storage is unavailable. Please retry.') from None

    def path(self, key):
        return quote(self.settings.storage_bucket, safe='') + '/' + quote(key, safe='/')

    def signed_upload(self, key):
        if self.settings.test_mode:
            return '/api/test-uploads/' + key.split('/')[-1]
        data = self.request('POST', 'object/upload/sign/' + self.path(key), json={}).json()
        url = data.get('url') or data.get('signedURL')
        if not url:
            raise AppError(502, 'storage_failure', 'Storage did not return an upload URL.')
        return self.settings.supabase_url + '/storage/v1' + url if url.startswith('/') else url

    def read(self, key):
        if self.settings.test_mode:
            return (self.directory / key).read_bytes()
        # Stream and cap actual bytes: do not trust browser size or Content-Length.
        try:
            with httpx.Client(timeout=20) as client:
                with client.stream('GET', self.settings.supabase_url + '/storage/v1/object/' + self.path(key),
                    headers={'apikey':self.settings.supabase_key,'Authorization':'Bearer '+self.settings.supabase_key}) as response:
                    if not response.is_success:
                        raise AppError(409, 'upload_missing', 'Upload the file before completing it.')
                    content = bytearray()
                    for part in response.iter_bytes():
                        content.extend(part)
                        if len(content) > MAX_UPLOAD:
                            raise AppError(413, 'file_too_large', 'Files must be 1 MB or smaller.')
                    return bytes(content)
        except httpx.RequestError:
            raise AppError(503, 'storage_unavailable', 'Cannot read uploaded file. Please retry.') from None

    def write_test(self, key, content):
        if not self.settings.test_mode:
            raise RuntimeError('Use authenticated direct uploads.')
        target = self.directory / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def delete(self, key):
        if self.settings.test_mode:
            (self.directory / key).unlink(missing_ok=True)
            return
        self.request('DELETE', 'object/' + quote(self.settings.storage_bucket, safe=''), json={'prefixes':[key]})

    def download(self, key):
        data = self.request('POST', 'object/sign/' + self.path(key), json={'expiresIn':60}).json()
        return self.settings.supabase_url + '/storage/v1' + data['signedURL']
