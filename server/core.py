from __future__ import annotations

import argparse
import json
from collections import Counter

from fastmcp import FastMCP

from server.pipeline import run_batch_analysis
from server.prompt.prompts import register_prompts
from server.resources.resources import register_resources
from server.tools.tools import register_tools


def create_mcp_server() -> FastMCP:
    mcp = FastMCP("architecture-generation-tool")
    register_resources(mcp)
    register_prompts(mcp)
    register_tools(mcp)
    return mcp


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Architecture generation MCP server and batch runner.")
    subparsers = parser.add_subparsers(dest="command")

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Run the full project discovery and architecture generation batch pipeline.",
    )
    analyze_parser.add_argument("--output", dest="output_path", default=None)
    analyze_parser.add_argument("--project-name", default=None)
    analyze_parser.add_argument(
        "--project-type",
        choices=["open_source", "student_project"],
        default=None,
    )
    analyze_parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Build prompts and validations without calling external LLM providers.",
    )

    subparsers.add_parser("dashboard", help="Open the local Python dashboard for the analysis results.")
    subparsers.add_parser("serve", help="Run the FastMCP server.")
    return parser


def main() -> None:
    parser = _build_argument_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        payload = run_batch_analysis(
            output_path=args.output_path,
            include_llm_calls=not args.skip_llm,
            project_name=args.project_name,
            project_type=args.project_type,
        )
        status_counts = Counter(result["status"] for result in payload["results"])
        summary = {
            "output_path": payload["output_path"],
            "project_count": len(payload["results"]),
            "status_counts": dict(status_counts),
        }
        print(json.dumps(summary, indent=2))
        return

    if args.command == "dashboard":
        from client.gui import launch_dashboard

        launch_dashboard()
        return

    create_mcp_server().run()


if __name__ == "__main__":
    main()
