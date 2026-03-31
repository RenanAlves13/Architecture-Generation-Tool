from __future__ import annotations
from pathlib import Path
from fastmcp import FastMCP


BASE_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_FILE = BASE_DIR / "dataspace" / "few-shot-examples" / "example.txt"


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "dataspace://few-shot-examples",
        name="few_shot_examples",
        title="Few-shot Example",
        description="Retorna um exemplo simples salvo em arquivo TXT.",
        mime_type="text/plain",
    )
    def few_examples() -> str:
        try:
            return EXAMPLE_FILE.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Erro ao carregar o arquivo de exemplo: {EXAMPLE_FILE}"
            ) from exc
