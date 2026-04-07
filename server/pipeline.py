from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASPACE_ROOT = REPO_ROOT / "dataspace" / "systems"
OPEN_SOURCE_ROOT = DATASPACE_ROOT / "open_source_projects"
STUDENT_PROJECT_ROOT = DATASPACE_ROOT / "student_projects"
DEFAULT_RESULTS_PATH = REPO_ROOT / "dataspace" / "results" / "architecture_generation_results.json"
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 120
HTTP_METHODS = {
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
}
OUTPUT_SCHEMA_TEMPLATE = {
    "system_name": "string",
    "microservices": [
        {
            "name": "string",
            "responsibilities": ["string"],
            "covered_user_stories": ["string"],
            "main_endpoints": ["string"],
            "data_owned": ["string"],
            "dependencies": ["string"],
        }
    ],
    "communications": [
        {
            "source": "string",
            "target": "string",
            "type": "sync|async|event|unknown",
            "description": "string",
            "related_user_stories": ["string"],
        }
    ],
    "unassigned_user_stories": ["string"],
    "notes": ["string"],
}
GENERIC_SERVICE_HINTS = {
    "microservicessandbox",
    "opencensusmicroservicesdemo",
    "teastore",
    "sockshop",
    "trainticket",
    "serviceboutique",
    "rideshare",
}
INFRASTRUCTURE_SERVICE_HINTS = {
    "alertmanager",
    "binsh",
    "config",
    "discovery",
    "eureka",
    "grafana",
    "jaeger",
    "kubernetes",
    "loadgenerator",
    "loadtest",
    "logserver",
    "mongo",
    "mysql",
    "mysqlserver",
    "nats",
    "nodeexporter",
    "prometheus",
    "rabbitmq",
    "tinytools",
}
IGNORED_DOTTED_PATH_PARTS = {
    "com",
    "controller",
    "descartes",
    "java",
    "main",
    "org",
    "rest",
    "src",
    "tools",
    "util",
}
IGNORED_PATH_PREFIXES = (
    "/bin/",
    "/dev/",
    "/etc/",
    "/host",
    "/mnt/",
    "/opt/",
    "/tmp",
    "/usr/",
    "/var/",
    "http://",
    "https://",
)


@dataclass(frozen=True)
class UserStory:
    index: int
    text: str

    @property
    def labeled_text(self) -> str:
        return f"{self.index}) {self.text}"


@dataclass(frozen=True)
class EndpointRecord:
    path: str
    method: str | None = None
    service_hint: str | None = None
    source_file: str | None = None
    evidence_file: str | None = None

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "method": self.method or "UNKNOWN",
            "path": self.path,
            "service_hint": self.service_hint or "unknown",
            "source_file": self.evidence_file or self.source_file or "unknown",
        }


@dataclass(frozen=True)
class ReferenceService:
    set_id: int
    set_name: str
    user_story_ids: list[int]
    linked_service_ids: list[int]
    has_database: bool


@dataclass
class ProjectInstance:
    project_name: str
    project_type: str
    project_dir: Path
    input_path: Path | None
    csv_paths: list[Path]
    reference_path: Path | None
    system_description: str | None
    user_stories: list[UserStory]
    endpoints: list[EndpointRecord]
    reference_architecture: list[ReferenceService] | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    model: str
    endpoint_url: str
    api_style: str


def load_env_file(env_path: Path | None = None) -> None:
    target_path = env_path or (REPO_ROOT / ".env")
    if not target_path.exists():
        return

    for line in target_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def _is_reference_filename(file_name: str) -> bool:
    normalized = _normalize_filename(file_name)
    return normalized in {"datametricsjson", "contendinacaojson"}


def _canonical_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _clean_text(value: Any) -> str:
    return str(value).strip()


def discover_project_directories(
    project_name: str | None = None,
    project_type: str | None = None,
) -> list[tuple[Path, str]]:
    roots = [
        (OPEN_SOURCE_ROOT, "open_source"),
        (STUDENT_PROJECT_ROOT, "student_project"),
    ]
    results: list[tuple[Path, str]] = []

    for root, root_project_type in roots:
        if project_type and project_type != root_project_type:
            continue
        if not root.exists():
            continue
        for child in sorted(path for path in root.iterdir() if path.is_dir()):
            if project_name and child.name.lower() != project_name.lower():
                continue
            artifact_paths = _collect_artifact_paths(child)
            if artifact_paths["input_paths"] or artifact_paths["csv_paths"] or artifact_paths["reference_paths"]:
                results.append((child, root_project_type))

    return results


def _collect_artifact_paths(project_dir: Path) -> dict[str, list[Path]]:
    input_paths = sorted(project_dir.rglob("input.txt"))
    csv_paths = sorted(project_dir.rglob("*.csv"))
    reference_paths = sorted(
        path
        for path in project_dir.rglob("*.json")
        if _is_reference_filename(path.name)
    )
    return {
        "input_paths": input_paths,
        "csv_paths": csv_paths,
        "reference_paths": reference_paths,
    }


