# Domestic stage-artifact key rotation command (LOCAL/TEST)

The PostgreSQL stage-artifact adapter already supports authenticated, bounded
key rotation. This command supplies an operator entry point while retaining
the existing LOCAL/TEST boundary. It never performs Stage or Production work.

Run from `backend/` after setting `RONAS_STAGE_ARTIFACT_ROTATION_ENABLE=LOCAL_TEST_ONLY`,
`RONAS_STAGE_ARTIFACT_POSTGRES_DSN`,
`RONAS_STAGE_ARTIFACT_ACTIVE_KEY_ID`,
`RONAS_STAGE_ARTIFACT_KEYRING_DIRECTORY`, and
`RONAS_STAGE_ARTIFACT_SCOPE_KEY_FILE`:

```sh
python -m ronas_api.stage_artifact_key_rotation --batch-size 100 --max-batches 100
```

Each `<key-id>.key` in the keyring directory must contain exactly 32 bytes,
be a regular file owned by the current user with mode 0600, and reside in a
directory owned by the current user with mode 0700. The stable scope key is
stored separately under the same file protections. The active key id must
have a corresponding key file; retained old keys must remain available until
all old rows have been rotated and independently verified. Key material is
never accepted on the command line or printed.

An invocation processes at most `batch-size × max-batches` rows, with a
maximum batch of 500 and maximum batch count of 1000. A full final batch is
reported as `more_may_remain=true`; rerun after inspection to continue. Row
updates remain atomic per batch through PostgreSQL `FOR UPDATE SKIP LOCKED`.
The command prints counts only. Its successful exit means only that the bounded
rotation operation completed without an adapter error; it is not a deployment,
data-use, or Production approval.
