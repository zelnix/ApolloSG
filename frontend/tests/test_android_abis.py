"""Artifact-level release admission, independent of an Android SDK or live build."""
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
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
    def archive(self, abis=("arm64-v8a",), prefix="", override=None):
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

    def test_accepts_arm64_only_apk(self):
        self.assertEqual(guard.verify_archive(self.archive())["architectures"], ["arm64-v8a"])

    def test_accepts_play_bundle_native_layout(self):
        self.assertEqual(guard.verify_archive(self.archive(prefix="base/"))["nativeLibraries"], 2)

    def test_rejects_every_removed_architecture_even_when_arm64_is_present(self):
        for abi in ("armeabi-v7a", "x86", "x86_64"):
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
            guard.verify_archive(self.archive(abis=()))

    def test_explicit_arm64_test_build_is_an_allowed_subset(self):
        self.assertEqual(guard.verify_archive(self.archive(abis=("arm64-v8a",)), ["arm64-v8a"])["nativeLibraries"], 2)

    def test_cannot_admit_unsupported_target_with_expected_override(self):
        with self.assertRaisesRegex(ValueError, "approved 64-bit"):
            guard.verify_archive(self.archive(), ["x86"])

    def test_rejects_an_architecture_without_the_slm_runtime(self):
        path = self.archive(abis=(), override=lambda z: z.writestr("lib/arm64-v8a/libother.so", elf("arm64-v8a")))
        with self.assertRaisesRegex(ValueError, "SLM libraries.*arm64-v8a"):
            guard.verify_archive(path)

    def test_rejects_ambiguous_duplicate_native_library(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            path = self.archive(override=lambda z: z.writestr("lib/arm64-v8a/librnllama.so", elf("arm64-v8a")))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            guard.verify_archive(path)

    def result_file(self, value):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "eas.json"
        path.write_text(json.dumps(value))
        return path

    def test_eas_download_still_runs_full_binary_admission(self):
        source = self.archive()
        result = self.result_file([{"status": "FINISHED", "artifacts": {"buildUrl": "https://expo.dev/artifacts/eas/test.apk"}}])
        with patch.object(guard, "download_artifact", side_effect=lambda url, path: shutil.copyfile(source, path)) as download:
            self.assertEqual(guard.verify_eas_result(result)["nativeLibraries"], 2)
            download.assert_called_once()

    def test_eas_transfer_cannot_certify_an_incompatible_archive(self):
        source = self.archive(override=lambda z: z.writestr("lib/x86/libextra.so", elf("x86", 1)))
        result = self.result_file({"status": "FINISHED", "artifacts": {"buildUrl": "https://expo.dev/artifacts/eas/test.apk"}})
        with patch.object(guard, "download_artifact", side_effect=lambda url, path: shutil.copyfile(source, path)):
            with self.assertRaisesRegex(ValueError, "x86"):
                guard.verify_eas_result(result)

    def test_eas_metadata_must_be_finished_and_https(self):
        for value in [[], [{"status": "IN_PROGRESS"}], {"status": "FINISHED", "artifacts": {"buildUrl": "http://example.test/test.apk"}}]:
            with self.subTest(value=value), patch.object(guard, "download_artifact") as download:
                with self.assertRaises(ValueError):
                    guard.verify_eas_result(self.result_file(value))
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
