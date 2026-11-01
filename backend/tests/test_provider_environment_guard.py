"""The preview simulator — the module ships with the project, but only the preview server installs it.

Production is recognised by NOT being the preview server: no APOLLO_PREVIEW_SIMULATOR=on and no
*.preview.emergentagent.com APP_URL (which only the Emergent preview workspace sets).
APOLLO_ENV is deliberately not the switch: the deployment's secrets still hold an old "preview" value of it.

Emergent deploys the whole project, `services/higgins/preview/` included, so the directory's presence
proves nothing (it was the guard before, and production ended up answering from the simulator).
A missing, empty or unrecognised value is production — `register_preview_handler()` refuses,
`get_provider_mode()` answers "live" and `generate()` reaches the live provider only.

Run: cd /app/backend && python -m pytest tests/test_provider_environment_guard.py -q
"""
from __future__ import annotations

import pathlib

import pytest

from services.higgins import provider
from services.higgins.adapters import gemini as gemini_adapter
from services.higgins.provider import ProviderFailure

SOURCE = pathlib.Path(provider.__file__).read_text()
# Captured at import, before conftest's autouse fixture swaps generate() for a blocker.
_REAL_GENERATE = provider.generate
SERVER = (pathlib.Path(__file__).resolve().parents[1] / "server.py").read_text()


async def _handler(*_args, **_kwargs):
    raise AssertionError("the handler itself is not exercised here")


@pytest.mark.parametrize("value", [None, "", "off", "preview", "production", "true", "1", "yes", "onn"])
def test_anything_but_preview_refuses_the_simulator_and_stays_live(monkeypatch, value):
    monkeypatch.setattr(provider, "_preview_generate", None)
    monkeypatch.delenv("APP_URL", raising=False)
    if value is None:
        monkeypatch.delenv("APOLLO_PREVIEW_SIMULATOR", raising=False)
    else:
        monkeypatch.setenv("APOLLO_PREVIEW_SIMULATOR", value)
    assert provider.preview_environment() is False
    with pytest.raises(RuntimeError):
        provider.register_preview_handler(_handler)
    assert provider.get_provider_mode() == "live"


@pytest.mark.parametrize("value", ["on", " ON "])
def test_explicit_preview_installs_the_simulator_and_blocks_the_live_client(monkeypatch, value):
    monkeypatch.setattr(provider, "_preview_generate", None)
    monkeypatch.setenv("APOLLO_PREVIEW_SIMULATOR", value)
    provider.register_preview_handler(_handler)  # monkeypatch restores the real value afterwards
    assert provider.get_provider_mode() == "preview"
    # With the simulator answering, the live client must be unreachable — not merely unused.
    with pytest.raises(ProviderFailure):
        gemini_adapter.client()


def test_the_preview_workspace_is_recognised_by_its_own_address(monkeypatch):
    """The preview server runs the simulator with no setting to remember: the workspace's APP_URL says where it is."""
    monkeypatch.setattr(provider, "_preview_generate", None)
    monkeypatch.delenv("APOLLO_PREVIEW_SIMULATOR", raising=False)
    monkeypatch.setenv("APP_URL", "https://case-source-preview--3ijise2t.preview.emergentagent.com")
    assert provider.preview_environment() is True
    provider.register_preview_handler(_handler)
    assert provider.get_provider_mode() == "preview"
    with pytest.raises(ProviderFailure):
        gemini_adapter.client()


@pytest.mark.parametrize("url", ["https://threat-patrol-1.emergent.host", "https://apollo.example.com", "",
                                 "https://case-source-preview--3ijise2t.preview.emergentagent.com.evil.example", "https://preview.emergentagent.com",
                                 "not a url", "https://emergent.host/x.preview.emergentagent.com"])
def test_the_published_app_and_lookalike_addresses_stay_live(monkeypatch, url):
    monkeypatch.setattr(provider, "_preview_generate", None)
    monkeypatch.delenv("APOLLO_PREVIEW_SIMULATOR", raising=False)
    monkeypatch.setenv("APP_URL", url)
    assert provider.preview_environment() is False
    with pytest.raises(RuntimeError):
        provider.register_preview_handler(_handler)
    assert provider.get_provider_mode() == "live"


