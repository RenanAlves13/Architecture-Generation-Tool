from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from server.pipeline import build_architecture_prompt, discover_project_directories, parse_project_instance


BASE_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_FILE = BASE_DIR / "dataspace" / "few-shot-examples" / "example.txt"


def _load_project_prompt(project_name: str, project_type: str | None = None) -> str:
    matches = discover_project_directories(project_name=project_name, project_type=project_type)
    if not matches:
        raise RuntimeError(f"Project '{project_name}' was not found.")
    project_dir, resolved_project_type = matches[0]
    project = parse_project_instance(project_dir, resolved_project_type)
    return build_architecture_prompt(project)


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="project_architecture_prompt",
        title="Project Architecture Prompt",
        description="Builds the deterministic architecture-generation prompt for a project instance.",
    )
    def project_architecture_prompt(
        project_name: str,
        project_type: str | None = None,
    ) -> str:
        return _load_project_prompt(project_name=project_name, project_type=project_type)

    @mcp.prompt(
        name="zero_shot_prompt",
        title="Zero Shot Prompting Style",
        description="Alias for the deterministic JSON-only architecture-generation prompt.",
    )
    def zero_shot_prompt(
        project_name: str,
        project_type: str | None = None,
    ) -> str:
        return _load_project_prompt(project_name=project_name, project_type=project_type)

    @mcp.prompt(
        name="Few_Shot_prompt",
        title="Few Shot Prompting Style",
        description="Returns the architecture-generation prompt plus the repository few-shot example for optional style guidance.",
    )
    def few_shot_prompt(
        project_name: str,
        project_type: str | None = None,
    ) -> str:
        base_prompt = _load_project_prompt(project_name=project_name, project_type=project_type)
        example_text = ""
        if EXAMPLE_FILE.exists():
            example_text = EXAMPLE_FILE.read_text(encoding="utf-8").strip()
        if not example_text:
            return base_prompt
        return "\n\n".join(
            [
                base_prompt,
                "Few-shot reference example for style only:",
                example_text,
            ]
        )