def _choose_preferred_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return sorted(paths, key=lambda path: (len(path.parts), _relative_path(path)))[0]


def parse_project_instance(project_dir: Path, project_type: str) -> ProjectInstance:
    artifact_paths = _collect_artifact_paths(project_dir)
    errors: list[str] = []

    input_path = _choose_preferred_path(artifact_paths["input_paths"])
    if len(artifact_paths["input_paths"]) > 1 and input_path is not None:
        errors.append(
            f"Multiple input.txt files found; using {_relative_path(input_path)}."
        )

    reference_path = _choose_preferred_path(artifact_paths["reference_paths"])
    if len(artifact_paths["reference_paths"]) > 1 and reference_path is not None:
        errors.append(
            f"Multiple reference JSON files found; using {_relative_path(reference_path)}."
        )

    system_description: str | None = None
    user_stories: list[UserStory] = []
    if input_path:
        try:
            system_description, user_stories = parse_input_file(input_path)
        except Exception as exc:  # pragma: no cover
            errors.append(f"Failed to parse {_relative_path(input_path)}: {exc}")
    else:
        errors.append("input.txt not found.")

    endpoints = parse_endpoint_files(artifact_paths["csv_paths"], errors)
    if project_type == "open_source" and not artifact_paths["csv_paths"]:
        errors.append("No CSV evidence files were found for this open-source project.")

    reference_architecture: list[ReferenceService] | None = None
    if reference_path:
        try:
            reference_architecture = parse_reference_architecture(reference_path)
        except Exception as exc:  # pragma: no cover
            errors.append(f"Failed to parse {_relative_path(reference_path)}: {exc}")
    elif project_type == "student_project":
        errors.append("DataMetrics.json not found for this student project.")

    return ProjectInstance(
        project_name=project_dir.name,
        project_type=project_type,
        project_dir=project_dir,
        input_path=input_path,
        csv_paths=artifact_paths["csv_paths"],
        reference_path=reference_path,
        system_description=system_description,
        user_stories=user_stories,
        endpoints=endpoints,
        reference_architecture=reference_architecture,
        errors=errors,
    )


def parse_input_file(input_path: Path) -> tuple[str | None, list[UserStory]]:
    content = input_path.read_text(encoding="utf-8", errors="replace")
    sections = _parse_markdown_sections(content)

    description = sections.get("system description")
    user_stories_section = sections.get("user stories")

    if description is not None:
        description = description.strip() or None

    user_stories = parse_user_stories(user_stories_section or "")
    return description, user_stories


def _parse_markdown_sections(content: str) -> dict[str, str]:
    section_pattern = re.compile(r"(?im)^#\s*([A-Z0-9 _-]+):\s*$")
    matches = list(section_pattern.finditer(content))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        name = match.group(1).strip().lower()
        sections[name] = content[start:end].strip()
    return sections


def parse_user_stories(section: str) -> list[UserStory]:
    start_pattern = re.compile(r"^\s*(?:(\d+)[.)]|[-*])\s+(.*\S.*)\s*$")
    stories: list[UserStory] = []
    current_index: int | None = None
    current_parts: list[str] = []
    next_auto_index = 1

    def flush_current() -> None:
        nonlocal current_index
        if current_index is None or not current_parts:
            return
        text = " ".join(part.strip() for part in current_parts if part.strip()).strip()
        if text:
            stories.append(UserStory(index=current_index, text=text))
        current_index = None
        current_parts.clear()

    for line in section.replace("\r\n", "\n").splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        match = start_pattern.match(line)
        if match:
            flush_current()
            if match.group(1):
                current_index = int(match.group(1))
                next_auto_index = max(next_auto_index, current_index + 1)
            else:
                current_index = next_auto_index
                next_auto_index += 1
            current_parts.append(match.group(2).strip())
            continue

        if current_index is not None:
            current_parts.append(stripped)

    flush_current()
    return stories


def parse_reference_architecture(reference_path: Path) -> list[ReferenceService]:
    raw_content = json.loads(reference_path.read_text(encoding="utf-8"))
    if isinstance(raw_content, dict):
        entries = raw_content.get("services", [])
    else:
        entries = raw_content

    services: list[ReferenceService] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        set_id = int(entry.get("set_id", len(services) + 1))
        set_name = _clean_text(entry.get("set_name", f"service-{set_id}"))
        user_story_ids = [
            int(story_id)
            for story_id in entry.get("user_stories", [])
            if str(story_id).strip()
        ]
        linked_service_ids = [
            int(link_id)
            for link_id in entry.get("links", [])
            if str(link_id).strip()
        ]
        has_database = str(entry.get("db", "false")).strip().lower() == "true"
        services.append(
            ReferenceService(
                set_id=set_id,
                set_name=set_name,
                user_story_ids=user_story_ids,
                linked_service_ids=linked_service_ids,
                has_database=has_database,
            )
        )

    return services


