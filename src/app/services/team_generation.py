"""
Team generation with the Teamable algorithms API (repository "algorithms").

The backend collects the students of a course, their attribute responses and their
relationships, sends them to POST /api/generate/teams/ of the algorithms API and saves
the returned teams as a TeamSet. The interface is documented in docs/team_generation.md.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.db import transaction

from app.models.attribute import Attribute, AttributeResponse, AttributeValueType
from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from app.models.relationship import Relationship, RelationshipType
from app.models.team import Team, TeamSet

ALGORITHM_TYPES = ["priority", "weight", "social", "random"]
DEFAULT_ALGORITHM_TYPE = "priority"
DEFAULT_MIN_TEAM_SIZE = 3
DEFAULT_MAX_TEAM_SIZE = 5
# the backend has no project preferences, but the API requires the value
MAX_PROJECT_PREFERENCES = 0

RELATIONSHIP_VALUES = {
    RelationshipType.FRIEND: "friend",
    RelationshipType.ENEMY: "enemy",
}


class TeamGenerationError(Exception):
    """
    Team generation failed. The message can be shown to the user, status_code is the
    HTTP status the backend answers with.
    """

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class TeamGenerationParameters:
    algorithm_type: str = DEFAULT_ALGORITHM_TYPE
    min_team_size: int = DEFAULT_MIN_TEAM_SIZE
    max_team_size: int = DEFAULT_MAX_TEAM_SIZE
    # None: as few teams as possible, i.e. ceil(number of students / max_team_size)
    total_teams: Optional[int] = None
    # None: all attributes of the course that have options
    attributes: Optional[List[Attribute]] = None
    # only for "priority". None: derived from the course data, see build_default_priorities
    priorities: Optional[List[Dict[str, Any]]] = None


def generate_teams(
    course: Course, parameters: Optional[TeamGenerationParameters] = None
) -> TeamSet:
    """
    Generates teams for all students of the course and saves them as a new TeamSet.

    Raises TeamGenerationError if the input is invalid, the API fails or returns an invalid result.
    """
    parameters = parameters or TeamGenerationParameters()
    students = get_students(course)
    payload = build_payload(course, students, parameters)
    teams = request_teams(payload)
    validate_teams(
        teams,
        students,
        total_teams=payload["team_generation_options"]["total_teams"],
        min_team_size=parameters.min_team_size,
        max_team_size=parameters.max_team_size,
    )
    return save_team_set(course, teams, students, parameters)


def get_students(course: Course) -> List[CourseMember]:
    return list(course.course_members.filter(role=UserRole.STUDENT).order_by("id"))


def get_default_attributes(course: Course) -> List[Attribute]:
    return list(
        course.attributes.exclude(value_type=AttributeValueType.TEAM_TEMPLATE_SLUG)
        .filter(options__isnull=False)
        .distinct()
        .order_by("id")
    )


def get_attribute_values(attribute: Attribute) -> Dict[int, int]:
    """
    Maps the option ids of an attribute to the integer values the algorithms expect.

    Number attributes keep their value if every option is an integer. All other attributes
    are numbered by option, which is enough because the algorithms only compare the values.
    """
    options = list(attribute.options.order_by("id"))
    if attribute.value_type == AttributeValueType.NUMBER:
        try:
            return {option.pk: int(option.value) for option in options}
        except ValueError:
            pass
    return {option.pk: index for index, option in enumerate(options)}


def build_payload(
    course: Course,
    students: List[CourseMember],
    parameters: TeamGenerationParameters,
) -> Dict[str, Any]:
    """
    Builds the request body for POST /api/generate/teams/ of the algorithms API.
    """
    if not students:
        raise TeamGenerationError("The course has no students.", status_code=400)

    attributes = (
        parameters.attributes
        if parameters.attributes is not None
        else get_default_attributes(course)
    )
    attribute_values = {
        attribute.pk: get_attribute_values(attribute) for attribute in attributes
    }

    student_attributes: Dict[int, Dict[str, List[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    responses = AttributeResponse.objects.filter(
        course_member__in=students,
        attribute_option__attribute__in=attributes,
    ).select_related("attribute_option")
    for response in responses:
        option = response.attribute_option
        attribute_id: int = option.attribute_id  # type: ignore
        student_attributes[response.course_member_id][  # type: ignore
            str(attribute_id)
        ].append(attribute_values[attribute_id][option.pk])

    student_relationships: Dict[int, Dict[str, str]] = defaultdict(dict)
    relationships = Relationship.objects.filter(
        from_member__in=students, to_member__in=students
    )
    for relationship in relationships:
        from_id: int = relationship.from_member_id  # type: ignore
        to_id: int = relationship.to_member_id  # type: ignore
        if from_id != to_id:
            student_relationships[from_id][str(to_id)] = RELATIONSHIP_VALUES[
                RelationshipType(relationship.type)
            ]

    students_data = []
    for student in students:
        student_data: Dict[str, Any] = {
            "id": student.pk,
            "attributes": {
                attribute_id: sorted(values)
                for attribute_id, values in student_attributes[student.pk].items()
            },
            "relationships": student_relationships[student.pk],
        }
        name = " ".join(filter(None, [student.first_name, student.last_name]))
        if name:
            student_data["name"] = name
        students_data.append(student_data)

    total_teams = parameters.total_teams or math.ceil(
        len(students) / parameters.max_team_size
    )

    return {
        "algorithm_options": build_algorithm_options(
            parameters,
            attribute_ids=list(attribute_values.keys()),
            relationships=dict(student_relationships),
        ),
        "students": students_data,
        "team_generation_options": {
            "initial_teams": [],
            "max_team_size": parameters.max_team_size,
            "min_team_size": parameters.min_team_size,
            "total_teams": total_teams,
        },
    }


def build_algorithm_options(
    parameters: TeamGenerationParameters,
    attribute_ids: List[int],
    relationships: Dict[int, Dict[str, str]],
) -> Dict[str, Any]:
    if parameters.algorithm_type == "random":
        return {"algorithm_type": "random"}

    # weight, social and priority share these options. The priority algorithm uses them
    # for its starting team set, which it then improves according to its priorities.
    options: Dict[str, Any] = {
        "algorithm_type": parameters.algorithm_type,
        "max_project_preferences": MAX_PROJECT_PREFERENCES,
        "attributes_to_diversify": attribute_ids,
        "diversity_weight": 1 if attribute_ids else 0,
        "social_weight": 1 if relationships else 0,
    }
    if parameters.algorithm_type == "priority":
        options["priorities"] = (
            parameters.priorities
            if parameters.priorities is not None
            else build_default_priorities(attribute_ids, relationships)
        )
    return options


def build_default_priorities(
    attribute_ids: List[int], relationships: Dict[int, Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    Default priorities of the priority algorithm, most important first:
    1. friends together, enemies apart (if there are relationships)
    2. diverse teams, one priority per attribute
    """
    priorities: List[Dict[str, Any]] = []
    if relationships:
        max_num_friends = max(
            list(relations.values()).count("friend")
            for relations in relationships.values()
        )
        max_num_enemies = max(
            list(relations.values()).count("enemy")
            for relations in relationships.values()
        )
        priorities.append(
            {
                "priority_type": "social_preference",
                # at least 1, the satisfaction is normalized by these values
                "max_num_friends": max(max_num_friends, 1),
                "max_num_enemies": max(max_num_enemies, 1),
            }
        )
    for attribute_id in attribute_ids:
        priorities.append(
            {
                "priority_type": "diversity",
                "attribute_id": attribute_id,
                "strategy": "diversify",
            }
        )
    return priorities


