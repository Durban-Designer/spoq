"""Tests for multi-agent scaffolding (agents.py + init_cmd integration)."""

from __future__ import annotations

import filecmp
import json
import shutil
import tomllib
from pathlib import Path

import pytest

from spoq_server.agents import (
    AGENTS,
    MODEL_ROLES,
    install_commands,
    parse_agents,
    roles_section,
    setup_agent_mcp,
    translate_body,
)
from spoq_server.init_cmd import (
    _BUNDLED_SKILLS_DIR,
    CLAUDE_ONLY_SKILLS,
    CORE_SKILLS,
    run_init,
)


class TestParseAgents:
    def test_default_is_claude(self) -> None:
        assert parse_agents(None) == ["claude"]
        assert parse_agents("") == ["claude"]

    def test_comma_separated_string(self) -> None:
        assert parse_agents("claude,qwen,codex,cursor") == [
            "claude", "qwen", "codex", "cursor"
        ]

    def test_whitespace_and_case_tolerant(self) -> None:
        assert parse_agents(" Qwen , CODEX ") == ["qwen", "codex"]

    def test_list_input(self) -> None:
        assert parse_agents(["codex", "claude"]) == ["codex", "claude"]

    def test_dedupes_preserving_order(self) -> None:
        assert parse_agents("qwen,claude,qwen") == ["qwen", "claude"]

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="gemini"):
            parse_agents("claude,gemini")


