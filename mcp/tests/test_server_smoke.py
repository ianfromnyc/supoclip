"""Import-level smoke tests for the MCP server.

The server is a long-running process with no unit-testable entry point, so a
bad import only showed up as a container restart loop. These tests import the
module and inspect the registered tools, which makes an incompatible ``mcp``
release fail in CI instead.
"""

from __future__ import annotations


def test_server_module_imports() -> None:
    """The console-script entry point must be importable."""
    from supoclip_mcp.server import main

    assert callable(main)


def test_server_reports_its_version() -> None:
    """Clients read the version at initialize, so it must not be blank."""
    from supoclip_mcp.server import mcp

    assert mcp.version


async def test_expected_tools_are_registered() -> None:
    """Every documented tool must reach the wire, not only the source file."""
    from supoclip_mcp.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}

    assert {
        "supoclip_health",
        "supoclip_list_caption_templates",
        "supoclip_list_fonts",
        "supoclip_broll_status",
        "supoclip_create_clip_task",
        "supoclip_list_tasks",
        "supoclip_get_task",
        "supoclip_wait_for_task",
        "supoclip_list_clips",
        "supoclip_download_clip",
        "supoclip_export_clip",
        "supoclip_cancel_task",
        "supoclip_resume_task",
        "supoclip_delete_task",
    } <= names


async def test_context_parameter_is_not_a_tool_argument() -> None:
    """``ctx`` is injected by the server, so no client may be asked for it.

    The parameter is only recognised when it carries the Context class the tool
    layer looks for. A near-miss import made schema generation fail instead.
    """
    from supoclip_mcp.server import mcp

    tool = next(t for t in await mcp.list_tools() if t.name == "supoclip_wait_for_task")

    assert "ctx" not in tool.input_schema.get("properties", {})