def parse_endpoint_files(csv_paths: list[Path], errors: list[str] | None = None) -> list[EndpointRecord]:
    seen: set[tuple[str, str, str]] = set()
    endpoints: list[EndpointRecord] = []

    for csv_path in csv_paths:
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    endpoint = _normalize_endpoint_row(row, csv_path)
                    if endpoint is None:
                        continue
                    dedupe_key = (
                        endpoint.method or "",
                        endpoint.path,
                        endpoint.service_hint or "",
                    )
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    endpoints.append(endpoint)
        except Exception as exc:  # pragma: no cover
            if errors is not None:
                errors.append(f"Failed to parse {_relative_path(csv_path)}: {exc}")

    endpoints.sort(
        key=lambda endpoint: (
            endpoint.path,
            endpoint.method or "",
            endpoint.service_hint or "",
            endpoint.evidence_file or "",
            endpoint.source_file or "",
        )
    )
    return endpoints


def _normalize_endpoint_row(row: dict[str, Any], csv_path: Path) -> EndpointRecord | None:
    method = None
    for key in ("method", "http_method", "verb"):
        value = _clean_text(row.get(key, ""))
        if value:
            upper_value = value.upper()
            method = upper_value if upper_value in HTTP_METHODS else None
            break

    path = ""
    for key in ("path", "path_or_url", "url", "endpoint", "uri"):
        value = _clean_text(row.get(key, ""))
        if value:
            path = value
            break

    if not path:
        return None

    service_hint = None
    for key in ("service_hint", "service", "container", "microservice"):
        value = _clean_text(row.get(key, ""))
        if value:
            service_hint = value
            break

    if service_hint is None:
        service_hint = _infer_service_hint(
            source_path=_clean_text(row.get("file", "")),
            row_text=_clean_text(row.get("text", "")),
        )

    return EndpointRecord(
        method=method,
        path=path,
        service_hint=service_hint,
        source_file=_relative_path(csv_path),
        evidence_file=_clean_text(row.get("file", "")) or None,
    )


def _infer_service_hint(source_path: str, row_text: str) -> str | None:
    workspace_match = re.search(r"workspace:\s*src/([A-Za-z0-9._-]+)", row_text, re.IGNORECASE)
    if workspace_match:
        return workspace_match.group(1)

    if not source_path:
        return None

    parts = [Path(part).stem for part in source_path.replace("\\", "/").split("/") if part]
    for token in reversed(parts):
        lowered = token.lower()
        if lowered in {"src", "main", "java", "deploy", "kubernetes", "manifests"}:
            continue
        if any(marker in lowered for marker in ("service", "frontend", "backend", "gateway", "websocket", "-fe", "-be", "-ui")):
            return token
        dotted_parts = [part for part in re.split(r"[._-]+", token) if part]
        for dotted_part in reversed(dotted_parts):
            lowered_part = dotted_part.lower()
            if lowered_part in IGNORED_DOTTED_PATH_PARTS:
                continue
            if any(marker in lowered_part for marker in ("service", "frontend", "backend", "gateway", "websocket")):
                return dotted_part
        if "." in token:
            dotted_parts = [part for part in token.split(".") if part]
            for dotted_part in reversed(dotted_parts):
                lowered_part = dotted_part.lower()
                if lowered_part in IGNORED_DOTTED_PATH_PARTS:
                    continue
                if len(lowered_part) > 2:
                    return dotted_part
    return None


def _project_prompt_purpose(project_type: str) -> str:
    if project_type == "student_project":
        return "Generate a reference microservice architecture that will later be compared against the project's DataMetrics.json file."
    return "Generate a candidate microservice architecture that will later be compared against service and endpoint evidence extracted from the project's CSV files."


def _project_validation_basis(project_type: str) -> str:
    if project_type == "student_project":
        return "DataMetrics.json"
    return "CSV endpoint evidence"


def _normalize_service_display_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", "-").strip())


