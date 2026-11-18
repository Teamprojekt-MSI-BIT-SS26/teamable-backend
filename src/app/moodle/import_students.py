import os
from urllib.parse import urlsplit, urlunsplit

from pylti1p3.names_roles import NamesRolesProvisioningService
from pylti1p3.service_connector import ServiceConnector

from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from app.models.organization import LMSTypeOptions
from lti import lti_util

# Moodle sends the short name ("Learner"), other platforms the full URN
LEARNER_ROLES = {"Learner", "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"}


def _internal_url(url: str) -> str:
    """Optionally route server-to-server calls through MOODLE_INTERNAL_URL.

    Needed in local Docker setups where the Moodle URL seen by the browser
    (e.g. http://localhost:8000) is not reachable from the backend container.
    """
    internal = os.environ.get("MOODLE_INTERNAL_URL")
    if not internal:
        return url
    target = urlsplit(internal)
    parts = urlsplit(url)
    return urlunsplit((target.scheme, target.netloc, parts.path, parts.query, ""))


def import_students_from_moodle(course: Course):
    """Import the course's students through the LTI NRPS service.

    Requires that a launch has stored the memberships URL on the course.
    """
    if (
        course.organization is None
        or course.organization.lms_type != LMSTypeOptions.MOODLE
    ):
        return
    if not course.lms_memberships_url:
        raise Exception("Course has no NRPS memberships URL; launch from Moodle first")

    tool_conf = lti_util.get_tool_conf()
    registration = tool_conf.find_registration(course.organization.lms_api_url)  # type: ignore
    nrps = NamesRolesProvisioningService(
        ServiceConnector(registration),
        {"context_memberships_url": _internal_url(course.lms_memberships_url)},
    )

    for member in nrps.get_members():
        if not LEARNER_ROLES.intersection(member.get("roles", [])):
            continue
        if member.get("status", "Active") != "Active":
            continue
        CourseMember.upsert_course_member(
            user_id=None,
            first_name=member.get("given_name") or "",
            last_name=member.get("family_name") or "",
            lms_id=member["user_id"],
            sis_user_id=None,
            course_id=course.pk,
            role=UserRole.STUDENT,
        )
