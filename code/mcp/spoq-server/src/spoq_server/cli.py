"""SPOQ CLI: SQLite-native commands by default, explicit legacy compatibility.

The v1 dispatcher owns planning, migration, collaboration, search, and JSON
snapshots. This module retains initialization/MCP launch and the pre-1.0
filesystem commands selected with SPOQ_STORE=fs or --legacy.
"""

import argparse
import os
import sys

from spoq_server import __version__


def main():
    """Main CLI entry point."""
    from spoq_server.v1.cli import dispatch
    if dispatch(sys.argv[1:]):
        return
    parser = argparse.ArgumentParser(
        prog="spoq",
        description="SPOQ: Specialist Orchestrated Queuing for multi-agent AI development",
    )
    parser.add_argument(
        "--version", action="version", version=f"spoq {__version__}"
    )
    parser.add_argument('--legacy', action='store_true', help='Use the pre-1.0 filesystem commands')

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- spoq mcp ---
    mcp_parser = subparsers.add_parser(
        "mcp", help="Run the SPOQ MCP server (stdio transport)"
    )
    mcp_parser.add_argument(
        "--transport", default="stdio", choices=["stdio"],
        help="Transport protocol (default: stdio)",
    )
    mcp_parser.add_argument(
        "--root", default=None,
        help="Pin the SPOQ project root to this path, regardless of launch "
             "CWD. Overrides the SPOQ_PROJECT_ROOT environment variable.",
    )

    # --- spoq init ---
    init_parser = subparsers.add_parser(
        "init", help="Bootstrap SPOQ in a project directory"
    )
    init_parser.add_argument(
        "--target", default=".", help="Target directory (default: current directory)"
    )
    init_parser.add_argument(
        "--full", action="store_true",
        help="Include an example Project Plan, Feature, and Task",
    )
    init_parser.add_argument(
        "--with-mcp", action="store_true",
        help="Configure .mcp.json to use the SPOQ MCP server",
    )
    init_parser.add_argument(
        "--upgrade", action="store_true",
        help="Upgrade existing clients and prompt to convert legacy work",
    )
    init_parser.add_argument(
        "--agents", default=None,
        help="Comma-separated coding agents to scaffold for "
             "(claude, qwen, codex, cursor). Default: claude",
    )
    init_parser.add_argument('--yes', action='store_true', help='Confirm reviewed legacy conversion')

    # --- spoq template ---
    template_parser = subparsers.add_parser(
        "template", help="Generate epic or map skeletons"
    )
    template_sub = template_parser.add_subparsers(
        dest="template_type", help="Template type"
    )

    # spoq template epic <name> <task_count>
    epic_tmpl = template_sub.add_parser("epic", help="Generate an epic skeleton")
    epic_tmpl.add_argument("name", help="Epic name (converted to slug)")
    epic_tmpl.add_argument(
        "task_count", type=int, help="Number of task files (minimum 3)"
    )
    epic_tmpl.add_argument(
        "--path", default="", help="Base path (default: spoq/epics/active/)"
    )

    # spoq template map <name> <epic_count>
    map_tmpl = template_sub.add_parser("map", help="Generate a map skeleton")
    map_tmpl.add_argument("name", help="Map name (converted to slug)")
    map_tmpl.add_argument(
        "epic_count", type=int, help="Number of epic entries (minimum 2)"
    )
    map_tmpl.add_argument(
        "--path", default="", help="Base path (default: spoq/maps/active/)"
    )

    # --- spoq export ---
    export_parser = subparsers.add_parser(
        "export", help="Snapshot the SPOQ store into an on-disk YAML tree"
    )
    export_group = export_parser.add_mutually_exclusive_group()
    export_group.add_argument(
        "--epic", metavar="SLUG", default=None, help="Export a single epic by slug"
    )
    export_group.add_argument(
        "--all", action="store_true", dest="export_all",
        help="Export every epic and map in the store",
    )
    export_parser.add_argument(
        "--out", default="./spoq-export/", metavar="DIR",
        help="Output directory (must resolve OUTSIDE the frozen spoq/ tree)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "mcp":
        _cmd_mcp(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "template":
        _cmd_template(args)
    elif args.command == "export":
        _cmd_export(args)


def _cmd_export(args):
    """Snapshot the store into an on-disk YAML tree."""
    from spoq_server.export_cli import run_export
    sys.exit(run_export(epic=args.epic, export_all=args.export_all, out=args.out))


def _cmd_mcp(args):
    """Run the MCP server."""
    if not getattr(args, 'legacy', False) and os.environ.get('SPOQ_STORE','sqlite').strip().lower() not in {'fs'}:
        from spoq_server.v1.server import main as sqlite_main
        sqlite_main(getattr(args, 'root', None))
        return
    from spoq_server import server
    if getattr(args, "root", None):
        server.set_project_root_override(args.root)
    server.main()


def _cmd_init(args):
    """Bootstrap SPOQ in a project directory."""
    if not getattr(args, 'legacy', False) and os.environ.get('SPOQ_STORE','sqlite').strip().lower() not in {'fs'}:
        import json
        from spoq_server.v1.cli import init
        try:
            print(json.dumps(init(args.target, upgrade=args.upgrade, yes=getattr(args,'yes',False),
                                  layout=getattr(args,'layout','layer'), agents=args.agents,
                                  with_mcp=args.with_mcp, full=args.full)))
        except (ValueError, OSError) as exc:
            print(f'Error: {exc}', file=sys.stderr)
            raise SystemExit(1) from exc
        return
    from spoq_server.init_cmd import run_init
    try:
        run_init(
            target=args.target,
            full=args.full,
            with_mcp=args.with_mcp,
            upgrade=args.upgrade,
            agents=args.agents,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_template(args):
    """Generate a template."""
    import json

    if args.template_type is None:
        print("Usage: spoq template {epic,map} <name> <count>")
        sys.exit(1)

    if args.template_type == "epic":
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton(
            name=args.name,
            task_count=args.task_count,
            path=args.path,
        ))
    elif args.template_type == "map":
        from spoq_server.map_tools import spoq_generate_map_skeleton
        result = json.loads(spoq_generate_map_skeleton(
            name=args.name,
            epic_count=args.epic_count,
            path=args.path,
        ))
    else:
        print(f"Unknown template type: {args.template_type}")
        sys.exit(1)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    path_key = "epic_path" if args.template_type == "epic" else "map_path"
    print(f"Created {args.template_type} at: {result[path_key]}")
    if "wave_distribution" in result:
        dist = result["wave_distribution"]
        print(f"  Wave 0: {dist.get('wave_0', 0)}, Wave 1: {dist.get('wave_1', 0)}, Later: {dist.get('later', 0)}")


if __name__ == "__main__":
    main()


def mcp_main():
    """Dedicated console entry point with the same backend/root handling as spoq mcp."""
    sys.argv=[sys.argv[0],'mcp',*sys.argv[1:]]
    main()
