"""Private JSON snapshots: Azure Blob when configured, or an explicit persistent data directory."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from contextlib import contextmanager

_LOCKS = [threading.RLock() for _ in range(128)]


class SnapshotStore:
    def __init__(self):
        self.url = os.getenv('REPORT_STORAGE_ACCOUNT_URL', '').strip()
        self.directory = os.getenv('REPORT_STORAGE_DIR', '').strip()
        self.container = os.getenv('REPORT_STORAGE_CONTAINER', 'planning-reports')

    def key(self, kind, scope):
        if kind not in {'deliverables', 'planning', 'planning-settings', 'planning-response', 'planning-proposal', 'analytics'}:
            raise ValueError('Unknown report storage kind.')
        return kind + '/' + hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest() + '.json'

    @contextmanager
    def lock(self, kind, scope):
        # Serialize same-scope generation within this process; fixed stripes avoid unbounded lock growth.
        key = self.key(kind, scope)
        with _LOCKS[int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(_LOCKS)]:
            yield

    def blob(self, key):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        return BlobServiceClient(self.url, credential=DefaultAzureCredential()).get_blob_client(self.container, key)

    def read(self, kind, scope):
        key = self.key(kind, scope)
        if self.url:
            from azure.core.exceptions import ResourceNotFoundError
            try:
                return json.loads(self.blob(key).download_blob().readall())
            except ResourceNotFoundError:
                return None
        if self.directory:
            path = Path(self.directory) / key
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        return None

    def write(self, kind, scope, value):
        key = self.key(kind, scope)
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if self.url:
            from azure.storage.blob import ContentSettings
            self.blob(key).upload_blob(payload, overwrite=True, content_settings=ContentSettings(content_type='application/json'))
        elif self.directory:
            path = Path(self.directory) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
                    temporary = handle.name
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        else:
            raise ValueError('Persistent storage is not configured. Set REPORT_STORAGE_ACCOUNT_URL and provision a private container, or configure REPORT_STORAGE_DIR on persistent storage.')
