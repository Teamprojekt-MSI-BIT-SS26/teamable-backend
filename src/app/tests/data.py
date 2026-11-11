"""
Test data for the team generation tests: a course with 15 students, two attributes,
friends and one pair of enemies.
"""

from dataclasses import dataclass
from typing import Dict, List

from django.test import TestCase

from accounts.models import MyUser
from app.models.attribute import (
    Attribute,
    AttributeManageType,
    AttributeOption,
    AttributeResponse,
    AttributeValueType,
)
from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from app.models.organization import LMSTypeOptions, Organization
from app.models.relationship import Relationship, RelationshipType

NUM_STUDENTS = 15
FIRST_NAMES = [
    "Anna",
    "Ben",
    "Clara",
    "David",
    "Emma",
    "Felix",
    "Greta",
    "Hannes",
    "Ida",
    "Jonas",
    "Klara",
    "Lukas",
    "Mia",
    "Noah",
    "Olivia",
]


@dataclass
class TeamGenerationTestData:
    course: Course
    instructor: MyUser
    students: List[CourseMember]
    experience: Attribute
    study_program: Attribute
    # index of the student -> indices of the related students
    friends: Dict[int, List[int]]
    enemies: Dict[int, List[int]]


def create_test_data() -> TeamGenerationTestData:
    organization = Organization.objects.create(
        name="HTWG Test", lms_type=LMSTypeOptions.CANVAS
    )
    course = Course.objects.create(name="Teamprojekt", organization=organization)

    instructor = MyUser.objects.create_user(username="instructor", password="test")
    CourseMember.objects.create(
        user=instructor, course=course, role=UserRole.INSTRUCTOR
    )

    students = [
        CourseMember.objects.create(
            course=course,
            role=UserRole.STUDENT,
            first_name=first_name,
            last_name="Test",
            lms_id=str(1000 + index),
            sis_user_id=str(100000 + index),
        )
        for index, first_name in enumerate(FIRST_NAMES[:NUM_STUDENTS])
    ]

    experience = _create_attribute(
        course,
        name="Programming experience",
        value_type=AttributeValueType.NUMBER,
        options=[("Beginner", "1"), ("Intermediate", "2"), ("Advanced", "3")],
    )
    study_program = _create_attribute(
        course,
        name="Study program",
        value_type=AttributeValueType.STRING,
        options=[("MSI", "MSI"), ("BIT", "BIT"), ("WIN", "WIN")],
    )
    experience_options = list(experience.options.order_by("id"))
    study_program_options = list(study_program.options.order_by("id"))
    for index, student in enumerate(students):
        AttributeResponse.objects.create(
            course_member=student, attribute_option=experience_options[index % 3]
        )
        AttributeResponse.objects.create(
            course_member=student,
            attribute_option=study_program_options[(index // 3) % 3],
        )

    friends = {0: [1], 1: [0], 2: [3], 4: [5]}
    enemies = {6: [7]}
    for relationship_type, relations in [
        (RelationshipType.FRIEND, friends),
        (RelationshipType.ENEMY, enemies),
    ]:
        for from_index, to_indices in relations.items():
            for to_index in to_indices:
                Relationship.objects.create(
                    from_member=students[from_index],
                    to_member=students[to_index],
                    type=relationship_type,
                )

    return TeamGenerationTestData(
        course=course,
        instructor=instructor,
        students=students,
        experience=experience,
        study_program=study_program,
        friends=friends,
        enemies=enemies,
    )


def _create_attribute(course, name, value_type, options) -> Attribute:
    attribute = Attribute.objects.create(
        course=course,
        name=name,
        value_type=value_type,
        max_selections=1,
        manage_type=AttributeManageType.USER_MANAGED,
    )
    for label, value in options:
        AttributeOption.objects.create(attribute=attribute, label=label, value=value)
    return attribute


def assert_valid_team_set_response(
    test: TestCase,
    team_set_data: dict,
    students: List[CourseMember],
    total_teams: int,
    min_team_size: int,
    max_team_size: int,
):
    """
    Checks the response of GET /courses/{id}/team-sets/{team_set_id}/: the structure,
    every student in exactly one team, and the number and sizes of the teams.
    """
    test.assertEqual(
        set(team_set_data.keys()), {"id", "name", "teams", "unassigned_students"}
    )
    test.assertEqual(team_set_data["unassigned_students"], [])
    teams = team_set_data["teams"]
    test.assertEqual(len(teams), total_teams)

    assigned_ids = []
    for team in teams:
        test.assertEqual(set(team.keys()), {"id", "slug", "name", "members"})
        test.assertGreaterEqual(len(team["members"]), min_team_size)
        test.assertLessEqual(len(team["members"]), max_team_size)
        for member in team["members"]:
            test.assertEqual(member["role"], UserRole.STUDENT)
            assigned_ids.append(member["id"])
    test.assertCountEqual(assigned_ids, [student.pk for student in students])
