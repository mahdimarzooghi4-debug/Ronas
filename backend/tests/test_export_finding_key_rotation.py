"""Operator control and bounded batch tests for Export note-key rotation."""
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest

from ronas_api.export_finding_key_rotation import (
    RotationConfigurationError, RotationSettings, load_keyring, main,
    rotate_bounded,
)


class FakeStore:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.calls = []

    def rotate_batch(self, *, limit):
        self.calls.append(limit)
        return next(self.batches)


class ExportFindingKeyRotationTests(unittest.TestCase):
    def settings(self, directory):
        return RotationSettings("postgresql://local/test", "new-key", directory)

    def test_rotation_requires_explicit_local_test_opt_in(self):
        with self.assertRaises(RotationConfigurationError):
            RotationSettings.from_environment({})

    def test_keyring_loads_only_private_exact_32_byte_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "keys"
            directory.mkdir(mode=0o700)
            os.chmod(directory, 0o700)
            for key_id in ("old-key", "new-key"):
                path = directory / (key_id + ".key")
                path.write_bytes(key_id.encode().ljust(32, b"x"))
                os.chmod(path, 0o600)
            self.assertEqual(set(load_keyring(self.settings(directory))),
                             {"old-key", "new-key"})
            os.chmod(directory / "old-key.key", 0o644)
            with self.assertRaises(RotationConfigurationError):
                load_keyring(self.settings(directory))

    def test_batch_rotation_is_bounded_and_reports_more_work(self):
        store = FakeStore([2, 2, 2])
        result = rotate_bounded(store, batch_size=2, max_batches=2)
        self.assertEqual(result.rows_rotated, 4)
        self.assertEqual(result.batches, 2)
        self.assertTrue(result.more_may_remain)
        self.assertEqual(store.calls, [2, 2])

    def test_batch_rotation_stops_on_short_batch_and_rejects_invalid_bounds(self):
        store = FakeStore([1])
        result = rotate_bounded(store, batch_size=3)
        self.assertEqual((result.rows_rotated, result.batches,
                          result.more_may_remain), (1, 1, False))
        with self.assertRaises(ValueError):
            rotate_bounded(FakeStore([]), batch_size=0)
        with self.assertRaises(ValueError):
            rotate_bounded(FakeStore([]), max_batches=1001)

    def test_cli_fails_closed_when_not_enabled_and_does_not_print_connection(self):
        output = StringIO()
        code = main([], environ={
            "RONAS_EXPORT_FINDING_POSTGRES_DSN": "secret-dsn",
        }, output=output)
        self.assertEqual(code, 2)
        self.assertNotIn("secret-dsn", output.getvalue())


if __name__ == "__main__":
    unittest.main()
