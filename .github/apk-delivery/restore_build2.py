"""Restore a completed APK for delivery; this script does not compile application code."""
from pathlib import Path
import hashlib
import bsdiff4

BASE_SHA256 = "35e9030fe467e55e9a1679bbab61cb2881dc0212e4151e71d8c76ddaec6e7f49"
PATCH_SHA256 = "98fd43ab33451255b9cd51dabfa9802e53fda4ea6f82b776def61df9e0440311"
APK_SHA256 = "52e2b809c3fdc5bb741c2dcdbdad9c31deb68a68b9fe8ff557090e6b8d18991a"
APK_BYTES = 177604316

def checked(data: bytes, expected: str, name: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(name + " checksum mismatch; refusing publication")
    return data

def main() -> None:
    candidates = list(Path("baseline").rglob("*.apk"))
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one archived baseline APK")
    baseline = checked(candidates[0].read_bytes(), BASE_SHA256, "Baseline APK")
    parts = Path(__file__).parent
    delta = checked(
        b"".join((parts / ("build2.bsdiff.part" + str(i))).read_bytes() for i in range(2)),
        PATCH_SHA256, "Binary transfer",
    )
    apk = checked(bsdiff4.patch(baseline, delta), APK_SHA256, "Restored APK")
    if len(apk) != APK_BYTES:
        raise RuntimeError("Restored APK size mismatch")
    output = Path("delivery")
    output.mkdir(exist_ok=True)
    target = output / "ApolloSG-1.1.0-build2-arm64.apk"
    target.write_bytes(apk)
    target.with_suffix(".apk.sha256").write_text(APK_SHA256 + "  " + target.name + "\n")
    print("Restored existing APK unchanged:", target.name, len(apk), APK_SHA256)

if __name__ == "__main__":
    main()
