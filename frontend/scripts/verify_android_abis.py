#!/usr/bin/env python3
"""Reject APK/AAB artifacts that cannot satisfy the required 64-bit SLM runtime."""
import argparse
import asyncio
import json
import re
import shutil
import struct
import sys
import tempfile
import urllib.parse
import zipfile
from collections import Counter
from pathlib import Path

SUPPORTED_ABIS = frozenset(json.loads(
    (Path(__file__).resolve().parents[1] / "config/android-abis.json").read_text()
)["supported"])
ELF_MACHINES = {"arm64-v8a": 183, "x86_64": 62}
REQUIRED_SLM_LIBRARIES = {"librnllama.so", "librnllama_jni.so"}


def verify_archive(path, expected_abis=None):
    expected = SUPPORTED_ABIS if expected_abis is None else frozenset(expected_abis)
    if not expected or not expected <= SUPPORTED_ABIS:
        raise ValueError("Expected architectures must be approved 64-bit targets")
    libraries = {}
    with zipfile.ZipFile(path) as archive:
        counts = Counter(info.filename for info in archive.infolist())
        for info in archive.infolist():
            match = re.fullmatch(r"(?:[^/]+/)?lib/([^/]+)/([^/]+\.so)", info.filename)
            if not match:
                continue
            abi, name = match.groups()
            if abi not in expected:
                raise ValueError(f"Unsupported or unexpected native architecture: {abi}")
            if counts[info.filename] != 1:
                raise ValueError(f"Duplicate native library: {info.filename}")
            with archive.open(info) as stream:
                header = stream.read(20)
            if len(header) < 20 or header[:6] != b"\x7fELF\x02\x01":
                raise ValueError(f"Native library is not a 64-bit little-endian ELF: {info.filename}")
            if struct.unpack_from("<H", header, 18)[0] != ELF_MACHINES[abi]:
                raise ValueError(f"Native library processor does not match its directory: {info.filename}")
            libraries.setdefault(abi, set()).add(name)
    if set(libraries) != expected:
        raise ValueError("Artifact is missing required native architectures")
    for abi, names in libraries.items():
        if not REQUIRED_SLM_LIBRARIES <= names:
            raise ValueError(f"Required SLM libraries are missing for {abi}")
    return {"architectures": sorted(libraries), "nativeLibraries": sum(map(len, libraries.values()))}


def verify_eas_result(filename):
    result = json.loads(Path(filename).read_text())
    builds = result if isinstance(result, list) else [result]
    if len(builds) != 1 or builds[0].get("status") != "FINISHED":
        raise ValueError("Expected exactly one finished EAS build")
    url = builds[0].get("artifacts", {}).get("buildUrl", "")
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("EAS artifact must have an HTTPS download URL")
    # Do not log signed CDN URLs. Inspect the exact artifact before publishing its link.
    with tempfile.TemporaryDirectory(prefix="apollo-abi-") as directory:
        artifact = Path(directory) / "release.apk"
        download_artifact(url, artifact)
        return verify_archive(artifact)


def download_artifact(url, target):
    """Use a browser transport: Expo's artifact edge rejects plain HTTP clients."""
    async def download():
        from playwright.async_api import Error, async_playwright

        async with async_playwright() as playwright:
            bundled = playwright.chromium.executable_path
            executable = bundled if Path(bundled).is_file() else (
                shutil.which("chromium") or shutil.which("google-chrome"))
            browser = await playwright.chromium.launch(
                executable_path=executable, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                async with page.expect_download(timeout=120000) as pending:
                    try:
                        await page.goto(url, timeout=60000)
                    except Error as error:
                        # A successful file navigation intentionally aborts document loading.
                        if "Download is starting" not in str(error) and "net::ERR_ABORTED" not in str(error):
                            raise
                artifact = await pending.value
                await artifact.save_as(target)
                if await artifact.failure():
                    raise ValueError("Expo artifact download did not complete")
            finally:
                await browser.close()

    asyncio.run(download())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("artifact", nargs="?")
    source.add_argument("--eas-result")
    parser.add_argument("--expected-abi", action="append", help="Approved subset for a deliberately scoped test APK")
    args = parser.parse_args()
    if args.eas_result and args.expected_abi:
        parser.error("EAS production builds must include every supported architecture")
    try:
        result = verify_eas_result(args.eas_result) if args.eas_result else verify_archive(args.artifact, args.expected_abi)
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print(f"Android ABI admission failed: {error}", file=sys.stderr)
        return 1
    print("Android ABI admission passed: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
