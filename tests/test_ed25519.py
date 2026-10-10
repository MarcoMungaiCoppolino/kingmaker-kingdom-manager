"""The signatures (`access/ed25519.py`): the RFC 8032 vectors, a round
trip on fresh keys, and every way a signature can be wrong."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kingmaker.access import ed25519  # noqa: E402

results: list[tuple[str, bool]] = []

# RFC 8032, section 7.1: seed, public key, message, signature
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]
for i, (seed, public, message, signature) in enumerate(VECTORS, 1):
    seed_b, public_b, message_b, signature_b = (bytes.fromhex(seed), bytes.fromhex(public),
                                                bytes.fromhex(message), bytes.fromhex(signature))
    results.append((f"RFC 8032 vector {i}: the public key", ed25519.public_key(seed_b) == public_b))
    results.append((f"RFC 8032 vector {i}: the signature", ed25519.sign(seed_b, message_b) == signature_b))
    results.append((f"RFC 8032 vector {i}: verifies", ed25519.verify(public_b, message_b, signature_b)))

seed = ed25519.new_seed()
public = ed25519.public_key(seed)
message = b"save-e3-s7.zip 1b066ef8789b"
signature = ed25519.sign(seed, message)
results.append(("a fresh seed is 32 bytes and its key too", len(seed) == 32 and len(public) == 32))
results.append(("a round trip verifies", ed25519.verify(public, message, signature)))
results.append(("another message does not", not ed25519.verify(public, message + b"!", signature)))
results.append(("another key does not", not ed25519.verify(ed25519.public_key(ed25519.new_seed()), message, signature)))
flipped = bytes([signature[0] ^ 1]) + signature[1:]
results.append(("a flipped bit does not", not ed25519.verify(public, message, flipped)))
results.append(("a short signature is false, not an error", not ed25519.verify(public, message, signature[:40])))
results.append(("a short key is false, not an error", not ed25519.verify(public[:10], message, signature)))
results.append(("junk is false, not an error", not ed25519.verify(b"\xff" * 32, message, b"\x00" * 64)))
high = signature[:32] + (ed25519.Q + 1).to_bytes(32, "little")
results.append(("a scalar past the group order is refused", not ed25519.verify(public, message, high)))
results.append(("signing is deterministic", ed25519.sign(seed, message) == signature))
try:
    ed25519.sign(b"short", message)
    results.append(("a wrong seed length raises", False))
except ValueError:
    results.append(("a wrong seed length raises", True))
started = time.perf_counter()
for _ in range(20):
    ed25519.verify(public, message, signature)
per_verify = (time.perf_counter() - started) / 20
results.append((f"a verification takes well under a tenth of a second ({per_verify * 1000:.1f} ms)",
                per_verify < 0.1))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
sys.exit(0 if all(ok for _n, ok in results) else 1)