def _service_aliases(name: str) -> set[str]:
    normalized = _canonical_name(name)
    aliases = {normalized}
    for suffix in ("deployment", "container", "controller", "endpoint", "service", "server", "rest", "dep"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
            aliases.add(normalized[: -len(suffix)])
    if normalized.startswith("ts") and len(normalized) > 4:
        aliases.add(normalized[2:])
    return {alias for alias in aliases if alias}


def _is_ignored_service_name(name: str) -> bool:
    canonical = _canonical_name(name)
    if not canonical:
        return True
    if canonical in GENERIC_SERVICE_HINTS or canonical in INFRASTRUCTURE_SERVICE_HINTS:
        return True
    if any(token in canonical for token in ("prometheus", "grafana", "jaeger", "rabbitmq", "mysql", "mongo")):
        return True
    return False


def _is_probable_application_endpoint(endpoint: EndpointRecord) -> bool:
    path = endpoint.path.strip()
    if not path:
        return False
    if any(path.startswith(prefix) for prefix in IGNORED_PATH_PREFIXES):
        return False
    if "${" in path:
        return False
    if endpoint.method in HTTP_METHODS:
        return True
    source_file = (endpoint.evidence_file or endpoint.source_file or "").lower()
    return any(marker in source_file for marker in ("controller", "endpoint", "rest"))


def _extract_service_name_from_path(path: str) -> str | None:
    cleaned = path.strip().strip("/")
    if not cleaned:
        return None
    if any(path.startswith(prefix) for prefix in IGNORED_PATH_PREFIXES):
        return None
    if "{" in cleaned or ":" in cleaned:
        return None
    first_segment = cleaned.split("/", 1)[0]
    if not first_segment:
        return None
    lowered = _canonical_name(first_segment)
    if lowered in {"api", "v1", "v1alpha2", "v1alpha3", "v1beta1", "ready", "metrics", "health", "healthz"}:
        return None
    if _is_ignored_service_name(first_segment):
        return None
    if "-" in first_segment or "service" in lowered:
        return first_segment
    return None


def extract_csv_service_evidence(endpoints: list[EndpointRecord]) -> dict[str, dict[str, Any]]:
    service_evidence: dict[str, dict[str, Any]] = {}

    def ensure_service(name: str) -> dict[str, Any]:
        canonical = _canonical_name(name)
        current = service_evidence.get(canonical)
        if current is None:
            current = {
                "name": _normalize_service_display_name(name),
                "aliases": set(_service_aliases(name)),
                "endpoints": set(),
            }
            service_evidence[canonical] = current
        return current

    for endpoint in endpoints:
        candidate_names: list[str] = []
        if endpoint.service_hint and not _is_ignored_service_name(endpoint.service_hint):
            candidate_names.append(endpoint.service_hint)
        path_name = _extract_service_name_from_path(endpoint.path)
        if path_name and path_name not in candidate_names:
            candidate_names.append(path_name)

        if not candidate_names:
            continue

        for name in candidate_names:
            current = ensure_service(name)
            if _is_probable_application_endpoint(endpoint):
                current["endpoints"].add(_normalize_endpoint_candidate(endpoint.method, endpoint.path))

    return service_evidence


def _normalize_endpoint_candidate(method: str | None, path: str) -> str:
    normalized_path = "/" + path.strip().lstrip("/")
    normalized_path = re.sub(r"/+", "/", normalized_path)
    normalized_path = normalized_path.rstrip("/") or "/"
    if method and method in HTTP_METHODS:
        return f"{method} {normalized_path}"
    return normalized_path


def _normalize_endpoint_string_for_comparison(value: str) -> str:
    stripped = value.strip()
    method_match = re.match(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(.+)$", stripped, re.IGNORECASE)
    if method_match:
        method = method_match.group(1).upper()
        path = method_match.group(2)
        return _normalize_endpoint_candidate(method, path)
    return _normalize_endpoint_candidate(None, stripped)


def build_architecture_prompt(project: ProjectInstance) -> str:
    description_block = project.system_description or "MISSING: system description not found in input.txt."
    user_story_lines = [story.labeled_text for story in project.user_stories]

    if not user_story_lines:
        user_story_lines = ["MISSING: no user stories were extracted from input.txt."]

    schema_text = json.dumps(OUTPUT_SCHEMA_TEMPLATE, indent=2, ensure_ascii=True)
    prompt_sections = [
        _project_prompt_purpose(project.project_type),
        "Return ONLY valid JSON. Do not add markdown fences, commentary, or explanation.",
        "Use only the information provided below. Never invent files, user stories, or features that are not supported by the input.txt evidence.",
        "If information is missing, keep the output JSON valid and explain the gap in the notes array.",
        "Preserve the user stories verbatim inside covered_user_stories when you assign them to a microservice.",
        "When listing main_endpoints, include only endpoints that are strongly implied by the description and user stories.",
        "Required JSON schema:",
        schema_text,
        f'Project name: "{project.project_name}"',
        f'Project type: "{project.project_type}"',
        f'Validation target after generation: "{_project_validation_basis(project.project_type)}"',
        "System description (verbatim):",
        description_block,
        "User stories (verbatim and enumerated):",
        "\n".join(user_story_lines),
    ]
    return "\n\n".join(prompt_sections)


def _resolve_endpoint_url(env_var_name: str, default_url: str) -> tuple[str, str]:
    configured = os.getenv(env_var_name, "").strip()
    if not configured:
        configured = default_url

    if configured.endswith("/responses"):
        return configured, "responses"
    if configured.endswith("/chat/completions"):
        return configured, "chat_completions"
    if configured.endswith("/v1"):
        return f"{configured}/chat/completions", "chat_completions"
    if configured.startswith("http"):
        return f"{configured.rstrip('/')}/chat/completions", "chat_completions"
    return default_url, "chat_completions"


def get_provider_configs() -> dict[str, ProviderConfig]:
    load_env_file()

    configs: dict[str, ProviderConfig] = {}
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        openai_url, openai_style = _resolve_endpoint_url(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1/chat/completions",
        )
        configs["openai"] = ProviderConfig(
            name="openai",
            api_key=openai_key,
            model=os.getenv("OPENAI_MODEL", "gpt-5.4").strip() or "gpt-5.4",
            endpoint_url=openai_url,
            api_style=openai_style,
        )

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        deepseek_url, deepseek_style = _resolve_endpoint_url(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com/chat/completions",
        )
        configs["deepseek"] = ProviderConfig(
            name="deepseek",
            api_key=deepseek_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner").strip() or "deepseek-reasoner",
            endpoint_url=deepseek_url,
            api_style=deepseek_style,
        )

    return configs


def _build_provider_payload(config: ProviderConfig, prompt: str) -> dict[str, Any]:
    if config.api_style == "responses":
        return {
            "model": config.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "You generate valid JSON only for software architecture analysis tasks.",
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            ],
        }

    return {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "You generate valid JSON only for software architecture analysis tasks.",
            },
            {"role": "user", "content": prompt},
        ],
    }


