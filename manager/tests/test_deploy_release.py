"""Portable deployment release tests."""

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy.py"
SPEC = importlib.util.spec_from_file_location("robots_deploy", MODULE_PATH)
assert SPEC and SPEC.loader
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


def test_release_files_exclude_local_state_and_secrets() -> None:
    archive_paths = {path.as_posix() for _, path in DEPLOY.release_files()}

    assert "compose.deploy.yml" in archive_paths
    assert "VERSION" in archive_paths
    assert "backend/Dockerfile" in archive_paths
    assert "frontend/Dockerfile" in archive_paths
    assert "install.cmd" in archive_paths
    assert "manage.cmd" in archive_paths
    assert "deploy/.env" not in archive_paths
    assert not any(
        excluded in path.split("/")
        for path in archive_paths
        for excluded in DEPLOY.RELEASE_EXCLUDED_DIRS
    )


def test_generated_release_secrets_are_distinct() -> None:
    values = {}
    for line in DEPLOY.generate_env().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            values[name] = value

    generated = [values[name] for name in DEPLOY.SECRET_NAMES]
    assert len(set(generated)) == len(generated)
    assert all(len(value) >= 24 for value in generated)


@pytest.mark.parametrize("value", ["0.1.0", "v1.2.3", "2.0.0-rc.1"])
def test_normalize_version_accepts_release_versions(value: str) -> None:
    assert DEPLOY.normalize_version(value) == value.removeprefix("v")


@pytest.mark.parametrize("value", ["latest", "1.2", "01.2.3", "1.2.3+local"])
def test_normalize_version_rejects_non_release_versions(value: str) -> None:
    with pytest.raises(ValueError):
        DEPLOY.normalize_version(value)


def test_registry_package_uses_immutable_images(tmp_path: Path) -> None:
    result = DEPLOY.package_release(
        tmp_path,
        offline=False,
        env_file=tmp_path / ".env",
        version="v1.2.3",
        registry_prefix="ghcr.io/example/robots-system",
    )

    assert result == 0
    archive = tmp_path / "RobotsSystem-v1.2.3-registry.zip"
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("RobotsSystem/release-manifest.json"))
    assert manifest["version"] == "1.2.3"
    assert manifest["mode"] == "registry"
    assert manifest["images"]["backend"] == "ghcr.io/example/robots-system-backend:v1.2.3"


@pytest.mark.parametrize(
    "prefix",
    ["https://ghcr.io/example/robots-system", "GHCR.IO/example/robots-system", r"ghcr.io\example\robots-system"],
)
def test_registry_images_reject_invalid_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        DEPLOY.registry_images(prefix, "1.2.3")
