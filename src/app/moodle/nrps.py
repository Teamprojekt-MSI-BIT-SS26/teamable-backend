from pylti1p3.names_roles import NamesRolesProvisioningService
from pylti1p3.service_connector import ServiceConnector

from app.models.course import Course
from lti import lti_util


class NrpsNotAvailable(Exception):
    """The course has no LTI Names and Roles service (yet)."""


def init_nrps(course: Course) -> NamesRolesProvisioningService:
    if not (course.lms_iss and course.lms_client_id and course.lms_memberships_url):
        raise NrpsNotAvailable(
            "The LMS has not shared a memberships service for this course. Enable "
            "the memberships service for the tool and start it again from the LMS."
        )

    tool_conf = lti_util.get_tool_conf()
    if tool_conf is None:
        raise NrpsNotAvailable("LTI is not configured on the server.")

    registration = tool_conf.find_registration_by_params(
        course.lms_iss, course.lms_client_id
    )

    # The access token is requested with the tool's own key (LTI Advantage
    # client credentials), so unlike Canvas no OAuth2 token per user is needed
    return NamesRolesProvisioningService(
        ServiceConnector(registration),
        {"context_memberships_url": course.lms_memberships_url},
    )
