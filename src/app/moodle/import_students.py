from pprint import pprint

from django.conf import settings
from pylti1p3.names_roles import NamesRolesProvisioningService
from pylti1p3.service_connector import ServiceConnector

from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from app.models.organization import LMSTypeOptions
from lti import lti_util

LTI_LEARNER_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"


def import_students_from_moodle(course: Course):
    if (
        course.organization is None
        or course.organization.lms_type != LMSTypeOptions.MOODLE
    ):
        return

    if not course.lms_memberships_url:
        raise Exception(
            "No NRPS memberships URL stored for this course. Launch Teamable from "
            "the Moodle course once and check that 'IMS LTI Names and Role "
            "Provisioning' is enabled on the external tool"
        )

    tool_conf = lti_util.get_tool_conf()
    if tool_conf is None:
        raise Exception("LTI is not configured")

    # For Moodle, the LTI issuer is the site URL, which is stored in lms_api_url
    registration = tool_conf.find_registration_by_issuer(
        course.organization.lms_api_url
    )

    # The access token is obtained with the tool's own key (LTI Advantage),
    # so no per-user OAuth2 token as with Canvas is needed
    nrps = NamesRolesProvisioningService(
        ServiceConnector(registration),
        {"context_memberships_url": course.lms_memberships_url},
    )
    members = nrps.get_members()

    if settings.DEBUG:
        print("NRPS members:")
        pprint(members)

    for member in members:
        roles = member.get("roles", [])
        is_learner = LTI_LEARNER_ROLE in roles or "Learner" in roles
        if not is_learner or member.get("status", "Active") != "Active":
            continue

        # Looked up per course, unlike CourseMember.upsert_course_member(),
        # which only matches on lms_id and can move members between courses
        CourseMember.objects.update_or_create(
            course=course,
            lms_id=member["user_id"],
            defaults={
                "first_name": member.get("given_name"),
                "last_name": member.get("family_name"),
                "sis_user_id": member.get("lis_person_sourcedid") or None,
                "role": UserRole.STUDENT,
            },
        )
