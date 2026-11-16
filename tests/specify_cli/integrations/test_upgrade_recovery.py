"""Built-in integration upgrades must not destroy working files on failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from specify_cli.integrations import get_integration
from specify_cli.integrations.manifest import IntegrationManifest
from tests.specify_cli.integrations._helpers import _init_project, _run_in_project


@pytest.mark.parametrize("force", (False, True))
def test_failed_upgrade_restores_original_generated_bytes_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force: bool
) -> None:
    project = _init_project(tmp_path, "claude")
    integration = get_integration("claude")
    manifest = IntegrationManifest.load("claude", project)
    own_paths = [
        rel for rel in manifest.files
        if rel.startswith(".claude/") and (project / rel).is_file()
    ]
    assert own_paths, manifest.files
    target = project / own_paths[0]
    original = target.read_bytes()
    manifest_file = manifest.manifest_path
    original_manifest = manifest_file.read_bytes()

    if force:
        target.write_bytes(original + b"\n# personal customization\n")
    expected = target.read_bytes()
    rogue = project / ".claude" / "commands" / "speckit-dirty-on-failure.md"
    assert not rogue.exists()

    def partial_then_fail(project_root, new_manifest, **kwargs):
        new_manifest.record_file(target.relative_to(project_root), b"CORRUPT")
        new_manifest.record_file(rogue.relative_to(project_root), b"NEW FILE")
        raise RuntimeError("probe: generation failed after two writes")

    monkeypatch.setattr(integration, "setup", partial_then_fail)
    args = ["integration", "upgrade", "claude"]
    if force:
        args.append("--force")
    result = _run_in_project(project, args)

    assert result.exit_code != 0
    assert b"probe" not in target.read_bytes()
    assert target.read_bytes() == expected, result.output
    assert not rogue.exists(), "Failed regeneration left newly written files behind"
    assert manifest_file.read_bytes() == original_manifest


def test_nonforce_refuses_modified_generated_files_before_mutating(
    tmp_path: Path
) -> None:
    project = _init_project(tmp_path, "claude")
    manifest = IntegrationManifest.load("claude", project)
    relative = next(
        r for r in manifest.files if r.startswith(".claude/")
    )
    changed = project / relative
    changed.write_bytes(changed.read_bytes() + b"\n# customization\n")
    before_manifest = manifest.manifest_path.read_bytes()
    result = _run_in_project(project, ["integration", "upgrade", "claude"])
    assert result.exit_code != 0
    assert b"customization" in changed.read_bytes()
    assert manifest.manifest_path.read_bytes() == before_manifest


@pytest.mark.parametrize("writer", ("manifest", "host_helper", "host_text"))
@pytest.mark.parametrize("preexisting", (True, False))
def test_partial_failed_write_restores_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str, preexisting: bool,
) -> None:
    """An interrupted owned write must not leave half a generated command."""
    from specify_cli.integrations._file_changes import write_bytes, write_text

    project = _init_project(tmp_path, "claude")
    manifest = IntegrationManifest.load("claude", project)
    target = (
        project / next(
            relative for relative in manifest.files if relative.startswith(".claude/")
        ) if preexisting else project / ".claude/commands/speckit-new-rollback.md"
    )
    before = target.read_bytes() if preexisting else None
    user_file = project / ".claude/commands/user-notes.md"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_bytes(b"Personal note: do not remove")
    manifest_before = manifest.manifest_path.read_bytes()
    original_write = Path.write_bytes

    original_write_text = Path.write_text

    def fail_after_partial_write(path: Path, content: bytes) -> int:
        if path == target:
            original_write(path, b"TRUNCATED")
            raise OSError("simulated interrupted write")
        return original_write(path, content)

    def fail_after_partial_text(path: Path, content: str, **kwargs) -> int:
        if path == target:
            original_write(path, b"TRUNCATED")
            raise OSError("simulated interrupted text write")
        return original_write_text(path, content, **kwargs)

    integration = get_integration("claude")

    def interrupted_setup(project_root, new_manifest, **kwargs):
        monkeypatch.setattr(Path, "write_bytes", fail_after_partial_write)
        monkeypatch.setattr(Path, "write_text", fail_after_partial_text)
        try:
            if writer == "manifest":
                new_manifest.record_file(target.relative_to(project_root), b"COMPLETE")
            elif writer == "host_helper":
                write_bytes(target, b"COMPLETE")
            else:
                write_text(target, "COMPLETE")
        finally:
            monkeypatch.setattr(Path, "write_bytes", original_write)
            monkeypatch.setattr(Path, "write_text", original_write_text)

    monkeypatch.setattr(integration, "setup", interrupted_setup)
    result = _run_in_project(project, ["integration", "upgrade", "claude", "--force"])
    assert result.exit_code != 0
    assert (target.read_bytes() if target.exists() else None) == before, result.output
    assert user_file.read_bytes() == b"Personal note: do not remove"
    assert manifest.manifest_path.read_bytes() == manifest_before


def test_failed_builtin_secondary_install_preserves_user_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsuccessful install cannot discard an existing unrelated user file."""
    project = _init_project(tmp_path, "claude")
    target = project / ".agents/skills/speckit-plan/SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"My personal prompt")
    state_path = project / ".specify/integration.json"
    state_bytes = state_path.read_bytes()

    def partial_then_fail(project_root, new_manifest, **kwargs):
        new_manifest.record_file(target.relative_to(project_root), b"PARTIAL")
        raise RuntimeError("probe: secondary installation failed during setup")

    monkeypatch.setattr(get_integration("codex"), "setup", partial_then_fail)
    result = _run_in_project(project, ["integration", "install", "codex", "--force", "--script", "sh"])
    assert result.exit_code != 0
    assert target.read_bytes() == b"My personal prompt", result.output
    assert state_path.read_bytes() == state_bytes, result.output


def test_failed_builtin_switch_restores_previous_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup failure after Phase 1 must not uninstall the old integration."""
    project = _init_project(tmp_path, "claude")
    manifest = IntegrationManifest.load("claude", project)
    previous_file = project / next(
        rel for rel in manifest.files if rel.startswith(".claude/")
    )
    previous_bytes = previous_file.read_bytes()
    state_path = project / ".specify/integration.json"
    state_bytes = state_path.read_bytes()
    target = project / ".github/agents/speckit-partial.agent.md"
    assert not target.exists()

    def partial_then_fail(project_root, new_manifest, **kwargs):
        new_manifest.record_file(target.relative_to(project_root), b"PARTIAL")
        raise RuntimeError("probe: switch target failed during setup")

    monkeypatch.setattr(get_integration("copilot"), "setup", partial_then_fail)
    result = _run_in_project(project, ["integration", "switch", "copilot", "--script", "sh"])
    assert result.exit_code != 0
    assert previous_file.read_bytes() == previous_bytes, result.output
    assert state_path.read_bytes() == state_bytes, result.output
    assert not target.exists(), result.output
