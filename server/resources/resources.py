from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from server.pipeline import DEFAULT_RESULTS_PATH


BASE_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_FILE = BASE_DIR / "dataspace" / "few-shot-examples" / "example.txt"


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "dataspace://few-shot-examples",
        name="few_shot_examples",
        title="Few-shot Example",
        description="Returns the repository few-shot example text.",
        mime_type="text/plain",
    )
    def few_examples() -> str:
        try:
            return EXAMPLE_FILE.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load the example file: {EXAMPLE_FILE}"
            ) from exc

    @mcp.resource(
        "dataspace://architecture-analysis-results",
        name="architecture_analysis_results",
        title="Architecture Analysis Results",
        description="Returns the latest persisted batch architecture analysis results.",
        mime_type="application/json",
    )
    def latest_results() -> str:
        if not DEFAULT_RESULTS_PATH.exists():
            return "{}"
        try:
            return DEFAULT_RESULTS_PATH.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load the results file: {DEFAULT_RESULTS_PATH}"
            ) from exc
