from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from fastmcp import FastMCP


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MARKDOWN_PATH = BASE_DIR / "dataspace" / "systems" / "reference-architecture.md"


def _read_markdown_file(markdown_path: str | None) -> tuple[Path, str]:
    file_path = Path(markdown_path) if markdown_path else DEFAULT_MARKDOWN_PATH

    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(
            f"Erro ao carregar o arquivo markdown: {file_path}"
        ) from exc

    return file_path, content


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="reference_architecture",
        title="Generating reference architecture",
        description="Le um arquivo markdown e retorna a referencia do grafico da arquitetura.",
    )
    def graph_reference_archic(markdown_path: str | None = None) -> dict[str, Any]:
        file_path, markdown_content = _read_markdown_file(markdown_path)

        response = "image"
        return response
