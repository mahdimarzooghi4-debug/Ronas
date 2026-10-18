# Household stage observation artifact API

The existing shared Household Bearer API can transfer the same opaque stage
artifact used by the household browser workflow. These routes mount only when
the explicitly injected stage context authority and artifact store are present.

- `PUT /api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations/artifacts/{stage_ref}` accepts raw image/PDF bytes, not multipart data. It requires the signed household Bearer principal, current profile access, and exact current case version, input revision, plan digest, stage reference, and observation-requirements digest in the `X-Ronas-*` headers. The server streams at most 8 MiB, checks declared framing length, validates the media signature, and returns the content digest and byte length.
- `GET /api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations/artifacts/{stage_ref}/{digest}` returns bytes only when the same owner has a recorded stage-observation receipt linking that stage and digest. Responses are non-cacheable and set `X-Content-Type-Options: nosniff`.
- The client then submits the digest to the existing version-bound `POST .../stage-observations` command. Uploading or reading a file never records a receipt, completes a cultivation stage, evaluates an agricultural requirement, or approves specialist advice.

The content store remains injected and encrypted by its adapter. This API does not make a filesystem adapter suitable for Production or authorize real household data.