def request_teams(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Sends the payload to the algorithms API and returns the generated teams.
    """
    url = settings.TEAM_GENERATION_API_URL
    api_key = settings.TEAM_GENERATION_API_KEY
    if not url or not api_key:
        raise TeamGenerationError(
            "Team generation is not configured. Set TEAM_GENERATION_API_URL and TEAM_GENERATION_API_KEY.",
            status_code=503,
        )

    timeout = settings.TEAM_GENERATION_API_TIMEOUT
    try:
        response = requests.post(
            url, json=payload, headers={"X-Api-Key": api_key}, timeout=timeout
        )
    except requests.Timeout:
        raise TeamGenerationError(
            f"The team generation API did not answer within {timeout} seconds.",
            status_code=504,
        )
    except requests.RequestException as e:
        raise TeamGenerationError(
            f"The team generation API at {url} could not be reached: {e}",
            status_code=502,
        )

    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else response.text

    if response.status_code == 400 and isinstance(body, dict):
        # the algorithms API rejected the students or options, e.g. team sizes that do not fit
        raise TeamGenerationError(f"Invalid team generation input: {error}", 400)
    if response.status_code in (400, 401):
        # the authentication of the algorithms API answers with plain text
        raise TeamGenerationError(
            f"The team generation API rejected the API key: {error}", 502
        )
    if response.status_code != 200 or not isinstance(body, dict) or error:
        raise TeamGenerationError(
            f"The team generation API failed with status {response.status_code}: {error}",
            502,
        )

    try:
        return body["teams"]["teams"]
    except (KeyError, TypeError):
        raise TeamGenerationError(
            "The team generation API returned an unexpected response.", 502
        )


def validate_teams(
    teams: List[Dict[str, Any]],
    students: List[CourseMember],
    total_teams: int,
    min_team_size: int,
    max_team_size: int,
):
    """
    Checks that the result is a valid team set for the requested parameters:
    every student is in exactly one team, and the number and sizes of the teams match.
    """
    if len(teams) != total_teams:
        raise TeamGenerationError(
            f"Expected {total_teams} teams, but the API returned {len(teams)}."
        )

    assigned_ids = [student["id"] for team in teams for student in team["students"]]
    student_ids = {student.pk for student in students}
    duplicates = {i for i in assigned_ids if assigned_ids.count(i) > 1}
    unknown = set(assigned_ids) - student_ids
    missing = student_ids - set(assigned_ids)
    if duplicates or unknown or missing:
        raise TeamGenerationError(
            "The API returned an invalid team set "
            f"(duplicate: {sorted(duplicates)}, unknown: {sorted(unknown)}, unassigned: {sorted(missing)})."
        )

    for team in teams:
        size = len(team["students"])
        if not min_team_size <= size <= max_team_size:
            raise TeamGenerationError(
                f"Team {team.get('name') or team.get('id')} has {size} students, "
                f"expected {min_team_size} to {max_team_size}."
            )


@transaction.atomic
def save_team_set(
    course: Course,
    teams: List[Dict[str, Any]],
    students: List[CourseMember],
    parameters: TeamGenerationParameters,
) -> TeamSet:
    students_by_id = {student.pk: student for student in students}
    team_set = TeamSet.objects.create(
        course=course,
        name=f"Team Set {course.team_sets.count() + 1} ({parameters.algorithm_type})",
    )
    for index, team_data in enumerate(teams, start=1):
        team = Team.objects.create(
            slug=uuid.uuid4(),
            name=team_data.get("name") or f"Team {index}",
            max_people=parameters.max_team_size,
            min_people=parameters.min_team_size,
            team_set=team_set,
        )
        team.members.add(
            *[students_by_id[student["id"]] for student in team_data["students"]]
        )
    return team_set
