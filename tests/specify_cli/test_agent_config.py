"""Tests for root agent configuration exports and defaults."""


def test_agent_config_importable():
    from specify_cli._agent_config import (
        AGENT_CONFIG,
        DEFAULT_INIT_INTEGRATION,
        SCRIPT_TYPE_CHOICES,
    )
    assert isinstance(AGENT_CONFIG, dict)
    assert DEFAULT_INIT_INTEGRATION == "copilot"
    assert "sh" in SCRIPT_TYPE_CHOICES


def test_script_type_choices_includes_python():
    from specify_cli._agent_config import SCRIPT_TYPE_CHOICES
    assert SCRIPT_TYPE_CHOICES.get("py") == "Python"
    # The three supported variants are sh, ps, and py.
    assert {"sh", "ps", "py"} <= set(SCRIPT_TYPE_CHOICES)


def test_workflow_init_valid_script_types_includes_python():
    from specify_cli.workflows.step.init import VALID_SCRIPT_TYPES
    assert "py" in VALID_SCRIPT_TYPES
    # Negative: an unknown variant is not accepted.
    assert "rb" not in VALID_SCRIPT_TYPES


def test_agent_config_re_exported_from_init():
    from specify_cli import AGENT_CONFIG, SCRIPT_TYPE_CHOICES
    assert isinstance(AGENT_CONFIG, dict)
    assert "sh" in SCRIPT_TYPE_CHOICES


def test_resolve_default_init_integration_unset(monkeypatch):
    from specify_cli._agent_config import (
        DEFAULT_INIT_INTEGRATION,
        DEFAULT_INIT_INTEGRATION_ENV_VAR,
        resolve_default_init_integration,
    )
    monkeypatch.delenv(DEFAULT_INIT_INTEGRATION_ENV_VAR, raising=False)
    assert resolve_default_init_integration() == DEFAULT_INIT_INTEGRATION


def test_resolve_default_init_integration_valid_override(monkeypatch):
    from specify_cli._agent_config import (
        DEFAULT_INIT_INTEGRATION_ENV_VAR,
        resolve_default_init_integration,
    )
    monkeypatch.setenv(DEFAULT_INIT_INTEGRATION_ENV_VAR, "gemini")
    assert resolve_default_init_integration() == "gemini"


def test_resolve_default_init_integration_whitespace_trimmed(monkeypatch):
    from specify_cli._agent_config import (
        DEFAULT_INIT_INTEGRATION_ENV_VAR,
        resolve_default_init_integration,
    )
    monkeypatch.setenv(DEFAULT_INIT_INTEGRATION_ENV_VAR, "  gemini  ")
    assert resolve_default_init_integration() == "gemini"


def test_resolve_default_init_integration_invalid_warns_and_falls_back(
    monkeypatch, capsys
):
    from specify_cli._agent_config import (
        DEFAULT_INIT_INTEGRATION,
        DEFAULT_INIT_INTEGRATION_ENV_VAR,
        resolve_default_init_integration,
    )
    monkeypatch.setenv(DEFAULT_INIT_INTEGRATION_ENV_VAR, "not-a-real-agent")
    assert resolve_default_init_integration() == DEFAULT_INIT_INTEGRATION
    captured = capsys.readouterr()
    assert "not-a-real-agent" in captured.err
    assert DEFAULT_INIT_INTEGRATION_ENV_VAR in captured.err


def test_resolve_default_init_integration_re_exported_from_init():
    from specify_cli import resolve_default_init_integration
    assert callable(resolve_default_init_integration)


def test_skill_frontmatter_version_is_optional_and_text():
    from specify_cli.agents import CommandRegistrar

    args = ("claude", "speckit-plan", "Plan", "templates/commands/plan.md")
    for absent in (None, "", "unknown"):
        fm = CommandRegistrar.build_skill_frontmatter(*args, version=absent)
        assert fm["metadata"] == {
            "author": "github-spec-kit",
            "source": "templates/commands/plan.md",
        }

    versioned = CommandRegistrar.build_skill_frontmatter(*args, version="1.10")
    assert versioned["metadata"]["version"] == "1.10"
    from specify_cli._utils import dump_frontmatter

    assert 'version: "1.10"' in dump_frontmatter(versioned)
    versioned["metadata"]["version"] = "1.4.0"
    assert 'version: "1.4.0"' in dump_frontmatter(versioned)
    assert type(versioned["metadata"]["version"]) is str


def test_native_skill_registrar_propagates_source_version_and_quotes_yaml(tmp_path):
    from specify_cli.agents import CommandRegistrar
    source_dir = tmp_path / "preset"
    source_dir.mkdir()
    command_dir = source_dir / "commands"
    command_dir.mkdir()
    (command_dir / "hello.md").write_text("---\ndescription: Hello\n---\nHello\n")
    target = tmp_path / "project"
    target.mkdir()
    registrar = CommandRegistrar(target)
    (target / ".claude" / "skills").mkdir(parents=True)
    names = registrar.register_commands(
        "claude",
        [
            {
                "name": "speckit.example.hello",
                "file": "commands/hello.md",
                "aliases": ["speckit.example.hi"],
            }
        ],
        "example",
        source_dir,
        target,
        version="1.10",
        author="Acme",
    )
    assert set(names) == {"speckit.example.hello", "speckit.example.hi"}
    import yaml

    for skill in ("speckit-example-hello", "speckit-example-hi"):
        content = (target / ".claude" / "skills" / skill / "SKILL.md").read_text()
        assert 'version: "1.10"' in content
        metadata = yaml.safe_load(content.split("---", 2)[1])["metadata"]
        assert metadata == {
            "author": "Acme",
            "source": "example:commands/hello.md",
            "version": "1.10",
        }
