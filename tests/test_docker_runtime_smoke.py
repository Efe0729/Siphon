"""The published image must pass offline runtime gates, not just build."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def smoke_module():
    spec = importlib.util.spec_from_file_location('docker_runtime_smoke', ROOT / 'scripts/docker_runtime_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_smoke_has_bounded_local_http_and_private_headers():
    module = smoke_module()
    assert module.READY_TIMEOUT <= 90
    assert module.SYNTHETIC_URL.startswith('https://example.test/videos/')
    assert module.SYNTHETIC_URL.endswith('/')
    with pytest.raises(AssertionError, match='HTTP status'):
        module.expect_status((401, {}, b'not a secret'), 200)


# The docker-publish workflow was dropped before the first public release:
# nothing here publishes container images, so there is no pipeline to check.
