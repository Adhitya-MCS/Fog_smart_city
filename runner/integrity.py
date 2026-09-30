"""Verify that the vendored YAFS source is byte-identical to the original copy."""
import hashlib
import json
from pathlib import Path


def verify_yafs(root=None):
    root=Path(root) if root else Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'SOURCE_MANIFEST.json').read_text())
    expected=manifest['yafs_sha256']
    files={str(p.relative_to(root)) for p in (root/'yafs').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store'}
    if files!=set(expected):raise RuntimeError('YAFS source file list differs from source manifest')
    for filename,digest in expected.items():
        if hashlib.sha256((root/filename).read_bytes()).hexdigest()!=digest:
            raise RuntimeError(f'YAFS source changed: {filename}')
    return expected


if __name__=='__main__':print(f'YAFS verified: {len(verify_yafs())} files unchanged')
