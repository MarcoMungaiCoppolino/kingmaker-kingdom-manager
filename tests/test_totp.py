"""The one-time codes (`access/totp.py`): the RFC 6238 vectors, the
window, the secret's two spellings, the recovery codes."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kingmaker.access import totp  # noqa: E402

results: list[tuple[str, bool]] = []

# RFC 6238, appendix B, SHA-1, eight digits
SEED = b"12345678901234567890"
for when, expected in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                       (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")):
    results.append((f"RFC 6238 at {when}: {expected}", totp.code_now(SEED, now=when, digits=8) == expected))

secret = totp.new_secret()
now = 1_800_000_000.0
code = totp.code_now(secret, now=now)
results.append(("a code is six digits", len(code) == 6 and code.isdigit()))
results.append(("the current code matches", totp.matches(secret, code, now=now)))
results.append(("spaces in the typed code are fine", totp.matches(secret, code[:3] + " " + code[3:], now=now)))
results.append(("the step just gone still matches", totp.matches(secret, totp.code_now(secret, now=now - 30), now=now)))
results.append(("the step to come matches too (clock drift)",
                totp.matches(secret, totp.code_now(secret, now=now + 30), now=now)))
results.append(("two steps away does not", not totp.matches(secret, totp.code_now(secret, now=now - 60), now=now)))
results.append(("a wrong code does not", not totp.matches(secret, "000000" if code != "000000" else "111111", now=now)))
results.append(("letters do not", not totp.matches(secret, "12345a", now=now)))
results.append(("five digits do not", not totp.matches(secret, code[:5], now=now)))

spelled = totp.encode_secret(secret)
results.append(("the secret is spelt in groups of four, base32, no padding",
                all(len(g) == 4 for g in spelled.split()) and "=" not in spelled))
results.append(("and reads back", totp.decode_secret(spelled) == secret))
results.append(("lower case reads back too", totp.decode_secret(spelled.lower()) == secret))
url = totp.otpauth_url(secret, "marco")
results.append(("the otpauth link names the issuer and the account",
                url.startswith("otpauth://totp/Kingmaker%3Amarco?") and "issuer=Kingmaker" in url
                and "period=30" in url and "digits=6" in url))

codes = totp.new_recovery_codes()
results.append(("eight recovery codes of ten characters, all different",
                len(codes) == 8 and all(len(c) == 10 for c in codes) and len(set(codes)) == 8))
results.append(("a recovery code is kept as a hash, spelling forgiven",
                totp.hash_recovery(codes[0]) == totp.hash_recovery(codes[0].upper() + " ")
                and totp.hash_recovery(codes[0]) != totp.hash_recovery(codes[1])))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
sys.exit(0 if all(ok for _n, ok in results) else 1)
