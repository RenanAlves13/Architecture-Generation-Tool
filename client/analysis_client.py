from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.pipeline import DEFAULT_RESULTS_PATH, run_batch_analysis


class AnalysisClient:
    def __init__(self, default_output_path: Path | None = None) -> None:
        self.default_output_path = default_output_path or DEFAULT_RESULTS_PATH

    def run_analysis(
        self,
        include_llm_calls: bool = True,
        project_name: str | None = None,
        project_type: str | None = None,
        output_path: Path | None = None,
    ) -> dict[str, Any]:
        return run_batch_analysis(
            output_path=str(output_path or self.default_output_path),
            include_llm_calls=include_llm_calls,
            project_name=project_name,
            project_type=project_type,
        )

    def load_results(self, path: Path | None = None) -> dict[str, Any]:
        target = path or self.default_output_path
        if not target.exists():
            return {"generated_at": None, "results": [], "output_path": str(target)}
        return json.loads(target.read_text(encoding="utf-8"))
