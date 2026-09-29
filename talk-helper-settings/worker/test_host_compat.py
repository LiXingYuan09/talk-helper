import hashlib
import tempfile
import unittest
from pathlib import Path

from host_compat import known_binary


class PortableHostTests(unittest.TestCase):
    def test_identical_binary_matches_outside_default_install_path(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'custom-folder' / 'Weixin.dll'
            path.parent.mkdir()
            content = b'verified-build-fixture'
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            self.assertTrue(known_binary(path, 'Weixin.dll', len(content), digest))
            self.assertFalse(known_binary(path, 'Weixin.dll', len(content) + 1, digest))
            path.write_bytes(b'changed-build-fixture!')
            self.assertFalse(known_binary(path, 'Weixin.dll', len(content), digest))

    def test_wrong_module_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'other.dll'
            path.write_bytes(b'x')
            self.assertFalse(known_binary(path, 'Weixin.dll', 1, hashlib.sha256(b'x').hexdigest()))


if __name__ == '__main__':
    unittest.main()
