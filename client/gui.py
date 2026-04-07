from __future__ import annotations

import json
import threading
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from client.analysis_client import AnalysisClient


class AnalysisDashboard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Architecture Analysis Dashboard")
        self.geometry("1360x860")

        self.client = AnalysisClient()
        self.results_payload: dict[str, Any] = {"generated_at": None, "results": [], "output_path": ""}
        self.project_index: dict[str, dict[str, Any]] = {}

        self.project_type_var = tk.StringVar(value="all")
        self.project_name_var = tk.StringVar()
        self.skip_llm_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Pronto.")
        self.generated_at_var = tk.StringVar(value="Sem resultados carregados.")

        self._build_layout()
        self.load_results()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        for column in range(8):
            controls.columnconfigure(column, weight=1 if column in {1, 3} else 0)

        ttk.Label(controls, text="Tipo").grid(row=0, column=0, sticky="w")
        project_type_combo = ttk.Combobox(
            controls,
            textvariable=self.project_type_var,
            values=("all", "student_project", "open_source"),
            state="readonly",
            width=18,
        )
        project_type_combo.grid(row=0, column=1, sticky="ew", padx=(6, 12))

        ttk.Label(controls, text="Projeto").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.project_name_var).grid(row=0, column=3, sticky="ew", padx=(6, 12))

        ttk.Checkbutton(
            controls,
            text="Pular chamadas LLM",
            variable=self.skip_llm_var,
        ).grid(row=0, column=4, sticky="w")

        ttk.Button(controls, text="Rodar análise", command=self.run_analysis).grid(row=0, column=5, padx=6)
        ttk.Button(controls, text="Recarregar JSON", command=self.load_results).grid(row=0, column=6, padx=6)
        ttk.Button(controls, text="Abrir JSON...", command=self.open_results_file).grid(row=0, column=7, padx=6)

        status_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.columnconfigure(1, weight=1)
        ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=1, sticky="w")
        ttk.Label(status_frame, textvariable=self.generated_at_var).grid(row=0, column=2, sticky="e")

        content = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        content.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        left_panel = ttk.Frame(content, padding=8)
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(2, weight=1)
        content.add(left_panel, weight=1)

        ttk.Label(left_panel, text="Resumo").grid(row=0, column=0, sticky="w")
        self.summary_text = ScrolledText(left_panel, height=10, wrap=tk.WORD)
        self.summary_text.grid(row=1, column=0, sticky="nsew", pady=(6, 12))
        self.summary_text.configure(state="disabled")

        ttk.Label(left_panel, text="Projetos").grid(row=2, column=0, sticky="nw")
        self.project_list = tk.Listbox(left_panel, exportselection=False)
        self.project_list.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.project_list.bind("<<ListboxSelect>>", self.on_project_selected)
        left_panel.rowconfigure(3, weight=1)

        right_panel = ttk.Frame(content, padding=8)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(1, weight=1)
        content.add(right_panel, weight=3)

        ttk.Label(right_panel, text="Métricas visuais").grid(row=0, column=0, sticky="w")
        self.chart_canvas = tk.Canvas(right_panel, height=150, background="white", highlightthickness=1, highlightbackground="#cccccc")
        self.chart_canvas.grid(row=1, column=0, sticky="ew", pady=(6, 12))

        notebook = ttk.Notebook(right_panel)
        notebook.grid(row=2, column=0, sticky="nsew")
        right_panel.rowconfigure(2, weight=1)

        self.overview_text = self._add_text_tab(notebook, "Visão geral")
        self.prompt_text = self._add_text_tab(notebook, "Prompt")
        self.responses_text = self._add_text_tab(notebook, "Respostas LLM")
        self.validation_text = self._add_text_tab(notebook, "Validação")

    def _add_text_tab(self, notebook: ttk.Notebook, title: str) -> ScrolledText:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        widget = ScrolledText(frame, wrap=tk.WORD)
        widget.grid(row=0, column=0, sticky="nsew")
        widget.configure(state="disabled")
        notebook.add(frame, text=title)
        return widget

    def run_analysis(self) -> None:
        project_type = self.project_type_var.get()
        project_name = self.project_name_var.get().strip() or None
        include_llm_calls = not self.skip_llm_var.get()

        self.status_var.set("Executando análise...")

        def worker() -> None:
            try:
                payload = self.client.run_analysis(
                    include_llm_calls=include_llm_calls,
                    project_name=project_name,
                    project_type=None if project_type == "all" else project_type,
                )
            except Exception as exc:
                self.after(0, lambda: self._handle_run_error(exc))
                return
            self.after(0, lambda: self._apply_results(payload, "Análise concluída."))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_run_error(self, exc: Exception) -> None:
        self.status_var.set("Falha ao executar a análise.")
        messagebox.showerror("Erro", str(exc))

    def load_results(self, path: Path | None = None) -> None:
        payload = self.client.load_results(path=path)
        self._apply_results(payload, "Resultados carregados.")

    def open_results_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Abrir resultados",
            filetypes=[("JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            self.load_results(Path(selected))

    def _apply_results(self, payload: dict[str, Any], status_message: str) -> None:
        self.results_payload = payload
        self.project_index = {}

        results = payload.get("results", [])
        self.generated_at_var.set(f"Geração: {payload.get('generated_at') or 'n/a'}")
        self.status_var.set(status_message)

        self.project_list.delete(0, tk.END)
        for item in results:
            label = f"{item['project_type']} :: {item['project_name']}"
            self.project_index[label] = item
            self.project_list.insert(tk.END, label)

        self._set_text(self.summary_text, self._build_summary_text(results, payload))
        self._draw_summary_chart(results)

        if results:
            self.project_list.selection_clear(0, tk.END)
            self.project_list.selection_set(0)
            self.project_list.event_generate("<<ListboxSelect>>")
        else:
            self._clear_detail_tabs()

    def _build_summary_text(self, results: list[dict[str, Any]], payload: dict[str, Any]) -> str:
        status_counts = Counter(item.get("status", "unknown") for item in results)
        type_counts = Counter(item.get("project_type", "unknown") for item in results)
        lines = [
            f"Arquivo: {payload.get('output_path', '')}",
            f"Projetos processados: {len(results)}",
            "",
            "Status:",
        ]
        for status, count in sorted(status_counts.items()):
            lines.append(f"- {status}: {count}")
        lines.append("")
        lines.append("Tipos:")
        for project_type, count in sorted(type_counts.items()):
            lines.append(f"- {project_type}: {count}")
        return "\n".join(lines)

    def _draw_summary_chart(self, results: list[dict[str, Any]]) -> None:
        self.chart_canvas.delete("all")
        status_counts = Counter(item.get("status", "unknown") for item in results)
        if not status_counts:
            self.chart_canvas.create_text(20, 20, text="Sem dados para exibir.", anchor="nw")
            return

        colors = {
            "success": "#2e8b57",
            "partial": "#d4a017",
            "failed": "#c0392b",
            "unknown": "#7f8c8d",
        }
        width = max(self.chart_canvas.winfo_width(), 500)
        max_value = max(status_counts.values()) or 1
        bar_width = 120
        spacing = 40
        start_x = 40
        baseline = 120

        for index, (status, count) in enumerate(sorted(status_counts.items())):
            x0 = start_x + index * (bar_width + spacing)
            x1 = x0 + bar_width
            height = int((count / max_value) * 80)
            y0 = baseline - height
            y1 = baseline
            self.chart_canvas.create_rectangle(x0, y0, x1, y1, fill=colors.get(status, "#7f8c8d"), outline="")
            self.chart_canvas.create_text((x0 + x1) / 2, y0 - 12, text=str(count))
            self.chart_canvas.create_text((x0 + x1) / 2, y1 + 14, text=status)
        self.chart_canvas.config(scrollregion=(0, 0, width, 150))

    def on_project_selected(self, event: tk.Event | None = None) -> None:
        selection = self.project_list.curselection()
        if not selection:
            self._clear_detail_tabs()
            return

        label = self.project_list.get(selection[0])
        project = self.project_index.get(label)
        if project is None:
            self._clear_detail_tabs()
            return

        self._set_text(self.overview_text, self._build_project_overview(project))
        self._set_text(self.prompt_text, self._build_prompt_text(project))
        self._set_text(self.responses_text, self._build_responses_text(project))
        self._set_text(self.validation_text, self._build_validation_text(project))

    def _build_project_overview(self, project: dict[str, Any]) -> str:
        input_summary = project.get("input_summary", {})
        analysis_profile = project.get("analysis_profile", {})
        errors = project.get("errors", [])
        lines = [
            f"Projeto: {project.get('project_name')}",
            f"Tipo: {project.get('project_type')}",
            f"Status: {project.get('status')}",
            f"Fonte do prompt: {analysis_profile.get('prompt_source', 'n/a')}",
            f"Base de validação: {analysis_profile.get('validation_target', 'n/a')}",
            "",
            "Entradas:",
            f"- input.txt encontrado: {input_summary.get('input_txt_found')}",
            f"- CSVs: {len(input_summary.get('csv_files_found', []))}",
            f"- DataMetrics.json encontrado: {input_summary.get('reference_json_found')}",
            f"- user stories: {input_summary.get('user_story_count', 0)}",
            f"- endpoints: {input_summary.get('endpoint_count', 0)}",
        ]
        if errors:
            lines.append("")
            lines.append("Erros:")
            lines.extend(f"- {error}" for error in errors)
        return "\n".join(lines)

    def _build_prompt_text(self, project: dict[str, Any]) -> str:
        prompts = project.get("llm_request", {}).get("model_prompts", {})
        return "\n\n".join(
            [
                "Prompt OpenAI:",
                prompts.get("openai", ""),
                "",
                "Prompt DeepSeek:",
                prompts.get("deepseek", ""),
            ]
        ).strip()

    def _build_responses_text(self, project: dict[str, Any]) -> str:
        responses = project.get("llm_responses", {})
        return "\n\n".join(
            [
                "OpenAI:",
                json.dumps(responses.get("openai", {}), indent=2, ensure_ascii=False),
                "",
                "DeepSeek:",
                json.dumps(responses.get("deepseek", {}), indent=2, ensure_ascii=False),
            ]
        ).strip()

    def _build_validation_text(self, project: dict[str, Any]) -> str:
        validation = project.get("validation", {})
        return json.dumps(validation, indent=2, ensure_ascii=False)

    def _clear_detail_tabs(self) -> None:
        for widget in (self.overview_text, self.prompt_text, self.responses_text, self.validation_text):
            self._set_text(widget, "")

    @staticmethod
    def _set_text(widget: ScrolledText, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")


def launch_dashboard() -> None:
    app = AnalysisDashboard()
    app.mainloop()


if __name__ == "__main__":
    launch_dashboard()
