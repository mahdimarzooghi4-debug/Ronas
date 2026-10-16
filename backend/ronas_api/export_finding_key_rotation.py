"""Operator-bounded LOCAL/TEST rotation for Export finding encryption keys."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import sys
from collections.abc import Callable, Mapping

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_BATCH = 500
_MAX_BATCHES = 1000


class RotationConfigurationError(ValueError):
    """Missing or unsafe LOCAL/TEST key-rotation configuration."""


@dataclass(frozen=True, slots=True)
class RotationSettings:
    dsn: str
    active_key_id: str
    keyring_directory: Path
    connect_timeout: int = 3

    def __post_init__(self) -> None:
        if (not isinstance(self.dsn, str) or not self.dsn or len(self.dsn) > 4096
                or "\x00" in self.dsn):
            raise RotationConfigurationError("PostgreSQL DSN required")
        if not isinstance(self.active_key_id, str) or not _KEY_ID.fullmatch(
                self.active_key_id):
            raise RotationConfigurationError("valid active key id required")
        if (not isinstance(self.keyring_directory, Path)
                or not self.keyring_directory.is_absolute()
                or self.keyring_directory.is_symlink()
                or ".." in self.keyring_directory.parts):
            raise RotationConfigurationError("absolute private keyring path required")
        if type(self.connect_timeout) is not int or not 1 <= self.connect_timeout <= 15:
            raise RotationConfigurationError("bounded connection timeout required")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None,
    ) -> "RotationSettings":
        values = os.environ if environ is None else environ
        if values.get("RONAS_EXPORT_FINDING_ROTATION_ENABLE") != "LOCAL_TEST_ONLY":
            raise RotationConfigurationError("explicit LOCAL/TEST opt-in missing")
        required = (
            "RONAS_EXPORT_FINDING_POSTGRES_DSN",
            "RONAS_EXPORT_FINDING_ACTIVE_KEY_ID",
            "RONAS_EXPORT_FINDING_KEYRING_DIRECTORY",
        )
        if any(not values.get(name) for name in required):
            raise RotationConfigurationError("required rotation configuration missing")
        timeout_text = values.get("RONAS_EXPORT_FINDING_CONNECT_TIMEOUT", "3")
        if not re.fullmatch(r"[0-9]{1,2}", timeout_text):
            raise RotationConfigurationError("invalid connection timeout")
        return cls(values[required[0]], values[required[1]],
                   Path(values[required[2]]), int(timeout_text))


def _read_key(path: Path) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RotationConfigurationError("platform cannot safely open private keys")
    try:
        initial = path.lstat()
        if (not stat.S_ISREG(initial.st_mode) or stat.S_IMODE(initial.st_mode) != 0o600
                or (hasattr(os, "getuid") and initial.st_uid != os.getuid())):
            raise RotationConfigurationError("private key ownership or permissions invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW
                             | getattr(os, "O_CLOEXEC", 0))
        try:
            opened = os.fstat(descriptor)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != initial.st_dev
                    or opened.st_ino != initial.st_ino
                    or stat.S_IMODE(opened.st_mode) != 0o600
                    or (hasattr(os, "getuid") and opened.st_uid != os.getuid())):
                raise RotationConfigurationError("private key changed during open")
            value = os.read(descriptor, 33)
            if len(value) != 32:
                raise RotationConfigurationError("key files must contain exactly 32 bytes")
            return value
        finally:
            os.close(descriptor)
    except RotationConfigurationError:
        raise
    except OSError as exc:
        raise RotationConfigurationError("private key material unavailable") from exc


def load_keyring(settings: RotationSettings) -> dict[str, bytes]:
    try:
        directory = settings.keyring_directory
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise RotationConfigurationError("keyring directory is not private")
        keys: dict[str, bytes] = {}
        for path in sorted(directory.iterdir()):
            if path.suffix != ".key":
                continue
            key_id = path.stem
            if not _KEY_ID.fullmatch(key_id) or key_id in keys:
                raise RotationConfigurationError("invalid or duplicate key id")
            keys[key_id] = _read_key(path)
        if not keys or settings.active_key_id not in keys:
            raise RotationConfigurationError("active encryption key is unavailable")
        return keys
    except RotationConfigurationError:
        raise
    except OSError as exc:
        raise RotationConfigurationError("keyring directory unavailable") from exc


@dataclass(frozen=True, slots=True)
class RotationResult:
    rows_rotated: int
    batches: int
    more_may_remain: bool


def rotate_bounded(store, *, batch_size: int = 100,
                   max_batches: int = 100) -> RotationResult:
    if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH:
        raise ValueError("batch size must be between 1 and 500")
    if type(max_batches) is not int or not 1 <= max_batches <= _MAX_BATCHES:
        raise ValueError("maximum batches must be between 1 and 1000")
    total = batches = 0
    for _ in range(max_batches):
        changed = store.rotate_batch(limit=batch_size)
        if type(changed) is not int or not 0 <= changed <= batch_size:
            raise RuntimeError("rotation adapter returned an invalid batch count")
        batches += 1
        total += changed
        if changed < batch_size:
            return RotationResult(total, batches, False)
    return RotationResult(total, batches, True)


def build_store(settings: RotationSettings, *, store_factory=None):
    from .postgres_export_findings import PostgresExportResearchFindingLedger

    factory = PostgresExportResearchFindingLedger if store_factory is None else store_factory
    return factory(
        settings.dsn, lambda _ref, _principal: None,
        keyring=load_keyring(settings), active_key_id=settings.active_key_id,
        connect_timeout=settings.connect_timeout,
    )


def main(argv: list[str] | None = None, *,
         environ: Mapping[str, str] | None = None,
         store_factory: Callable | None = None, output=None) -> int:
    parser = argparse.ArgumentParser(
        description="Rotate encrypted Export research notes in bounded PostgreSQL batches."
    )
    parser.add_argument("--batch-size", type=int, default=100,
                        choices=range(1, _MAX_BATCH + 1))
    parser.add_argument("--max-batches", type=int, default=100,
                        choices=range(1, _MAX_BATCHES + 1))
    args = parser.parse_args(argv)
    stream = sys.stdout if output is None else output
    try:
        settings = RotationSettings.from_environment(environ)
        store = build_store(settings, store_factory=store_factory)
        result = rotate_bounded(store, batch_size=args.batch_size,
                                max_batches=args.max_batches)
    except (RotationConfigurationError, ValueError, RuntimeError, OSError) as exc:
        print(f"rotation refused or failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception:
        print("rotation failed: internal error", file=sys.stderr)
        return 2
    print(f"rotated_rows={result.rows_rotated} batches={result.batches} "
          f"more_may_remain={str(result.more_may_remain).lower()}", file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
