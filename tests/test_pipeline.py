from __future__ import annotations

import unittest
from pathlib import Path

from server.pipeline import (
    ProjectInstance,
    ReferenceService,
    UserStory,
    build_architecture_prompt,
    parse_endpoint_files,
    parse_user_stories,
    validate_candidate_against_csv_evidence,
    validate_candidate_against_reference,
)


class PipelineTests(unittest.TestCase):
    def test_parse_user_stories_handles_multiline_and_bullets(self) -> None:
        section = """
1) As a User, I want to upload a photo
so that it can be processed.
- As a User, I want to list my photos
  so that I can browse them.
"""

        stories = parse_user_stories(section)

        self.assertEqual(2, len(stories))
        self.assertEqual("1) As a User, I want to upload a photo so that it can be processed.", stories[0].labeled_text)
        self.assertEqual("2) As a User, I want to list my photos so that I can browse them.", stories[1].labeled_text)

    def test_parse_endpoint_files_normalizes_and_deduplicates(self) -> None:
        csv_path = Path(__file__).resolve().parent / "fixtures" / "sample_endpoints.csv"
        endpoints = parse_endpoint_files([csv_path])

        self.assertEqual(2, len(endpoints))
        self.assertEqual("GET", endpoints[0].method)
        self.assertEqual("/api/photos", endpoints[0].path)
        self.assertEqual("photo-service", endpoints[0].service_hint)
        self.assertEqual("/photo-service", endpoints[1].path)

    def test_validate_candidate_against_reference(self) -> None:
        candidate = {
            "system_name": "ChronoPic",
            "microservices": [
                {
                    "name": "auth service",
                    "responsibilities": ["authentication"],
                    "covered_user_stories": ["1) As a User, I want to sign up", "2) As a User, I want to log in"],
                    "main_endpoints": [],
                    "data_owned": [],
                    "dependencies": [],
                },
                {
                    "name": "photo-service",
                    "responsibilities": ["photos"],
                    "covered_user_stories": ["3) As a User, I want to list photos"],
                    "main_endpoints": [],
                    "data_owned": [],
                    "dependencies": ["auth service"],
                },
                {
                    "name": "extra-service",
                    "responsibilities": ["other"],
                    "covered_user_stories": [],
                    "main_endpoints": [],
                    "data_owned": [],
                    "dependencies": [],
                },
            ],
            "communications": [
                {
                    "source": "auth service",
                    "target": "photo-service",
                    "type": "sync",
                    "description": "auth before photo access",
                    "related_user_stories": [],
                },
                {
                    "source": "extra-service",
                    "target": "photo-service",
                    "type": "unknown",
                    "description": "",
                    "related_user_stories": [],
                },
            ],
            "unassigned_user_stories": [],
            "notes": [],
        }
        reference = [
            ReferenceService(1, "auth-service", [1, 2], [2], True),
            ReferenceService(2, "photo-service", [3], [], True),
        ]
        stories = [
            UserStory(1, "As a User, I want to sign up"),
            UserStory(2, "As a User, I want to log in"),
            UserStory(3, "As a User, I want to list photos"),
        ]

        validation = validate_candidate_against_reference(candidate, reference, stories)

        self.assertEqual(["auth-service", "photo-service"], validation["matched_services"])
        self.assertEqual(["extra-service"], validation["extra_services"])
        self.assertEqual([], validation["missing_services"])
        self.assertEqual(1.0, validation["metrics"]["service_recall"])
        self.assertEqual(0.6667, validation["metrics"]["service_precision"])
        self.assertEqual(1, len(validation["matched_communications"]))
        self.assertEqual(1, len(validation["extra_communications"]))
        self.assertEqual([], validation["uncovered_user_stories"])

    def test_build_architecture_prompt_uses_input_txt_evidence_only(self) -> None:
        project = ProjectInstance(
            project_name="ChronoPic",
            project_type="student_project",
            project_dir=Path("."),
            input_path=Path("input.txt"),
            csv_paths=[Path("sample.csv")],
            reference_path=Path("DataMetrics.json"),
            system_description="A photo platform.",
            user_stories=[UserStory(1, "As a User, I want to upload a photo.")],
            endpoints=[],
            reference_architecture=None,
            errors=[],
        )

        prompt = build_architecture_prompt(project)

        self.assertIn("DataMetrics.json", prompt)
        self.assertIn("A photo platform.", prompt)
        self.assertIn("1) As a User, I want to upload a photo.", prompt)
        self.assertNotIn("Endpoints (normalized", prompt)

    def test_validate_candidate_against_csv_evidence(self) -> None:
        endpoints = [
            parse_endpoint_files([Path(__file__).resolve().parent / "fixtures" / "sample_endpoints.csv"])[0],
            parse_endpoint_files([Path(__file__).resolve().parent / "fixtures" / "sample_endpoints.csv"])[1],
        ]
        candidate = {
            "system_name": "Photo App",
            "microservices": [
                {
                    "name": "photo-service",
                    "responsibilities": ["photos"],
                    "covered_user_stories": ["1) As a User, I want to upload a photo"],
                    "main_endpoints": ["GET /api/photos", "/photo-service"],
                    "data_owned": [],
                    "dependencies": [],
                },
                {
                    "name": "billing-service",
                    "responsibilities": ["billing"],
                    "covered_user_stories": [],
                    "main_endpoints": ["POST /api/payments"],
                    "data_owned": [],
                    "dependencies": [],
                },
            ],
            "communications": [],
            "unassigned_user_stories": [],
            "notes": [],
        }
        stories = [UserStory(1, "As a User, I want to upload a photo")]

        validation = validate_candidate_against_csv_evidence(candidate, endpoints, stories)

        self.assertEqual("csv_evidence", validation["validation_basis"])
        self.assertIn("photo-service", validation["matched_services"])
        self.assertIn("billing-service", validation["extra_services"])
        self.assertIn("GET /api/photos", validation["matched_endpoints"])
        self.assertIn("POST /api/payments", validation["extra_endpoints"])
        self.assertEqual([], validation["uncovered_user_stories"])


if __name__ == "__main__":
    unittest.main()
