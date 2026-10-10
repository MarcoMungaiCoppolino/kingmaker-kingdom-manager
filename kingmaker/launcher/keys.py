"""The owner's release keys: the public halves of the Ed25519 keys the
installers are signed with (`packaging/sign_release.py`, run by the owner
after the release workflow built the draft). The launcher refuses to run
a downloaded installer whose hash is not in a `SHA256SUMS` signed by one
of these (`core.verify_download`). A list, so a release signed by the old
key may ship a new one next to it; the old key is dropped a release later.

A release from before the signatures carries no sums and no signature:
the launcher says so and asks before running it."""

RELEASE_KEYS: tuple[str, ...] = (
    # 2026-10-10, the first key
    "2aa3c7305e0158ce8b811523b157825fcd95d69f94d14f5d5922146179362fa2",
)
SUMS_NAME = "SHA256SUMS"
SIG_NAME = "SHA256SUMS.sig"
