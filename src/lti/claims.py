from dataclasses import dataclass
from typing import Any, Mapping

from app.models.organization import LMSTypeOptions

# the launch data as decoded from the LTI message (id_token)
LaunchData = Mapping[str, Any]

CLAIM_ROLES = "https://purl.imsglobal.org/spec/lti/claim/roles"
CLAIM_CUSTOM = "https://purl.imsglobal.org/spec/lti/claim/custom"
CLAIM_CONTEXT = "https://purl.imsglobal.org/spec/lti/claim/context"
CLAIM_TOOL_PLATFORM = "https://purl.imsglobal.org/spec/lti/claim/tool_platform"
CLAIM_NRPS = "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice"


class LtiLaunchError(Exception):
    """The LTI launch is missing data that Teamable needs."""


@dataclass
class LmsLaunch:
    """The data Teamable takes from an LTI launch, independent of the LMS."""

    # ids as the LMS itself knows them (stored as Course.lms_course_id and
    # CourseMember.lms_id), so they can be used with the LMS's own services
    course_id: str
    user_id: str
    course_name: str | None
    first_name: str | None
    last_name: str | None


def get_lms_type(launch_data: LaunchData) -> LMSTypeOptions:
    """Detect the LMS from the tool_platform claim."""
    family = (launch_data.get(CLAIM_TOOL_PLATFORM) or {}).get("product_family_code")
    if family == "moodle":
        return LMSTypeOptions.MOODLE
    # Canvas was the only supported LMS before, so it stays the default
    return LMSTypeOptions.CANVAS