class TestInstallCommands:
    def test_qwen_writes_valid_toml(self, tmp_path: Path) -> None:
        count = install_commands(
            AGENTS["qwen"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path
        )
        assert count >= 1
        tomls = list((tmp_path / ".qwen" / "commands").glob("*.toml"))
        assert tomls
        for f in tomls:
            data = tomllib.loads(f.read_text())
            assert data["description"]
            assert data["prompt"]
            # Resource references rewritten away from the Claude path.
            assert ".claude/skills/" not in data["prompt"]

    def test_codex_writes_skills(self, tmp_path: Path) -> None:
        count = install_commands(
            AGENTS["codex"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path
        )
        assert count >= 1
        skill_files = list((tmp_path / ".agents" / "skills").glob("*/SKILL.md"))
        assert skill_files
        assert not (tmp_path / ".codex" / "prompts").exists()
        for f in skill_files:
            data = f.read_text()
            assert data.startswith("---\n")
            assert "name:" in data
            assert "description:" in data
            assert ".claude/skills/" not in data
            assert ".Codex/skills/" not in data

    def test_shared_lib_copied_alongside(self, tmp_path: Path) -> None:
        install_commands(AGENTS["qwen"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        # lib must sit at the commands root so scripts resolve it via
        # __file__.parent.parent.parent / "lib"
        assert (tmp_path / ".qwen" / "commands" / "lib" / "epic_utils.py").exists()

    def test_lib_is_not_a_command(self, tmp_path: Path) -> None:
        install_commands(AGENTS["qwen"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        assert not (tmp_path / ".qwen" / "commands" / "lib.toml").exists()

    def test_script_resources_copied(self, tmp_path: Path) -> None:
        install_commands(AGENTS["qwen"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        script = (
            tmp_path / ".qwen" / "commands" / "epic-planning"
            / "scripts" / "analyze-dag.py"
        )
        assert script.exists()

    def test_cursor_writes_md_commands(self, tmp_path: Path) -> None:
        count = install_commands(
            AGENTS["cursor"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path
        )
        assert count >= 1
        md_files = list((tmp_path / ".cursor" / "commands").glob("*.md"))
        assert md_files
        for f in md_files:
            data = f.read_text()
            # Description blockquote leads the file; no frontmatter.
            assert data.startswith("> ")
            assert ".claude/skills/" not in data

    def test_cursor_script_resources_copied(self, tmp_path: Path) -> None:
        install_commands(AGENTS["cursor"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        script = (
            tmp_path / ".cursor" / "commands" / "epic-planning"
            / "scripts" / "analyze-dag.py"
        )
        assert script.exists()
        # lib sits at the commands root so scripts resolve it via
        # __file__.parent.parent.parent / "lib"
        assert (tmp_path / ".cursor" / "commands" / "lib" / "epic_utils.py").exists()
        assert not (tmp_path / ".cursor" / "commands" / "lib.md").exists()

    def test_codex_script_resources_copied(self, tmp_path: Path) -> None:
        install_commands(AGENTS["codex"], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        script = (
            tmp_path / ".agents" / "skills" / "epic-planning"
            / "scripts" / "analyze-dag.py"
        )
        assert script.exists()

    @pytest.mark.parametrize("agent", ["qwen", "codex", "cursor"])
    def test_ported_resources_are_translated(self, tmp_path: Path, agent: str) -> None:
        install_commands(AGENTS[agent], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        root = tmp_path / AGENTS[agent].commands_root
        blob = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.rglob("*")
            if path.is_file()
        ).lower()

        assert ".claude/skills/" not in blob
        assert ".codex/skills/" not in blob
        assert ".agents/skills/" not in blob if agent == "qwen" else True
        assert AGENTS[agent].commands_root in blob
        for term in ("opus", "sonnet", "haiku", "claude code", "anthropic"):
            assert term not in blob, f"{term!r} leaked into {agent} resources"


class TestTranslateBody:
    def test_qwen_model_tiers(self) -> None:
        out = translate_body("qwen", "Opus workers and Sonnet QA, Haiku triage")
        assert "qwen3-coder-plus workers" in out
        assert "qwen3-coder-flash triage" in out
        assert "Opus" not in out and "Sonnet" not in out and "Haiku" not in out

    def test_codex_model_tiers(self) -> None:
        out = translate_body("codex", "Spawn Opus, fall back to Haiku")
        assert "gpt-5.5" in out
        assert "gpt-5.4-mini" in out

    def test_cursor_model_tiers(self) -> None:
        out = translate_body("cursor", "Spawn Opus, fall back to Haiku")
        assert "composer-1" in out
        assert "cursor-small" in out

    def test_lowercase_model_names_translated(self) -> None:
        # ASCII diagrams use "Model: opus"
        assert "qwen3-coder-plus" in translate_body("qwen", "Model: opus")

    def test_product_name_and_task_tool(self) -> None:
        out = translate_body("qwen", "Claude Code uses one Task tool per task")
        assert "Qwen Code" in out
        assert "Claude" not in out
        assert "one SubAgent per task" in out

    def test_claude_code_not_pre_empted_by_claude(self) -> None:
        # The multi-word rule must win over the standalone Claude rule.
        assert translate_body("codex", "Claude Code") == "Codex"

    def test_anthropic_vendor(self) -> None:
        assert "OpenAI" in translate_body("codex", "Anthropic best practices")
        assert "Qwen" in translate_body("qwen", "Anthropic best practices")

    def test_claude_agent_is_noop(self) -> None:
        text = "Opus workers and the Task tool"
        assert translate_body("claude", text) == text


class TestRolesSection:
    def test_qwen_roles_section(self) -> None:
        out = roles_section(AGENTS["qwen"])
        assert "qwen3-coder-plus" in out
        assert "qwen3-coder-flash" in out
        assert "SubAgents" in out

    def test_codex_roles_section(self) -> None:
        out = roles_section(AGENTS["codex"])
        assert "gpt-5.5" in out
        assert "gpt-5.4-mini" in out
        assert "codex exec" in out

    def test_cursor_roles_section(self) -> None:
        out = roles_section(AGENTS["cursor"])
        assert "composer-1" in out
        assert "cursor-small" in out
        assert "cursor-agent" in out

    def test_claude_has_no_roles_section(self) -> None:
        assert roles_section(AGENTS["claude"]) == ""


class TestPortedCommandsHaveNoClaudeTerms:
    """End-to-end: ported command files must not leak Claude model/product names."""

    @pytest.mark.parametrize("agent", ["qwen", "codex", "cursor"])
    def test_no_claude_terms_leak(self, tmp_path: Path, agent: str) -> None:
        install_commands(AGENTS[agent], _BUNDLED_SKILLS_DIR, CORE_SKILLS, tmp_path)
        root = tmp_path / AGENTS[agent].commands_root
        files = {
            "qwen": lambda: list(root.glob("*.toml")),
            "codex": lambda: list(root.glob("*/SKILL.md")),
            "cursor": lambda: list(root.glob("*.md")),
        }[agent]()
        blob = "\n".join(
            f.read_text() for f in files
        ).lower()
        for term in ("opus", "sonnet", "haiku", "claude code", "anthropic"):
            assert term not in blob, f"{term!r} leaked into {agent} commands"
        # The agent's own models should be present.
        assert MODEL_ROLES[agent]["worker"] in blob


class TestAgentMcp:
    def test_qwen_settings_registers_spoq(self, tmp_path: Path) -> None:
        setup_agent_mcp(AGENTS["qwen"], tmp_path)
        data = json.loads((tmp_path / ".qwen" / "settings.json").read_text())
        assert data["mcpServers"]["spoq"]["command"] == "spoq"

    def test_qwen_merges_existing_settings(self, tmp_path: Path) -> None:
        settings = tmp_path / ".qwen" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"theme": "dark"}))
        setup_agent_mcp(AGENTS["qwen"], tmp_path)
        data = json.loads(settings.read_text())
        assert data["theme"] == "dark"
        assert "spoq" in data["mcpServers"]

    def test_codex_config_registers_spoq(self, tmp_path: Path) -> None:
        setup_agent_mcp(AGENTS["codex"], tmp_path)
        cfg = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text())
        assert cfg["mcp_servers"]["spoq"]["command"] == "spoq"

    def test_codex_appends_without_clobbering(self, tmp_path: Path) -> None:
        config = tmp_path / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('model = "gpt-5"\n')
        setup_agent_mcp(AGENTS["codex"], tmp_path)
        cfg = tomllib.loads(config.read_text())
        assert cfg["model"] == "gpt-5"
        assert cfg["mcp_servers"]["spoq"]["command"] == "spoq"

    def test_codex_idempotent(self, tmp_path: Path) -> None:
        setup_agent_mcp(AGENTS["codex"], tmp_path)
        msg = setup_agent_mcp(AGENTS["codex"], tmp_path)
        assert "skipped" in msg
        cfg = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text())
        # Exactly one spoq table.
        assert (tmp_path / ".codex" / "config.toml").read_text().count(
            "[mcp_servers.spoq]"
        ) == 1


    def test_cursor_mcp_registers_spoq(self, tmp_path: Path) -> None:
        setup_agent_mcp(AGENTS["cursor"], tmp_path)
        data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        assert data["mcpServers"]["spoq"]["command"] == "spoq"

    def test_cursor_merges_existing_mcp_json(self, tmp_path: Path) -> None:
        config = tmp_path / ".cursor" / "mcp.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        setup_agent_mcp(AGENTS["cursor"], tmp_path)
        data = json.loads(config.read_text())
        assert data["mcpServers"]["other"]["command"] == "x"
        assert data["mcpServers"]["spoq"]["command"] == "spoq"

    def test_cursor_idempotent(self, tmp_path: Path) -> None:
        setup_agent_mcp(AGENTS["cursor"], tmp_path)
        msg = setup_agent_mcp(AGENTS["cursor"], tmp_path)
        assert "skipped" in msg


class TestMultiAgentInit:
    def test_all_three_context_files(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="claude,qwen,codex")
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "QWEN.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert "$epic-planning" in (tmp_path / "AGENTS.md").read_text()

    def test_qwen_only_skips_claude_artifacts(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="qwen", with_mcp=True)
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / ".mcp.json").exists()
        assert (tmp_path / ".qwen" / "commands").is_dir()
        assert (tmp_path / ".qwen" / "settings.json").exists()

    def test_with_mcp_registers_each_selected_agent(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="claude,qwen,codex", with_mcp=True)
        assert (tmp_path / ".mcp.json").exists()
        assert (tmp_path / ".qwen" / "settings.json").exists()
        assert (tmp_path / ".codex" / "config.toml").exists()

    def test_claude_settings_only_when_claude_selected(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="codex")
        assert not (tmp_path / ".claude" / "settings.json").exists()

    def test_default_init_is_claude_only(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        assert (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / "QWEN.md").exists()
        assert not (tmp_path / "AGENTS.md").exists()

    def test_cursor_only_init(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="cursor", with_mcp=True)
        assert (tmp_path / "AGENTS.md").exists()
        assert "/epic-planning" in (tmp_path / "AGENTS.md").read_text()
        assert (tmp_path / ".cursor" / "commands").is_dir()
        assert (tmp_path / ".cursor" / "mcp.json").exists()
        assert not (tmp_path / ".claude").exists()

    def test_codex_and_cursor_share_agents_md(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="codex,cursor", with_mcp=True)
        # First selected agent (codex) writes AGENTS.md; cursor skips it but
        # still gets its own commands and MCP registration.
        assert "$epic-planning" in (tmp_path / "AGENTS.md").read_text()
        assert (tmp_path / ".agents" / "skills").is_dir()
        assert (tmp_path / ".cursor" / "commands").is_dir()
        assert (tmp_path / ".cursor" / "mcp.json").exists()

    def test_upgrade_adds_new_agent(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))  # claude only
        run_init(target=str(tmp_path), upgrade=True, agents="qwen")
        assert (tmp_path / "QWEN.md").exists()
        assert (tmp_path / ".qwen" / "commands").is_dir()


class TestClaudeOnlySkills:
    """workflow-execute targets the Claude-only dynamic-workflow runtime, so it
    must install for Claude but never port to Qwen/Codex."""

    def test_workflow_execute_is_claude_only(self) -> None:
        assert "workflow-execute" in CLAUDE_ONLY_SKILLS
        assert "workflow-execute" in CORE_SKILLS

    def test_installed_for_claude(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="claude")
        skill = tmp_path / ".claude" / "skills" / "workflow-execute" / "SKILL.md"
        assert skill.exists()
        # The compiler ships alongside it.
        assert (tmp_path / ".claude" / "skills" / "workflow-execute"
                / "scripts" / "compile-workflow.py").exists()

    def test_not_ported_to_qwen_or_codex(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path), agents="claude,qwen,codex")
        # Absent from the other agents' command dirs...
        assert not (tmp_path / ".qwen" / "commands" / "workflow-execute.toml").exists()
        assert not (
            tmp_path / ".agents" / "skills" / "workflow-execute" / "SKILL.md"
        ).exists()
        # ...while a normal skill IS ported (filtering is targeted, not blanket).
        assert (tmp_path / ".qwen" / "commands" / "agent-execution.toml").exists()
        assert (
            tmp_path / ".agents" / "skills" / "agent-execution" / "SKILL.md"
        ).exists()

    def test_filter_is_source_of_truth(self) -> None:
        # The non-Claude install site filters CLAUDE_ONLY_SKILLS out of CORE_SKILLS.
        portable = [s for s in CORE_SKILLS if s not in CLAUDE_ONLY_SKILLS]
        assert "workflow-execute" not in portable
        assert "agent-execution" in portable

    def test_upgrade_adds_workflow_execute(self, tmp_path: Path) -> None:
        # Simulate an older install that predates workflow-execute, then upgrade.
        run_init(target=str(tmp_path), agents="claude")
        wf = tmp_path / ".claude" / "skills" / "workflow-execute"
        shutil.rmtree(wf)
        assert not wf.exists()

        run_init(target=str(tmp_path), upgrade=True, agents="claude")

        assert (wf / "SKILL.md").exists()
        assert (wf / "scripts" / "compile-workflow.py").exists()


def _dircmp_diffs(prefix: str, a: Path, b: Path) -> list[str]:
    """Recursively diff two skill trees; return human-readable mismatch lines."""
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pyc"])
    out = [f"{prefix}: only in source: {f}" for f in cmp.left_only]
    out += [f"{prefix}: only in bundle: {f}" for f in cmp.right_only]
    _match, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    out += [f"{prefix}: differs: {f}" for f in mismatch]
    out += [f"{prefix}: error comparing: {f}" for f in errors]
    for sub in cmp.common_dirs:
        out += _dircmp_diffs(f"{prefix}/{sub}", a / sub, b / sub)
    return out


class TestInstalledSkillParity:
    """The package is the canonical skill source for this standalone repo."""

    def test_installed_skills_match_bundled_source(self, tmp_path) -> None:
        run_init(target=str(tmp_path), agents="claude")
        installed = tmp_path / ".claude/skills"
        mismatches = []
        for skill in CORE_SKILLS:
            mismatches.extend(_dircmp_diffs(skill, _BUNDLED_SKILLS_DIR / skill, installed / skill))
        assert not mismatches, "\n".join(mismatches)
