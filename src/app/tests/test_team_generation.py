"""
Tests of the team generation with a mocked algorithms API.

They check the request the backend sends, how it handles the answers of the API and
that the endpoints return the saved teams. The tests against the real API are in
test_team_generation_integration.py.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from app.models.attribute import Attribute, AttributeManageType, AttributeValueType
from app.models.course import Course
from app.models.team import TeamSet
from app.services.team_generation import (
    TeamGenerationParameters,
    build_payload,
    get_students,
)
from app.tests.data import (
    NUM_STUDENTS,
    assert_valid_team_set_response,
    create_test_data,
)

API_URL = "http://algorithms.test/api/generate/teams/"
API_KEY = "test-key"
POST_PATH = "app.services.team_generation.requests.post"


def fake_api_response(payload: Dict[str, Any], status_code: int = 200) -> MagicMock:
    """
    Answers like the algorithms API: the students are dealt to the teams in turn.
    """
    total_teams = payload["team_generation_options"]["total_teams"]
    teams = [
        {"id": i + 1, "name": f"Team {i + 1}", "students": []}
        for i in range(total_teams)
    ]
    for index, student in enumerate(payload["students"]):
        teams[index % total_teams]["students"].append({"id": student["id"]})
    return mock_response(
        status_code,
        {"teams": {"teams": teams}, "metadata": {}, "error": None},
    )


def mock_response(status_code: int, body=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = body
    response.text = text
    return response


class TestBuildPayload(TestCase):
    def setUp(self):
        self.data = create_test_data()
        self.students = get_students(self.data.course)

    def build(self, **kwargs):
        return build_payload(
            self.data.course, self.students, TeamGenerationParameters(**kwargs)
        )

    def test_contains_all_students_with_attributes_and_relationships(self):
        payload = self.build()
        students = {s["id"]: s for s in payload["students"]}
        self.assertEqual(len(students), NUM_STUDENTS)

        anna = students[self.data.students[0].pk]
        self.assertEqual(anna["name"], "Anna Test")
        # number attribute keeps its value, string attribute is numbered by option
        self.assertEqual(anna["attributes"][str(self.data.experience.pk)], [1])
        self.assertEqual(anna["attributes"][str(self.data.study_program.pk)], [0])
        self.assertEqual(
            anna["relationships"], {str(self.data.students[1].pk): "friend"}
        )
        greta = students[self.data.students[6].pk]
        self.assertEqual(
            greta["relationships"], {str(self.data.students[7].pk): "enemy"}
        )

    def test_default_team_options(self):
        options = self.build()["team_generation_options"]
        self.assertEqual(
            options,
            {
                "initial_teams": [],
                "max_team_size": 5,
                "min_team_size": 3,
                # 15 students, at most 5 per team
                "total_teams": 3,
            },
        )

    def test_priority_is_default_with_derived_priorities(self):
        options = self.build()["algorithm_options"]
        self.assertEqual(options["algorithm_type"], "priority")
        self.assertEqual(options["max_project_preferences"], 0)
        self.assertEqual(
            options["priorities"],
            [
                {
                    "priority_type": "social_preference",
                    "max_num_friends": 1,
                    "max_num_enemies": 1,
                },
                {
                    "priority_type": "diversity",
                    "attribute_id": self.data.experience.pk,
                    "strategy": "diversify",
                },
                {
                    "priority_type": "diversity",
                    "attribute_id": self.data.study_program.pk,
                    "strategy": "diversify",
                },
            ],
        )

    def test_custom_priorities_are_passed_on(self):
        priorities = [{"priority_type": "project_requirement"}]
        options = self.build(priorities=priorities)["algorithm_options"]
        self.assertEqual(options["priorities"], priorities)

    def test_options_for_every_algorithm_type(self):
        self.assertEqual(
            self.build(algorithm_type="random")["algorithm_options"],
            {"algorithm_type": "random"},
        )
        for algorithm_type in ["weight", "social"]:
            options = self.build(algorithm_type=algorithm_type)["algorithm_options"]
            self.assertEqual(options["algorithm_type"], algorithm_type)
            self.assertEqual(
                options["attributes_to_diversify"],
                [self.data.experience.pk, self.data.study_program.pk],
            )
            self.assertNotIn("priorities", options)

    def test_selected_attributes_only(self):
        payload = self.build(attributes=[self.data.experience])
        for student in payload["students"]:
            self.assertEqual(
                list(student["attributes"].keys()), [str(self.data.experience.pk)]
            )

    def test_total_teams_can_be_set(self):
        payload = self.build(total_teams=4, min_team_size=3, max_team_size=4)
        self.assertEqual(payload["team_generation_options"]["total_teams"], 4)


@override_settings(TEAM_GENERATION_API_URL=API_URL, TEAM_GENERATION_API_KEY=API_KEY)
class TestGenerateTeamsEndpoint(TestCase):
    def setUp(self):
        self.data = create_test_data()
        self.client = APIClient()
        self.client.force_authenticate(user=self.data.instructor)
        self.url = f"/api/v1/courses/{self.data.course.pk}/generate_teams/"

    def post(self, data=None):
        return self.client.post(self.url, data or {}, format="json")

    def get_team_set(self, team_set_id):
        response = self.client.get(
            f"/api/v1/courses/{self.data.course.pk}/team-sets/{team_set_id}/"
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_generates_and_saves_teams(self):
        with patch(
            POST_PATH, side_effect=lambda *a, **kw: fake_api_response(kw["json"])
        ) as post:
            response = self.post()

        self.assertEqual(response.status_code, 200, response.content)
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], API_URL)
        self.assertEqual(post.call_args.kwargs["headers"], {"X-Api-Key": API_KEY})

        team_set = TeamSet.objects.get(pk=response.json()["team_set_id"])
        self.assertEqual(team_set.name, "Team Set 1 (priority)")
        assert_valid_team_set_response(
            self,
            self.get_team_set(team_set.pk),
            self.data.students,
            total_teams=3,
            min_team_size=3,
            max_team_size=5,
        )

    def test_passes_request_parameters(self):
        with patch(
            POST_PATH, side_effect=lambda *a, **kw: fake_api_response(kw["json"])
        ) as post:
            response = self.post(
                {
                    "algorithm_type": "weight",
                    "min_team_size": 3,
                    "max_team_size": 4,
                    "total_teams": 4,
                    "attributes": [self.data.study_program.pk],
                }
            )

        self.assertEqual(response.status_code, 200, response.content)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["algorithm_options"]["algorithm_type"], "weight")
        self.assertEqual(
            payload["algorithm_options"]["attributes_to_diversify"],
            [self.data.study_program.pk],
        )
        self.assertEqual(payload["team_generation_options"]["total_teams"], 4)
        self.assertEqual(payload["team_generation_options"]["max_team_size"], 4)

    def test_legacy_attribute_parameter_still_works(self):
        with patch(
            POST_PATH, side_effect=lambda *a, **kw: fake_api_response(kw["json"])
        ) as post:
            response = self.post({"attribute": self.data.experience.pk})

        self.assertEqual(response.status_code, 200, response.content)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(
            payload["algorithm_options"]["attributes_to_diversify"],
            [self.data.experience.pk],
        )

    def test_invalid_parameters_are_rejected_without_calling_the_api(self):
        invalid_requests = [
            {"min_team_size": 5, "max_team_size": 3},
            {"algorithm_type": "unknown"},
            {"algorithm_type": "weight", "priorities": []},
            {"attributes": [999999]},
        ]
        with patch(POST_PATH) as post:
            for data in invalid_requests:
                with self.subTest(data=data):
                    self.assertEqual(self.post(data).status_code, 400)
        post.assert_not_called()

    def test_attribute_of_another_course_is_rejected(self):
        other_course = Course.objects.create(
            name="Other course", organization=self.data.course.organization
        )
        other_attribute = Attribute.objects.create(
            course=other_course,
            name="Other attribute",
            value_type=AttributeValueType.NUMBER,
            max_selections=1,
            manage_type=AttributeManageType.USER_MANAGED,
        )
        with patch(POST_PATH) as post:
            response = self.post({"attributes": [other_attribute.pk]})
        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_api_errors_return_an_error_and_save_nothing(self):
        cases = [
            # the API rejects the input, e.g. team sizes that do not fit
            (mock_response(400, {"teams": None, "error": "does not fit"}), 400),
            (mock_response(401, text="Invalid API key provided"), 502),
            (mock_response(500, {"teams": None, "error": "boom"}), 502),
            (requests.ConnectionError("refused"), 502),
            (requests.Timeout("too slow"), 504),
        ]
        for api_answer, expected_status in cases:
            with self.subTest(api_answer=api_answer):
                with patch(POST_PATH, side_effect=[api_answer]):
                    response = self.post()
                self.assertEqual(response.status_code, expected_status)
                self.assertIn("error", response.json())
        self.assertFalse(TeamSet.objects.exists())

    def test_invalid_result_of_the_api_is_rejected(self):
        def drop_one_student(*args, **kwargs):
            response = fake_api_response(kwargs["json"])
            response.json.return_value["teams"]["teams"][0]["students"].pop()
            return response

        with patch(POST_PATH, side_effect=drop_one_student):
            response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertIn("unassigned", response.json()["error"])
        self.assertFalse(TeamSet.objects.exists())

    @override_settings(TEAM_GENERATION_API_KEY=None)
    def test_missing_configuration_returns_503(self):
        with patch(POST_PATH) as post:
            response = self.post()
        self.assertEqual(response.status_code, 503)
        post.assert_not_called()