def _extract_provider_text(config: ProviderConfig, response_payload: dict[str, Any]) -> str:
    if config.api_style == "responses":
        if isinstance(response_payload.get("output_text"), str):
            return response_payload["output_text"]
        chunks: list[str] = []
        for item in response_payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content_item in item.get("content", []):
                content_type = content_item.get("type")
                if content_type in {"output_text", "text"}:
                    chunks.append(str(content_item.get("text", "")))
        return "".join(chunks).strip()

    choices = response_payload.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


def call_provider(
    config: ProviderConfig,
    prompt: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    payload = _build_provider_payload(config, prompt)
    request = urllib.request.Request(
        url=config.endpoint_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_PROVIDER_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return None, f"{config.name} HTTP {exc.code}: {body}", None
    except urllib.error.URLError as exc:
        return None, f"{config.name} request failed: {exc.reason}", None

    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        return None, f"{config.name} returned a non-JSON HTTP payload: {exc}", response_body

    text = _extract_provider_text(config, payload).strip()
    if not text:
        return None, f"{config.name} returned an empty completion.", None

    try:
        parsed = parse_candidate_json(text)
    except ValueError as exc:
        return None, str(exc), text
    return parsed, None, text


def parse_candidate_json(raw_text: str) -> dict[str, Any]:
    json_text = _extract_json_object(raw_text)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON response: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Invalid JSON response: top-level payload must be an object.")
    return normalize_candidate_response(parsed)


def normalize_candidate_response(payload: dict[str, Any]) -> dict[str, Any]:
    def normalize_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    microservices: list[dict[str, Any]] = []
    for entry in payload.get("microservices", []):
        if not isinstance(entry, dict):
            continue
        name = _clean_text(entry.get("name", ""))
        if not name:
            continue
        microservices.append(
            {
                "name": name,
                "responsibilities": normalize_string_list(entry.get("responsibilities")),
                "covered_user_stories": normalize_string_list(entry.get("covered_user_stories")),
                "main_endpoints": normalize_string_list(entry.get("main_endpoints")),
                "data_owned": normalize_string_list(entry.get("data_owned")),
                "dependencies": normalize_string_list(entry.get("dependencies")),
            }
        )

    communications: list[dict[str, Any]] = []
    for entry in payload.get("communications", []):
        if not isinstance(entry, dict):
            continue
        source = _clean_text(entry.get("source", ""))
        target = _clean_text(entry.get("target", ""))
        if not source or not target:
            continue
        communications.append(
            {
                "source": source,
                "target": target,
                "type": _clean_text(entry.get("type", "unknown")) or "unknown",
                "description": _clean_text(entry.get("description", "")),
                "related_user_stories": normalize_string_list(entry.get("related_user_stories")),
            }
        )

    return {
        "system_name": _clean_text(payload.get("system_name", "")),
        "microservices": microservices,
        "communications": communications,
        "unassigned_user_stories": normalize_string_list(payload.get("unassigned_user_stories")),
        "notes": normalize_string_list(payload.get("notes")),
    }


def _extract_json_object(raw_text: str) -> str:
    stripped = raw_text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        stripped = fenced_match.group(1).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    if start == -1:
        raise ValueError("Invalid JSON response: no JSON object found in provider output.")

    depth = 0
    in_string = False
    escape = False
    object_start = None
    for index in range(start, len(stripped)):
        char = stripped[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                object_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and object_start is not None:
                return stripped[object_start : index + 1]

    raise ValueError("Invalid JSON response: could not isolate a complete JSON object.")


def build_retry_prompt(original_prompt: str, invalid_response: str) -> str:
    return "\n\n".join(
        [
            "Your previous answer was not valid JSON.",
            "Return ONLY valid JSON matching the required schema.",
            "Do not include markdown fences or any explanatory text.",
            "Original request:",
            original_prompt,
            "Previous invalid response:",
            invalid_response,
        ]
    )


def generate_provider_response(
    provider_name: str,
    prompt: str,
    provider_configs: dict[str, ProviderConfig],
) -> tuple[dict[str, Any] | None, str | None]:
    config = provider_configs.get(provider_name)
    if config is None:
        return None, f"{provider_name} provider is not configured."

    response, error, raw_text = call_provider(config, prompt)
    if response is not None:
        return response, None

    if error and "Invalid JSON response:" in error:
        retry_prompt = build_retry_prompt(prompt, raw_text or error)
        retry_response, retry_error, _ = call_provider(config, retry_prompt)
        if retry_response is not None:
            return retry_response, None
        return None, f"{provider_name} retry failed: {retry_error}"

    return None, error


def _normalize_story_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _resolve_story_identifier(
    value: str,
    source_stories_by_id: dict[int, UserStory],
    normalized_story_lookup: dict[str, int],
) -> int | None:
    direct_match = re.match(r"^\s*(\d+)[.)]?\s*", value)
    if direct_match:
        story_id = int(direct_match.group(1))
        if story_id in source_stories_by_id:
            return story_id

    story_id = normalized_story_lookup.get(_normalize_story_text(value))
    if story_id is not None:
        return story_id

    if direct_match:
        return int(direct_match.group(1))
    return None


def _format_user_story(story: UserStory | None, story_id: int) -> str:
    if story is None:
        return str(story_id)
    return story.labeled_text


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def evaluate_candidate_story_coverage(
    candidate: dict[str, Any],
    input_user_stories: list[UserStory],
) -> tuple[list[str], list[str]]:
    source_stories_by_id = {story.index: story for story in input_user_stories}
    source_story_ids = set(source_stories_by_id)
    normalized_story_lookup = {
        _normalize_story_text(story.text): story.index
        for story in input_user_stories
    }

    covered_story_ids: set[int] = set()
    for service in candidate.get("microservices", []):
        for story_text in service.get("covered_user_stories", []):
            story_id = _resolve_story_identifier(
                story_text,
                source_stories_by_id=source_stories_by_id,
                normalized_story_lookup=normalized_story_lookup,
            )
            if story_id is not None and story_id in source_story_ids:
                covered_story_ids.add(story_id)

    covered = [
        _format_user_story(source_stories_by_id[story_id], story_id)
        for story_id in sorted(covered_story_ids)
    ]
    uncovered = [
        _format_user_story(source_stories_by_id[story_id], story_id)
        for story_id in sorted(source_story_ids - covered_story_ids)
    ]
    return covered, uncovered


def validate_candidate_against_reference(
    candidate: dict[str, Any],
    reference_services: list[ReferenceService],
    input_user_stories: list[UserStory],
) -> dict[str, Any]:
    reference_service_map = {
        _canonical_name(service.set_name): service.set_name
        for service in reference_services
    }
    candidate_service_map = {
        _canonical_name(service["name"]): service["name"]
        for service in candidate.get("microservices", [])
        if _canonical_name(service.get("name", ""))
    }

    matched_service_keys = sorted(set(reference_service_map) & set(candidate_service_map))
    missing_service_keys = sorted(set(reference_service_map) - set(candidate_service_map))
    extra_service_keys = sorted(set(candidate_service_map) - set(reference_service_map))

    reference_by_id = {service.set_id: service.set_name for service in reference_services}
    reference_communications = {
        (_canonical_name(service.set_name), _canonical_name(reference_by_id[target_id])): {
            "source": service.set_name,
            "target": reference_by_id[target_id],
        }
        for service in reference_services
        for target_id in service.linked_service_ids
        if target_id in reference_by_id
    }
    candidate_communications = {
        (_canonical_name(entry["source"]), _canonical_name(entry["target"])): {
            "source": entry["source"],
            "target": entry["target"],
            "type": entry.get("type", "unknown"),
            "description": entry.get("description", ""),
        }
        for entry in candidate.get("communications", [])
        if entry.get("source") and entry.get("target")
    }

    matched_communication_keys = sorted(set(reference_communications) & set(candidate_communications))
    missing_communication_keys = sorted(set(reference_communications) - set(candidate_communications))
    extra_communication_keys = sorted(set(candidate_communications) - set(reference_communications))
    covered_stories, uncovered_stories = evaluate_candidate_story_coverage(candidate, input_user_stories)

    return {
        "reference_used": True,
        "validation_basis": "data_metrics",
        "matched_services": [reference_service_map[key] for key in matched_service_keys],
        "missing_services": [reference_service_map[key] for key in missing_service_keys],
        "extra_services": [candidate_service_map[key] for key in extra_service_keys],
        "matched_communications": [
            reference_communications[key] for key in matched_communication_keys
        ],
        "missing_communications": [
            reference_communications[key] for key in missing_communication_keys
        ],
        "extra_communications": [
            candidate_communications[key] for key in extra_communication_keys
        ],
        "matched_endpoints": [],
        "missing_endpoints": [],
        "extra_endpoints": [],
        "covered_user_stories": covered_stories,
        "uncovered_user_stories": uncovered_stories,
        "metrics": {
            "service_precision": _safe_ratio(len(matched_service_keys), len(candidate_service_map)),
            "service_recall": _safe_ratio(len(matched_service_keys), len(reference_service_map)),
            "communication_precision": _safe_ratio(
                len(matched_communication_keys),
                len(candidate_communications),
            ),
            "communication_recall": _safe_ratio(
                len(matched_communication_keys),
                len(reference_communications),
            ),
            "endpoint_precision": 0.0,
            "endpoint_recall": 0.0,
        },
    }


def validate_candidate_against_csv_evidence(
    candidate: dict[str, Any],
    endpoints: list[EndpointRecord],
    input_user_stories: list[UserStory],
) -> dict[str, Any]:
    service_evidence = extract_csv_service_evidence(endpoints)
    evidence_name_by_alias: dict[str, str] = {}
    evidence_endpoints_by_alias: dict[str, set[str]] = {}

    for evidence in service_evidence.values():
        for alias in evidence["aliases"]:
            evidence_name_by_alias[alias] = evidence["name"]
            evidence_endpoints_by_alias[alias] = evidence["endpoints"]

    matched_services: list[str] = []
    missing_services_map = {key: value["name"] for key, value in service_evidence.items()}
    extra_services: list[str] = []
    matched_endpoints: set[str] = set()
    extra_endpoints: set[str] = set()
    candidate_service_count = 0

    for service in candidate.get("microservices", []):
        service_name = service.get("name", "")
        if not service_name:
            continue
        candidate_service_count += 1
        service_aliases = _service_aliases(service_name)
        evidence_match_alias = next(
            (alias for alias in service_aliases if alias in evidence_name_by_alias),
            None,
        )
        if evidence_match_alias is None:
            extra_services.append(service_name)
            for endpoint_text in service.get("main_endpoints", []):
                extra_endpoints.add(_normalize_endpoint_string_for_comparison(endpoint_text))
            continue

        evidence_name = evidence_name_by_alias[evidence_match_alias]
        if evidence_name not in matched_services:
            matched_services.append(evidence_name)
        missing_services_map.pop(_canonical_name(evidence_name), None)

        evidence_endpoint_set = evidence_endpoints_by_alias.get(evidence_match_alias, set())
        for endpoint_text in service.get("main_endpoints", []):
            normalized_candidate_endpoint = _normalize_endpoint_string_for_comparison(endpoint_text)
            if normalized_candidate_endpoint in evidence_endpoint_set:
                matched_endpoints.add(normalized_candidate_endpoint)
            else:
                extra_endpoints.add(normalized_candidate_endpoint)

    missing_endpoints: set[str] = set()
    for evidence in service_evidence.values():
        missing_endpoints.update(evidence["endpoints"] - matched_endpoints)

    covered_stories, uncovered_stories = evaluate_candidate_story_coverage(candidate, input_user_stories)
    evidence_service_aliases = set(evidence_name_by_alias)

    return {
        "reference_used": bool(service_evidence),
        "validation_basis": "csv_evidence",
        "matched_services": matched_services,
        "missing_services": list(missing_services_map.values()),
        "extra_services": extra_services,
        "matched_communications": [],
        "missing_communications": [],
        "extra_communications": [],
        "matched_endpoints": sorted(matched_endpoints),
        "missing_endpoints": sorted(missing_endpoints),
        "extra_endpoints": sorted(extra_endpoints),
        "covered_user_stories": covered_stories,
        "uncovered_user_stories": uncovered_stories,
        "metrics": {
            "service_precision": _safe_ratio(len(matched_services), candidate_service_count),
            "service_recall": _safe_ratio(len(matched_services), len(service_evidence)),
            "communication_precision": 0.0,
            "communication_recall": 0.0,
            "endpoint_precision": _safe_ratio(len(matched_endpoints), len(matched_endpoints) + len(extra_endpoints)),
            "endpoint_recall": _safe_ratio(len(matched_endpoints), len(matched_endpoints) + len(missing_endpoints)),
        },
    }


def empty_validation_report(reference_used: bool = False) -> dict[str, Any]:
    return {
        "reference_used": reference_used,
        "validation_basis": None,
        "matched_services": [],
        "missing_services": [],
        "extra_services": [],
        "matched_communications": [],
        "missing_communications": [],
        "extra_communications": [],
        "matched_endpoints": [],
        "missing_endpoints": [],
        "extra_endpoints": [],
        "covered_user_stories": [],
        "uncovered_user_stories": [],
        "metrics": {
            "service_precision": 0.0,
            "service_recall": 0.0,
            "communication_precision": 0.0,
            "communication_recall": 0.0,
            "endpoint_precision": 0.0,
            "endpoint_recall": 0.0,
        },
    }


def build_project_artifact(
    project: ProjectInstance,
    include_llm_calls: bool = True,
    provider_configs: dict[str, ProviderConfig] | None = None,
) -> dict[str, Any]:
    prompt = build_architecture_prompt(project)
    provider_configs = provider_configs or get_provider_configs()
    errors = list(project.errors)
    llm_responses: dict[str, Any] = {"openai": {}, "deepseek": {}}

    if include_llm_calls:
        for provider_name in ("openai", "deepseek"):
            response, error = generate_provider_response(provider_name, prompt, provider_configs)
            if response is not None:
                llm_responses[provider_name] = response
            elif error:
                errors.append(error)

    validation = empty_validation_report(reference_used=False)
    validation["validation_basis"] = "data_metrics" if project.project_type == "student_project" else "csv_evidence"
    validation_candidate = llm_responses.get("openai") or llm_responses.get("deepseek")
    if project.project_type == "student_project" and project.reference_architecture and validation_candidate:
        validation = validate_candidate_against_reference(
            candidate=validation_candidate,
            reference_services=project.reference_architecture,
            input_user_stories=project.user_stories,
        )
    elif project.project_type == "open_source" and project.endpoints and validation_candidate:
        validation = validate_candidate_against_csv_evidence(
            candidate=validation_candidate,
            endpoints=project.endpoints,
            input_user_stories=project.user_stories,
        )

    status = determine_status(
        project=project,
        llm_responses=llm_responses,
        errors=errors,
        include_llm_calls=include_llm_calls,
    )

    return {
        "project_name": project.project_name,
        "project_type": project.project_type,
        "analysis_profile": {
            "prompt_source": "input_txt",
            "validation_target": _project_validation_basis(project.project_type),
        },
        "input_summary": {
            "input_txt_found": project.input_path is not None,
            "csv_files_found": [_relative_path(path) for path in project.csv_paths],
            "reference_json_found": project.reference_path is not None,
            "user_story_count": len(project.user_stories),
            "endpoint_count": len(project.endpoints),
        },
        "llm_request": {
            "model_prompts": {
                "openai": prompt,
                "deepseek": prompt,
            }
        },
        "llm_responses": llm_responses,
        "validation": validation,
        "status": status,
        "errors": errors,
    }


def determine_status(
    project: ProjectInstance,
    llm_responses: dict[str, Any],
    errors: list[str],
    include_llm_calls: bool,
) -> str:
    has_any_response = any(bool(response) for response in llm_responses.values())
    has_input = project.input_path is not None
    has_missing_artifacts = (
        project.input_path is None
        or not project.user_stories
        or (project.project_type == "student_project" and project.reference_path is None)
        or (project.project_type == "student_project" and project.reference_path is not None and project.reference_architecture is None)
        or (project.project_type == "open_source" and not project.csv_paths)
    )

    if has_any_response and has_input and not has_missing_artifacts and not errors:
        return "success"
    if has_any_response or not include_llm_calls or project.input_path or project.csv_paths:
        return "partial"
    return "failed"


def persist_results(payload: dict[str, Any], output_path: Path | None = None) -> Path:
    target_path = output_path or DEFAULT_RESULTS_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target_path


def run_batch_analysis(
    output_path: str | None = None,
    include_llm_calls: bool = True,
    project_name: str | None = None,
    project_type: str | None = None,
) -> dict[str, Any]:
    provider_configs = get_provider_configs() if include_llm_calls else {}
    project_directories = discover_project_directories(
        project_name=project_name,
        project_type=project_type,
    )

    results: list[dict[str, Any]] = []
    for directory, current_project_type in project_directories:
        try:
            project = parse_project_instance(directory, current_project_type)
            artifact = build_project_artifact(
                project=project,
                include_llm_calls=include_llm_calls,
                provider_configs=provider_configs,
            )
        except Exception as exc:  # pragma: no cover
            artifact = {
                "project_name": directory.name,
                "project_type": current_project_type,
                "analysis_profile": {
                    "prompt_source": "input_txt",
                    "validation_target": _project_validation_basis(current_project_type),
                },
                "input_summary": {
                    "input_txt_found": False,
                    "csv_files_found": [],
                    "reference_json_found": False,
                    "user_story_count": 0,
                    "endpoint_count": 0,
                },
                "llm_request": {
                    "model_prompts": {
                        "openai": "",
                        "deepseek": "",
                    }
                },
                "llm_responses": {
                    "openai": {},
                    "deepseek": {},
                },
                "validation": empty_validation_report(reference_used=False),
                "status": "failed",
                "errors": [f"Unhandled project failure: {exc}"],
            }
        results.append(artifact)

    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "results": results,
    }
    persisted_path = persist_results(
        payload=payload,
        output_path=Path(output_path) if output_path else None,
    )
    payload["output_path"] = _relative_path(persisted_path)
    return payload