def test_a_stale_apollo_env_preview_cannot_switch_production_to_the_simulator(monkeypatch):
    """The deployment still carries APOLLO_ENV=preview from an earlier design; it must decide nothing."""
    monkeypatch.setattr(provider, "_preview_generate", None)
    monkeypatch.delenv("APOLLO_PREVIEW_SIMULATOR", raising=False)
    monkeypatch.delenv("APP_URL", raising=False)
    monkeypatch.setenv("APOLLO_ENV", "preview")
    monkeypatch.setenv("APOLLO_PROVIDER_MODE", "simulated")
    assert provider.preview_environment() is False
    with pytest.raises(RuntimeError):
        provider.register_preview_handler(_handler)
    assert provider.get_provider_mode() == "live"


def test_the_production_gateway_names_no_preview_module():
    for forbidden in ("preview_simulator", "mock_provider", "from services.higgins.preview"):
        assert forbidden not in SOURCE, f"provider.py must not reference {forbidden}"


def test_startup_installs_the_dispatch_only_behind_the_explicit_switch():
    install = "from services.higgins.preview.dispatch import install_preview_provider"
    assert install in SERVER
    guard = SERVER.index("if preview_environment():")
    assert guard < SERVER.index(install), "the import must sit behind the explicit switch"
    assert "except ImportError" not in SERVER, "a missing module must not be the production signal"


def test_production_startup_loads_no_simulation_module():
    """The simulation files ship with the project (Emergent deploys the whole snapshot), so the guarantee
    is that production never LOADS them: importing the whole app without the switch must leave every
    simulation module out of memory."""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k not in ("APOLLO_PREVIEW_SIMULATOR", "APP_URL")}
    probe = ("import sys, server; "
             "loaded = sorted(m for m in sys.modules if m.startswith('services.higgins.preview') or m.endswith('preview_analysis')); "
             "print('LOADED=' + ','.join(loaded))")
    out = subprocess.run([sys.executable, "-c", probe], cwd=str(pathlib.Path(__file__).resolve().parents[1]),
                         env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert "LOADED=\n" in out.stdout or out.stdout.strip().endswith("LOADED="), out.stdout[-400:]


@pytest.mark.anyio
async def test_preview_runs_every_production_check_before_the_simulator(monkeypatch):
    """The simulator replaces only the network call: a request production refuses is refused in preview."""
    from services.higgins.ai_request import Part
    from services.higgins.llm_boundary import Purpose
    calls = []

    async def _handler(*_args, **_kwargs):
        calls.append(1)

    monkeypatch.setattr(provider, "_preview_generate", _handler)
    image = Part.from_bytes(data=b"\x89PNG fake", mime_type="image/png")
    with pytest.raises(ProviderFailure) as refused:
        await _REAL_GENERATE("", [image], model="gemini-3.1-flash-lite", capability="text", purpose=Purpose.ORDINARY_CHAT)
    assert refused.value.code == "privacy_violation"
    with pytest.raises(ProviderFailure) as unknown_model:
        await _REAL_GENERATE("", "hello", model="not-a-model", capability="text", purpose=Purpose.ORDINARY_CHAT)
    assert unknown_model.value.code == "provider_configuration"
    with pytest.raises(ProviderFailure) as no_search:  # a model that can't search is refused, never swapped for one that can
        await _REAL_GENERATE("", "hello", model="gemini-2.5-flash-lite", capability="json", web_search=True, purpose=Purpose.TC_FLYBY_SEARCH)
    assert no_search.value.code == "provider_configuration"
    assert calls == [], "the simulator must never answer a request production would refuse"


def test_every_purpose_the_code_names_exists_and_image_purposes_may_send_images():
    """A purpose that doesn't exist fails only at call time — which only production reached."""
    import re
    from services.higgins.llm_boundary import Purpose
    root = pathlib.Path(__file__).resolve().parents[1]
    names = set()
    for path in [*root.glob("routers/*.py"), *root.glob("services/**/*.py")]:
        names |= set(re.findall(r"\bPurpose\.([A-Z_]+)\b", path.read_text()))
    assert names, "no purposes found"
    missing = sorted(n for n in names if n not in Purpose.__members__)
    assert not missing, f"code names purposes that don't exist: {missing}"
    assert Purpose.VISION_INVESTIGATION in provider._BINARY_AUTHORISED_PURPOSES
