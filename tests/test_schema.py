"""Synthetic-only independent schema and actual workflow staging regressions."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validate_public import NOTES, loads_public, validate_public


def fixture():
    return {
        'version': 1, 'checkedAt': '2026-01-02T12:00:00Z',
        'dataAsOf': '2026-01-02T10:00:00Z', 'timezone': 'Europe/Zurich',
        'recent': [{'startedAt': '2026-01-02T10:00:00Z', 'endedAt': None,
                    'leftMinutes': None, 'rightMinutes': 0, 'knownMinutes': 10,
                    'order': ['left', 'left'],
                    'segments': [{'side': 'left', 'at': '2026-01-02T10:00:00Z', 'minutes': 10},
                                 {'side': 'left', 'at': '2026-01-02T10:15:00Z', 'minutes': None}],
                    'grouped': False, 'uncertain': True}],
        'days': [{'date': '2026-01-02', 'sessions': 1, 'knownDurationSessions': 0,
                  'totalMinutes': 10, 'meanMinutes': None, 'meanIntervalHours': None}],
        'coverage': {'start': '2026-01-02', 'end': '2026-01-02', 'notes': sorted(NOTES)},
    }


def invalid_payloads():
    cases = []
    for path in ((), ('coverage',), ('recent', 0), ('recent', 0, 'segments', 0), ('days', 0)):
        for key in ('name', 'sources', 'extra', 'at'):
            value = fixture()
            target = value
            for component in path:
                target = target[component]
            # Existing segment at is tested separately, not overwritten here.
            if key in target:
                continue
            target[key] = 'PRIVATE_SENTINEL'
            cases.append(value)
    value = fixture()
    value['recent'] *= 6
    cases.append(value)
    for key, bad in (('totalMinutes', 11), ('meanMinutes', 12), ('meanIntervalHours', 1.25),
                     ('sessions', True), ('sessions', -1), ('knownDurationSessions', 2)):
        value = fixture()
        value['days'][0][key] = bad
        cases.append(value)
    for bad in (['PRIVATE_SENTINEL'], [{'name': 'PRIVATE_SENTINEL'}]):
        value = fixture()
        value['coverage']['notes'] = bad
        cases.append(value)
    for key, bad in (('checkedAt', '2026-01-02T10:00:00'), ('checkedAt', '2026-01-02'),
                     ('dataAsOf', '2025-12-01T10:00:00Z'), ('timezone', 'PRIVATE_SENTINEL'),
                     ('version', True)):
        value = fixture()
        value[key] = bad
        cases.append(value)
    for key, bad in (('knownMinutes', -1), ('knownMinutes', True), ('knownMinutes', float('nan')),
                     ('knownMinutes', float('inf')), ('grouped', 1), ('order', ['PRIVATE_SENTINEL']),
                     ('endedAt', '2026-01-01T00:00:00Z')):
        value = fixture()
        value['recent'][0][key] = bad
        cases.append(value)
    value = fixture()
    del value['recent'][0]['knownMinutes']
    cases.append(value)
    value = fixture()
    value['recent'][0]['segments'][0]['side'] = 'PRIVATE_SENTINEL'
    cases.append(value)
    return cases


class SchemaTests(unittest.TestCase):
    def test_valid_partial_and_empty(self):
        self.assertEqual(loads_public(json.dumps(fixture())), fixture())
        empty = fixture()
        empty.update(recent=[], days=[], dataAsOf=None)
        empty['coverage'].update(start=None, end=None)
        self.assertIs(validate_public(empty), empty)
        partial = fixture()
        partial['recent'][0]['knownMinutes'] = None
        validate_public(partial)

    def test_five_accepted_six_rejected(self):
        value = fixture()
        value['recent'] = []
        for hour in range(10, 4, -1):
            session = copy.deepcopy(fixture()['recent'][0])
            for key in ('startedAt',):
                session[key] = f'2026-01-02T{hour:02d}:00:00Z'
            for part, minute in zip(session['segments'], (0, 15)):
                part['at'] = f'2026-01-02T{hour:02d}:{minute:02d}:00Z'
            value['recent'].append(session)
        value['days'][0]['sessions'] = 6
        with self.assertRaises(ValueError):
            validate_public(value)
        value['recent'].pop()
        self.assertIs(validate_public(value), value)
        value['dataAsOf'] = '2026-01-02T05:15:00Z'
        with self.assertRaises(ValueError):
            validate_public(value)

    def test_invalid_payloads(self):
        for index, payload in enumerate(invalid_payloads()):
            with self.subTest(case=index), self.assertRaisesRegex(ValueError, '^Invalid public export$'):
                validate_public(payload)

    def test_duplicate_keys_and_invalid_json(self):
        for raw in ('{"version":1,"version":1}', '{', b'\xff', ' ' * (1024 * 1024 + 1)):
            with self.assertRaisesRegex(ValueError, '^Invalid public export$'):
                loads_public(raw)

    def test_workflow_gate_and_artifact_allowlist(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        workflow = (ROOT / '.github/workflows/deploy.yml').read_text()
        script = textwrap.dedent(workflow.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / 'checkout'
            checkout.mkdir()
            subprocess.run(['git', 'init', '-q', str(checkout)], check=True, capture_output=True)
            for name in ('index.html', 'styles.css', 'app.js', 'validate_public.py'):
                shutil.copyfile(ROOT / name, checkout / name)
            key, publish_id = os.urandom(32), 'a' * 32
            # All malformed cases traverse real AES-GCM decryption and runner code.
            for index, payload in enumerate([fixture()] + invalid_payloads()):
                runner = Path(temp) / str(index)
                runner.mkdir()
                plain = json.dumps(payload).encode()
                nonce = os.urandom(12)
                encrypted = nonce + AESGCM(key).encrypt(nonce, plain, publish_id.encode())
                env = dict(os.environ, EXPORT_KEY=base64.b64encode(key).decode(),
                           EXPORT_CIPHERTEXT=base64.b64encode(encrypted).decode(),
                           EXPORT_PUBLISH_ID=publish_id, RUNNER_TEMP=str(runner),
                           PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, '-c', script], cwd=checkout, env=env,
                                        capture_output=True, text=True, timeout=20)
                with self.subTest(case=index):
                    self.assertEqual(result.stdout, '')
                    if index == 0:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, '')
                        site = runner / 'public-site'
                        self.assertEqual({p.name for p in site.iterdir()},
                                         {'index.html', 'styles.css', 'app.js', 'data.json', '.nojekyll'})
                        self.assertEqual((site / 'data.json').read_bytes(), plain)
                    else:
                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(result.stderr, 'Public artifact preparation failed; no payload logged.\n')
                        self.assertFalse((runner / 'public-site').exists())


if __name__ == '__main__':
    unittest.main()
