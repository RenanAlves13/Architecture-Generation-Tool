from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from server.pipeline import (
    build_architecture_prompt,
    discover_project_directories,
    parse_project_instance,
    run_batch_analysis,
)


def _load_project(project_name: str, project_type: str | None = None):
    matches = discover_project_directories(project_name=project_name, project_type=project_type)
    if not matches:
        raise RuntimeError(f"Project '{project_name}' was not found.")
    project_dir, resolved_project_type = matches[0]
    return parse_project_instance(project_dir, resolved_project_type)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="analyze_architecture_projects",
        title="Analyze Projects And Generate Architectures",
        description="Discovers project folders, builds prompts, optionally calls configured LLMs, validates against references, and persists the batch JSON report.",
    )
    def analyze_architecture_projects(
        output_path: str | None = None,
        include_llm_calls: bool = True,
        project_name: str | None = None,
        project_type: str | None = None,
    ) -> dict[str, Any]:
        return run_batch_analysis(
            output_path=output_path,
            include_llm_calls=include_llm_calls,
            project_name=project_name,
            project_type=project_type,
        )

    @mcp.tool(
        name="build_project_architecture_prompt",
        title="Build Project Architecture Prompt",
        description="Builds the deterministic JSON-only architecture-generation prompt for a single project instance.",
    )
    def build_project_architecture_prompt(
        project_name: str,
        project_type: str | None = None,
    ) -> dict[str, Any]:
        project = _load_project(project_name=project_name, project_type=project_type)
        return {
            "project_name": project.project_name,
            "project_type": project.project_type,
            "prompt": build_architecture_prompt(project),
        }
