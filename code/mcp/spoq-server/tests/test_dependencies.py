"""Regression coverage for the MCP SDK compatibility boundary."""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_mcp_dependency_supports_v1_and_excludes_v2():
    """Installers must retain the SDK's mcp.server.fastmcp API."""
    manifest = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    requirement = next(
        Requirement(value)
        for value in manifest["project"]["dependencies"]
        if Requirement(value).name == "mcp"
    )
    assert "1.26.0" in requirement.specifier
    assert "1.28.1" in requirement.specifier
    assert "2.0.0" not in requirement.specifier
    assert "2.1.0" not in requirement.specifier
    assert "1.0.0" not in requirement.specifier
    assert "1.25.0" not in requirement.specifier


def test_lockfile_preserves_mcp_compatibility_boundary():
    """uv and published package installs must enforce the same SDK range."""
    manifest = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((PACKAGE_ROOT / "uv.lock").read_text())
    requirement = next(
        Requirement(value)
        for value in manifest["project"]["dependencies"]
        if Requirement(value).name == "mcp"
    )
    package = next(item for item in lock["package"] if item["name"] == "spoq")
    locked_requirement = next(
        item for item in package["metadata"]["requires-dist"]
        if item["name"] == "mcp"
    )
    assert Requirement("mcp" + locked_requirement["specifier"]) == requirement
    sdk = next(item for item in lock["package"] if item["name"] == "mcp")
    assert sdk["version"] in requirement.specifier


@pytest.mark.anyio
async def test_cli_mcp_stdio_connection(tmp_path):
    """A real CLI process must initialize, list tools, and answer a health check."""
    import json
    import os
    import sys
    from datetime import timedelta

    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "spoq_server", "mcp", "--root", str(tmp_path)],
        env={
            **os.environ,
            "SPOQ_STORE": "fs",
            # Fail the optional update lookup locally; this test needs no network.
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
        },
    )
    with anyio.fail_after(20):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(
                reader, writer, read_timeout_seconds=timedelta(seconds=10)
            ) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "spoq"
                tools = await session.list_tools()
                assert "spoq_ping" in {tool.name for tool in tools.tools}
                ping = await session.call_tool("spoq_ping", {})
                assert not ping.isError
                payload = json.loads(ping.content[0].text)
                assert payload["status"] == "ok"
                assert payload["project_root"] == str(tmp_path)
                maps = await session.call_tool(
                    "spoq_list_maps", {"base_path": str(tmp_path / "spoq" / "maps")}
                )
                assert not maps.isError
                listing = json.loads(maps.content[0].text)
                assert "error" not in listing
                for tier in ("backlog", "active", "complete"):
                    assert listing[tier] == []
