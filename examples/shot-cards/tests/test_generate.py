"""Observable offline CLI behavior; standard library only. SPDX-License-Identifier: MIT"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parent
SPEC = importlib.util.spec_from_file_location('shot_cards_generator', EXAMPLE / 'generate.py')
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


class ShotCardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.shot-cards-test-', dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        assert self.base.is_relative_to(HERE.resolve())
        self.work = self.base / 'work'
        self.work.mkdir()
        shutil.copyfile(EXAMPLE / 'generate.py', self.work / 'generate.py')
        self.data = json.loads((EXAMPLE / 'demo.json').read_text('utf-8'))

    def run_cli(self, data=None, output='cards.html', raw=None):
        source = self.work / 'input.json'
        source.write_text(raw if raw is not None else json.dumps(self.data if data is None else data, ensure_ascii=False), encoding='utf-8')
        return subprocess.run([sys.executable, '-I', '-S', str(self.work / 'generate.py'), '--input', str(source), '--output', output], cwd=self.work, capture_output=True, encoding='utf-8', errors='replace', timeout=15)

    def test_clean_copied_cli_without_site_packages(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.work / 'cards.html').read_bytes()
        self.assertIn('generated=cards.html shots=4', result.stdout)
        self.assertIn('计划 18 秒', output.decode('utf-8'))
        self.assertEqual(output.count(b'<article class="card"'), 4)
        self.assertNotIn(b'\r', output)
        self.assertNotIn(str(self.work).encode(), output)

    def test_changed_product_and_timing(self):
        changed = json.loads(json.dumps(self.data, ensure_ascii=False).replace('贝果', '乡村面包').replace('圆环形', '长条形'))
        changed['shots'][0]['duration_seconds'] = 5.5
        result = self.run_cli(changed)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.work / 'cards.html').read_text('utf-8')
        self.assertIn('乡村面包', output)
        self.assertNotIn('贝果', output)
        self.assertIn('计划 20.5 秒', output)
        self.assertIn('5.5–11.5 秒', output)

    def test_missing_field_does_not_create_output(self):
        del self.data['product']['name']
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('product: missing required field(s): name', result.stderr)
        self.assertFalse((self.work / 'cards.html').exists())

    def test_existing_output_retained_byte_for_byte(self):
        original = b'KEEP THIS PREVIOUS OUTPUT\x00\xff'
        (self.work / 'cards.html').write_bytes(original)
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.work / 'cards.html').read_bytes(), original)

    def test_paths_cannot_escape_working_directory(self):
        outside = self.base / 'escape.html'
        for path in ('../escape.html', str(outside), 'C:/escape.html', 'folder/../../escape.html', 'folder\\escape.html'):
            with self.subTest(path=path):
                result = self.run_cli(output=path)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(outside.exists())

    def test_reserved_or_non_html_names_rejected(self):
        for path in ('CON.html', 'file.html:stream', 'script.py', 'NUL.txt.html'):
            with self.subTest(path=path):
                self.assertEqual(self.run_cli(output=path).returncode, 2)

    def test_missing_output_parent_rejected(self):
        result = self.run_cli(output='missing/cards.html')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.work / 'missing').exists())

    def test_symlink_parent_rejected_when_os_allows_links(self):
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.work / 'link').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'OS cannot create test symlink: {type(exc).__name__}')
        result = self.run_cli(output='link/escape.html')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((outside / 'escape.html').exists())

    def test_text_is_escaped_not_executable_html(self):
        self.data['title'] = '<script>alert("demo")</script>'
        self.data['shots'][0]['action'] = '<img src=x onerror=alert(1)>'
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.work / 'cards.html').read_text('utf-8')
        self.assertIn('&lt;script&gt;', output)
        self.assertNotIn('<script>', output)
        self.assertNotIn('<img src=x', output)

    def test_invalid_fact_reference_rejected(self):
        self.data['shots'][0]['fact_ids'] = ['missing']
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('unknown fact id', result.stderr)

    def test_duplicate_ids_and_nonfinite_duration_rejected(self):
        invalid = []
        one = json.loads(json.dumps(self.data)); one['shots'][1]['id'] = one['shots'][0]['id']; invalid.append(one)
        two = json.loads(json.dumps(self.data)); two['product']['approved_facts'][1]['id'] = 'shape'; invalid.append(two)
        three = json.loads(json.dumps(self.data)); three['shots'][0]['duration_seconds'] = float('nan'); invalid.append(three)
        for data in invalid:
            with self.subTest(data=data):
                self.assertEqual(self.run_cli(data).returncode, 2)
                self.assertFalse((self.work / 'cards.html').exists())

    def test_duplicate_json_keys_rejected(self):
        result = self.run_cli(raw='{"version":1,"version":1}')
        self.assertEqual(result.returncode, 2)
        self.assertIn('duplicate key', result.stderr)

    def test_checked_in_demo_is_actual_deterministic_output(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / 'cards.html').read_bytes(), (EXAMPLE / 'demo.html').read_bytes())

    def test_existing_subdirectory_is_supported(self):
        (self.work / 'exports').mkdir()
        result = self.run_cli(output='exports/cards.html')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.work / 'exports/cards.html').is_file())


if __name__ == '__main__':
    unittest.main()
