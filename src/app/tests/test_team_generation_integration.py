"""
Integration tests of the team generation against the real algorithms API.

They need a running algorithms API (python manage.py runserver 8001 in the repository
"algorithms") and TEAM_GENERATION_API_URL / TEAM_GENERATION_API_KEY in .env.
If the API cannot be reached or no key is set, the tests are skipped.
See docs/team_generation.md.
"""

import unittest

import requests
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from app.services.team_generation import ALGORITHM_TYPES
from app.tests.data import (
    NUM_STUDENTS,
    assert_valid_team_set_response,
    create_test_data,
)


def _check_api():
    if not settings.TEAM_GENERATION_API_KEY:
        raise unittest.SkipTest("TEAM_GENERATION_API_KEY is not set.")
    try:
        response = requests.post(
            settings.TEAM_GENERATION_API_URL,
            json={},
            headers={"X-Api-Key": settings.TEAM_GENERATION_API_KEY},
            timeout=5,
        )
    except requests.RequestException:
        raise unittest.SkipTest(
            f"Algorithms API at {settings.TEAM_GENERATION_API_URL} is not reachable."
        )
    # an empty body is invalid, so a reachable API with a valid key answers with 400
    if response.status_code == 401:
        raise AssertionError(
            "The algorithms API rejected TEAM_GENERATION_API_KEY. Its hash must be in "
            "API_AUTH_ALLOWED_KEYS of the algorithms API."
        )


class TestGenerateTeamsWithAlgorithmsApi(TestCase):
    @classmethod
    def setUpClass(cls):
        _check_api()
        super().setUpClass()

    def setUp(self):
        self.data = create_test_data()
        self.client = APIClient()
        self.client.force_authenticate(user=self.data.instructor)
        self.course_url = f"/api/v1/courses/{self.data.course.pk}"

    def generate(self, data):
        return self.client.post(
            f"{self.course_url}/generate_teams/", data, format="json"
        )

    def assert_generates_valid_teams(
        self, data, total_teams, min_team_size, max_team_size
    ):
        response = self.generate(data)
        self.assertEqual(response.status_code, 200, response.content)

        team_set_id = response.json()["team_set_id"]
        response = self.client.get(f"{self.course_url}/team-sets/{team_set_id}/")
        self.assertEqual(response.status_code, 200)
        assert_valid_team_set_response(
            self,
            response.json(),
            self.data.students,
            total_teams=total_teams,
            min_team_size=min_team_size,
            max_team_size=max_team_size,
        )

    def test_test_data_has_10_to_20_students(self):
        self.assertTrue(10 <= NUM_STUDENTS <= 20)

    def test_default_parameters(self):
        # priority algorithm, teams of 3 to 5 students
        self.assert_generates_valid_teams(
            {}, total_teams=3, min_team_size=3, max_team_size=5
        )

    def test_every_algorithm_type(self):
        for algorithm_type in ALGORITHM_TYPES:
            with self.subTest(algorithm_type=algorithm_type):
                self.assert_generates_valid_teams(
                    {"algorithm_type": algorithm_type},
                    total_teams=3,
                    min_team_size=3,
                    max_team_size=5,
                )

    def test_custom_team_sizes(self):
        for algorithm_type in ALGORITHM_TYPES:
            with self.subTest(algorithm_type=algorithm_type):
                self.assert_generates_valid_teams(
                    {
                        "algorithm_type": algorithm_type,
                        "min_team_size": 3,
                        "max_team_size": 4,
                        "total_teams": 4,
                    },
                    total_teams=4,
                    min_team_size=3,
                    max_team_size=4,
                )

    def test_team_sizes_that_do_not_fit_are_rejected(self):
        # 15 students do not fit into 2 teams of at most 5 students
        response = self.generate({"total_teams": 2, "max_team_size": 5})
        self.assertEqual(response.status_code, 400)
        self.assertIn("do not fit", response.json()["error"])
