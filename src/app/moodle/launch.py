import os

from django.contrib.auth import login as auth_login
from django.shortcuts import redirect
from rest_framework.authtoken.models import Token

from accounts.models import MyUser
from app.models import Course, CourseMember, Organization
from app.models.course_member import UserRole
from app.models.organization import LMSTypeOptions

CLAIM_PLATFORM = "https://purl.imsglobal.org/spec/lti/claim/tool_platform"
CLAIM_CONTEXT = "https://purl.imsglobal.org/spec/lti/claim/context"
CLAIM_NRPS = "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice"


def is_moodle_launch(launch_data: dict) -> bool:
    platform = launch_data.get(CLAIM_PLATFORM, {})
    return platform.get("product_family_code", "").lower() == "moodle"


def handle_moodle_launch(request, launch_data: dict, role: UserRole):
    """Create/sync user, course and course member for a Moodle LTI 1.3 launch
    and redirect to the frontend.

    Unlike Canvas there are no custom claims and no OAuth step: the Moodle user
    is identified by the standard `sub` claim and the course by `context.id`.
    """
    iss = launch_data["iss"]
    moodle_user_id = launch_data["sub"]
    context = launch_data.get(CLAIM_CONTEXT, {})
    moodle_course_id = context.get("id")
    if not moodle_course_id:
        raise Exception("Missing context id in Moodle LTI launch")

    auth_user, _ = MyUser.objects.get_or_create(username=f"{moodle_user_id}+{iss}")
    auth_user.first_name = launch_data.get("given_name") or ""
    auth_user.last_name = launch_data.get("family_name") or ""
    auth_user.set_unusable_password()
    auth_user.save()

    auth_user.backend = "django.contrib.auth.backends.ModelBackend"  # type: ignore
    auth_login(request, auth_user)
    auth_token, _ = Token.objects.get_or_create(user=auth_user)

    # The Moodle site's issuer doubles as the organization's lms_api_url
    organization, _ = Organization.objects.get_or_create(
        lms_type=LMSTypeOptions.MOODLE,
        lms_api_url=iss,
        defaults={"name": launch_data.get(CLAIM_PLATFORM, {}).get("name") or iss},
    )

    memberships_url = launch_data.get(CLAIM_NRPS, {}).get("context_memberships_url")
    course, _ = Course.objects.get_or_create(
        organization=organization,
        lms_course_id=moodle_course_id,
        defaults={"name": context.get("label") or context.get("title") or "Moodle"},
    )
    if memberships_url and course.lms_memberships_url != memberships_url:
        course.lms_memberships_url = memberships_url
        course.save()

    course_member, _ = CourseMember.objects.get_or_create(
        user=auth_user,
        course=course,
        defaults={
            "first_name": auth_user.first_name,
            "last_name": auth_user.last_name,
            "lms_id": moodle_user_id,
        },
    )
    course_member.role = role
    course_member.save()

    client_url = os.environ.get("FRONTEND_BASE_URL")
    return redirect(
        f"{client_url}/authenticate?token={auth_token}&path=/course/{course.pk}"
    )
