import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sbepv.api import config, technoeconomic


class AnnualSourcePathTests(unittest.TestCase):
    def test_atomic_hardening_works_with_a_long_output_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ('x' * max(1, 144 - len(temporary)))
            root.mkdir()
            source = root / 'source.csv'
            source.write_bytes(b'timestamp,value\n2024-01-01,1\n')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(config, 'OUTPUT_DIR', root), patch.object(config, 'ANNUAL_SOURCE_ARTIFACT_DIR', root / '.annual_sources'):
                result = technoeconomic.harden_annual_source_artifact(source, digest, annual_job_id='path-fixture')
            self.assertEqual(digest, result['sha256'])
            hardened = list((root / '.annual_sources').rglob('*.csv'))
            self.assertEqual(1, len(hardened))
            self.assertEqual(source.read_bytes(), hardened[0].read_bytes())
            self.assertEqual([], list((root / '.annual_sources').rglob('*.tmp')))
