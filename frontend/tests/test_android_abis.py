"""Artifact-level release admission, independent of an Android SDK or live build."""
import importlib.util
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "android_abi_guard", Path(__file__).resolve().parents[1] / "scripts/verify_android_abis.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def elf(abi, elf_class=2):
    header = bytearray(20)
    header[:6] = b"\x7fELF" + bytes([elf_class, 1])
    struct.pack_into("<H", header, 18, {"arm64-v8a": 183, "x86_64": 62}.get(abi, 3))
    return bytes(header)


class AndroidAbiAdmissionTests(unittest.TestCase):
    def archive(self, abis=("arm64-v8a", "x86_64"), prefix="", override=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "release.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for abi in abis:
                for name in ("librnllama.so", "librnllama_jni.so"):
                    archive.writestr(f"{prefix}lib/{abi}/{name}", elf(abi))
            if override:
                override(archive)
        return path

    def test_accepts_apk_with_both_64_bit_runtimes(self):
        self.assertEqual(guard.verify_archive(self.archive())["architectures"], ["arm64-v8a", "x86_64"])

    def test_accepts_play_bundle_native_layout(self):
        self.assertEqual(guard.verify_archive(self.archive(prefix="base/"))["nativeLibraries"], 4)

    def test_rejects_each_32_bit_architecture_even_when_64_bit_is_present(self):
        for abi in ("armeabi-v7a", "x86"):
            with self.subTest(abi=abi), self.assertRaisesRegex(ValueError, abi):
                guard.verify_archive(self.archive(override=lambda z: z.writestr(f"lib/{abi}/libextra.so", elf(abi, 1))))

    def test_rejects_32_bit_elf_under_a_64_bit_directory(self):
        with self.assertRaisesRegex(ValueError, "64-bit"):
            guard.verify_archive(self.archive(override=lambda z: z.writestr("lib/arm64-v8a/libextra.so", elf("arm64-v8a", 1))))

    def test_rejects_library_for_wrong_processor(self):
        with self.assertRaisesRegex(ValueError, "processor"):
            guard.verify_archive(self.archive(override=lambda z: z.writestr("lib/arm64-v8a/libextra.so", elf("x86_64"))))

    def test_rejects_missing_architecture(self):
        with self.assertRaisesRegex(ValueError, "missing required native architectures"):
            guard.verify_archive(self.archive(abis=("arm64-v8a",)))

    def test_explicit_arm64_test_build_is_an_allowed_subset(self):
        self.assertEqual(guard.verify_archive(self.archive(abis=("arm64-v8a",)), ["arm64-v8a"])["nativeLibraries"], 2)

    def test_cannot_admit_unsupported_target_with_expected_override(self):
        with self.assertRaisesRegex(ValueError, "approved 64-bit"):
            guard.verify_archive(self.archive(), ["x86"])

    def test_rejects_an_architecture_without_the_slm_runtime(self):
        path = self.archive(abis=("arm64-v8a",), override=lambda z: z.writestr("lib/x86_64/libother.so", elf("x86_64")))
        with self.assertRaisesRegex(ValueError, "SLM libraries.*x86_64"):
            guard.verify_archive(path)

    def test_rejects_ambiguous_duplicate_native_library(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            path = self.archive(override=lambda z: z.writestr("lib/arm64-v8a/librnllama.so", elf("arm64-v8a")))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            guard.verify_archive(path)


if __name__ == "__main__":
    unittest.main()
