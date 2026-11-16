"""Version provenance for installed skills (#5423)."""

import pytest
import yaml

from specify_cli._assets import get_speckit_version
from specify_cli.agents import CommandRegistrar
from specify_cli.integrations import get_integration


def _frontmatter(content):
    return yaml.safe_load(content.split("---", 2)[1])


def test_metadata_version_is_a_string_and_missing_values_are_omitted():
    data = CommandRegistrar.build_skill_frontmatter(
        "claude", "speckit-plan", "Plan", "templates/commands/plan.md",
        version="1.10",
    )
    dumped = yaml.safe_dump(data, sort_keys=False)
    assert _frontmatter("---\n" + dumped + "---\n")["metadata"]["version"] == "1.10"
    assert 'version: "1.10"' in dumped

    for absent in (None, "", "unknown"):
        data = CommandRegistrar.build_skill_frontmatter(
            "claude", "speckit-plan", "Plan", "templates/commands/plan.md",
            version=absent,
        )
        assert "version" not in data["metadata"]


def test_builtin_skill_generators_identify_the_host_version():
    for key in ("claude", "vibe", "alquimia"):
        skill = get_integration(key)._render_skill(
            "plan", {"description": "Plan"}, "Body"
        )
        assert _frontmatter(skill)["metadata"]["version"] == get_speckit_version()


@pytest.mark.parametrize("key", ("claude", "vibe", "alquimia", "kimi", "hermes"))
def test_installed_builtin_skill_contains_generating_version(
    tmp_path, monkeypatch, key
):
    from specify_cli.integrations.manifest import IntegrationManifest

    integration = get_integration(key)
    if key == "hermes":
        # Hermes installs into the home directory; keep the test isolated.
        monkeypatch.setattr(
            integration, "_hermes_home_skills_dir",
            lambda: tmp_path / "isolated-hermes-home" / "skills",
        )

    manifest = IntegrationManifest(key, tmp_path)
    created = integration.setup(tmp_path, manifest, script_type="sh")
    matching = [
        path
        for path in created
        if path.name == "SKILL.md" and path.parent.name == "speckit-plan"
    ]
    assert len(matching) == 1

    text = matching[0].read_text(encoding="utf-8")
    assert _frontmatter(text)["metadata"]["version"] == get_speckit_version()
    assert f'version: "{get_speckit_version()}"' in text


def test_skill_versions_are_always_quoted_in_yaml():
    from specify_cli._utils import dump_frontmatter

    for value in ("1.10", "1.4.0", "1.4.1.dev0", "2026.11"):
        frontmatter = CommandRegistrar.build_skill_frontmatter(
            "claude", "speckit-plan", "Plan", "templates/commands/plan.md",
            version=value,
        )
        for serializer in (dump_frontmatter, CommandRegistrar.render_frontmatter):
            serialized = serializer(frontmatter)
            assert f'version: "{value}"' in serialized, serialized
            document = (
                serialized
                if serialized.startswith("---\n")
                else "---\n" + serialized + "\n---\n"
            )
            assert _frontmatter(document)["metadata"]["version"] == value


def test_unknown_version_is_not_written_to_installed_skills(tmp_path, monkeypatch):
    from specify_cli import _assets
    from specify_cli.integrations.manifest import IntegrationManifest

    monkeypatch.setattr(_assets, "get_speckit_version", lambda: "unknown")
    get_integration("claude").setup(
        tmp_path, IntegrationManifest("claude", tmp_path), script_type="sh"
    )
    installed = tmp_path / ".claude/skills/speckit-plan/SKILL.md"
    metadata = _frontmatter(installed.read_text(encoding="utf-8"))["metadata"]
    assert "version" not in metadata
