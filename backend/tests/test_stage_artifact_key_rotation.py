import io
import os
from pathlib import Path
import tempfile
import unittest

from ronas_api.stage_artifact_key_rotation import (
    RotationConfigurationError, RotationSettings, load_key_material,
    rotate_bounded, main,
)


class FakeStore:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def rotate_batch(self, *, limit):
        self.calls.append(limit)
        return self.batches.pop(0) if self.batches else 0


class StageArtifactKeyRotationTests(unittest.TestCase):
    def settings(self, root, directory, scope):
        return RotationSettings(
            "postgresql://opaque", "key-b", directory, scope,
        )

    def private_key(self, path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(value * 32)
        path.chmod(0o600)

    def test_loads_active_and_retained_keys_from_private_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keys = root / "keys"
            keys.mkdir(mode=0o700)
            self.private_key(keys / "key-a.key", b"a")
            self.private_key(keys / "key-b.key", b"b")
            scope = root / "scope.key"
            self.private_key(scope, b"s")
            keyring, scope_key = load_key_material(
                self.settings(root, keys, scope),
            )
            self.assertEqual(set(keyring), {"key-a", "key-b"})
            self.assertEqual(keyring["key-b"], b"b" * 32)
            self.assertEqual(scope_key, b"s" * 32)

    def test_refuses_insecure_directory_file_and_missing_active_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keys = root / "keys"
            keys.mkdir(mode=0o700)
            self.private_key(keys / "key-a.key", b"a")
            scope = root / "scope.key"
            self.private_key(scope, b"s")
            with self.assertRaises(RotationConfigurationError):
                load_key_material(self.settings(root, keys, scope))
            (keys / "key-b.key").write_bytes(b"b" * 32)
            (keys / "key-b.key").chmod(0o644)
            with self.assertRaises(RotationConfigurationError):
                load_key_material(self.settings(root, keys, scope))
            (keys / "key-b.key").chmod(0o600)
            keys.chmod(0o755)
            with self.assertRaises(RotationConfigurationError):
                load_key_material(self.settings(root, keys, scope))

    def test_environment_requires_explicit_local_test_opt_in_and_inputs(self):
        with self.assertRaises(RotationConfigurationError):
            RotationSettings.from_environment({})
        values = {
            "RONAS_STAGE_ARTIFACT_ROTATION_ENABLE": "LOCAL_TEST_ONLY",
            "RONAS_STAGE_ARTIFACT_POSTGRES_DSN": "postgresql://opaque",
            "RONAS_STAGE_ARTIFACT_ACTIVE_KEY_ID": "key-b",
            "RONAS_STAGE_ARTIFACT_KEYRING_DIRECTORY": "/tmp/keys",
            "RONAS_STAGE_ARTIFACT_SCOPE_KEY_FILE": "/tmp/scope.key",
        }
        settings = RotationSettings.from_environment(values)
        self.assertEqual(settings.active_key_id, "key-b")
        with self.assertRaises(RotationConfigurationError):
            RotationSettings.from_environment({
                **values, "RONAS_STAGE_ARTIFACT_CONNECT_TIMEOUT": "999",
            })

    def test_rotates_in_small_batches_and_stops_on_short_batch(self):
        store = FakeStore([2, 1])
        result = rotate_bounded(store, batch_size=2, max_batches=10)
        self.assertEqual((result.rows_rotated, result.batches), (3, 2))
        self.assertFalse(result.more_may_remain)
        self.assertEqual(store.calls, [2, 2])

    def test_total_work_is_bounded_and_reports_possible_remaining_rows(self):
        store = FakeStore([2, 2, 2])
        result = rotate_bounded(store, batch_size=2, max_batches=2)
        self.assertEqual((result.rows_rotated, result.batches), (4, 2))
        self.assertTrue(result.more_may_remain)
        self.assertEqual(store.calls, [2, 2])

    def test_refuses_boolean_or_oversized_adapter_result(self):
        for value in (True, -1, 3):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                rotate_bounded(FakeStore([value]), batch_size=2, max_batches=1)

    def test_cli_prints_only_counts_and_never_database_exception_details(self):
        class Broken:
            def rotate_batch(self, *, limit):
                raise RuntimeError("secret DSN should not escape")
        env = {
            "RONAS_STAGE_ARTIFACT_ROTATION_ENABLE": "LOCAL_TEST_ONLY",
            "RONAS_STAGE_ARTIFACT_POSTGRES_DSN": "postgresql://opaque",
            "RONAS_STAGE_ARTIFACT_ACTIVE_KEY_ID": "key-b",
            "RONAS_STAGE_ARTIFACT_KEYRING_DIRECTORY": "/tmp/keys",
            "RONAS_STAGE_ARTIFACT_SCOPE_KEY_FILE": "/tmp/scope.key",
        }
        def factory(*args, **kwargs):
            return Broken()
        output = io.StringIO()
        import contextlib
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main([], environ=env, store_factory=factory, output=output)
        self.assertEqual(code, 2)
        self.assertNotIn("secret DSN", errors.getvalue())
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
