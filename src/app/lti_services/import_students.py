from pylti1p3.names_roles import NamesRolesProvisioningService
from pylti1p3.service_connector import ServiceConnector

from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from lti import lti_util

# platforms send either the full role URI or the short name
LEARNER_ROLES = {"http://purl.imsglobal.org/vocab/lis/v2/membership#Learner", "Learner"}


class NrpsNotAvailable(Exception):
    """The course has no LTI Names and Roles service (yet)."""


def import_students_via_nrps(course: Course):
    """Import the students of a course using the LTI Names and Roles service."""
    if not (course.lms_iss and course.lms_client_id and course.lms_memberships_url):
        raise NrpsNotAvailable(
            "The LMS has not shared a memberships service for this course. Enable "
            "the memberships service for the tool and start it again from the LMS."
        )

    tool_conf = lti_util.get_tool_conf()
    registration = tool_conf.find_registration_by_params(
        course.lms_iss, course.lms_client_id
    )
    nrps = NamesRolesProvisioningService(
        ServiceConnector(registration),
        {"context_memberships_url": course.lms_memberships_url},
    )

    for member in nrps.get_members():
        if not LEARNER_ROLES.intersection(member.get("roles", [])):
            continue
        if member.get("status", "Active") != "Active":
            continue

        CourseMember.objects.update_or_create(
            course=course,
            lms_id=member["user_id"],
            defaults={
                "first_name": member.get("given_name"),
                "last_name": member.get("family_name"),
                "role": UserRole.STUDENT,
            },
        )
