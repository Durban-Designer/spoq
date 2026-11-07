"""Verify generated MCP registrations without using the developer's config."""
import json
import tomllib

import pytest

from spoq_server.v1.cli import init
from spoq_server.v1.config import CONFIG_PATHS


@pytest.mark.parametrize('agent', ['claude', 'codex', 'cursor', 'qwen'])
def test_native_mcp_registration_pins_generated_project(tmp_path, agent):
    project = tmp_path / 'project with spaces'
    init(project, agents=agent, with_mcp=True)
    path = project / CONFIG_PATHS[agent]
    if agent == 'codex':
        servers = tomllib.loads(path.read_text())['mcp_servers']
    else:
        servers = json.loads(path.read_text())['mcpServers']
    entry = servers['spoq']
    assert entry['command'] == 'spoq'
    assert entry['args'] == ['mcp', '--root', str(project.resolve())]
    assert entry['env']['SPOQ_STORE'] == 'sqlite'
    assert (project / '.spoq/spoq.db').is_file()
