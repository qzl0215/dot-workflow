"""Exercise release boundaries; behavior review is documented separately."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check', ROOT/'scripts/check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in check.SOURCE:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)

    def test_public_candidate_validates(self):
        self.assertRegex(check.validate(self.root), r'^\d+\.\d+\.\d+$')

    def test_unlisted_file_blocks_release(self):
        (self.root/'notes.txt').write_text('not part of the release')
        with self.assertRaisesRegex(ValueError, 'extra='):
            check.validate(self.root)

    def test_missing_reference_blocks_release(self):
        (self.root/'SKILL.md').write_text((self.root/'SKILL.md').read_text()+'\n[missing](references/missing.md)\n')
        with self.assertRaisesRegex(ValueError, 'broken local link'):
            check.validate(self.root)

    def test_symlink_blocks_release(self):
        icon = self.root/'assets/icon.svg'
        icon.unlink()
        icon.symlink_to(ROOT/'assets/icon.svg')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            check.validate(self.root)

    def test_missing_attribution_blocks_release(self):
        reference = self.root/'references/grill-me-zh.md'
        reference.write_text(reference.read_text().replace('Copyright (c) 2026 Matt Pocock', ''))
        with self.assertRaisesRegex(ValueError, 'upstream MIT'):
            check.validate(self.root)


if __name__ == '__main__':
    unittest.main()
