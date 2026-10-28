"""Build a labelled local SDK wheel with the patched urllib3 pin; no install side effects."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

OLD = 'isaacsim_kernel-6.2.0.0.dist-info/'
NEW = 'isaacsim_kernel-6.2.0.0+rosy.1.dist-info/'
FILENAME = 'isaacsim_kernel-6.2.0.0-cp312-none-manylinux_2_35_x86_64.whl'


def encoded_hash(data):
    return 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()


def rebuild(source, destination, expected_sha256):
    source, destination = Path(source), Path(destination)
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('source SHA mismatch')
    if source.name != FILENAME:
        raise ValueError('unexpected vendor wheel filename')
    with zipfile.ZipFile(source) as vendor:
        names = vendor.namelist()
        if len(names) != len(set(names)) or any('\\' in n or n.startswith('/') or '..' in PurePosixPath(n).parts for n in names):
            raise ValueError('unsafe wheel paths')
        if any(n.endswith(('RECORD.jws', 'RECORD.p7s')) for n in names):
            raise ValueError('signed wheel needs a separate signing procedure')
        records = list(csv.reader(io.StringIO(vendor.read(OLD + 'RECORD').decode())))
        if len(records) != len({r[0] for r in records}) or {r[0] for r in records} != {n for n in names if not n.endswith('/')}:
            raise ValueError('RECORD file inventory mismatch')
        for name, digest, size in records:
            if name == OLD + 'RECORD':
                if digest or size:
                    raise ValueError('RECORD must not hash itself')
                continue
            data = vendor.read(name)
            if digest != encoded_hash(data) or size != str(len(data)):
                raise ValueError('RECORD integrity mismatch: ' + name)
        metadata = vendor.read(OLD + 'METADATA')
        metadata, count = re.subn(rb'(?m)^Version: 6\.2\.0\.0\r?$', b'Version: 6.2.0.0+rosy.1', metadata)
        if count != 1:
            raise ValueError('unexpected vendor version')
        metadata, count = re.subn(rb'(?m)^Requires-Dist: urllib3==2\.7\.0\r?$', b'Requires-Dist: urllib3==2.8.0', metadata)
        if count != 1:
            raise ValueError('unexpected vendor pin')
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / FILENAME.replace('-6.2.0.0-', '-6.2.0.0+rosy.1-')
        manifest = {'source_filename': source.name, 'source_sha256': expected_sha256,
                    'local_version': '6.2.0.0+rosy.1', 'patch': {'urllib3': ['==2.7.0', '==2.8.0']},
                    'runtime_payload_changed': False}
        rows = []
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as patched:
            for member in vendor.infolist():
                if member.filename == OLD + 'RECORD':
                    continue
                old_name = member.filename
                member.filename = NEW + old_name[len(OLD):] if old_name.startswith(OLD) else old_name
                data = metadata if old_name == OLD + 'METADATA' else vendor.read(old_name)
                patched.writestr(member, data)
                if not member.is_dir():
                    rows.append((member.filename, encoded_hash(data), len(data)))
            data = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
            patched.writestr(NEW + 'ROSY_COMPAT.json', data)
            rows.append((NEW + 'ROSY_COMPAT.json', encoded_hash(data), len(data)))
            rows.append((NEW + 'RECORD', '', ''))
            record = io.StringIO(newline='')
            csv.writer(record, lineterminator='\n').writerows(rows)
            patched.writestr(NEW + 'RECORD', record.getvalue().encode())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    result = rebuild(args.source, args.destination, args.source_sha256)
    print(json.dumps({'wheel': result.name, 'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}))
