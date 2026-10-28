from django.urls import reverse
from pylti1p3.contrib.django.oidc_login import DjangoOIDCLogin
from pylti1p3.contrib.django.message_launch import DjangoMessageLaunch
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import logout as auth_logout, login as auth_login
from django.shortcuts import redirect
from django.conf import settings
from rest_framework.authtoken.models import Token

from accounts.models import MyUser
from app.models import CourseMember, Course, Organization
from app.models.course_member import UserRole
from app.models.organization import LMSTypeOptions
from lti import lti_util
from pprint import pprint
import os


CLAIM_CUSTOM = "https://purl.imsglobal.org/spec/lti/claim/custom"
CLAIM_CONTEXT = "https://purl.imsglobal.org/spec/lti/claim/context"
CLAIM_TOOL_PLATFORM = "https://purl.imsglobal.org/spec/lti/claim/tool_platform"
CLAIM_NRPS = "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice"


def get_lms_type(launch_data: dict) -> str:
    """Detect the LMS from the platform claim, falling back to Canvas."""
    family = (launch_data.get(CLAIM_TOOL_PLATFORM) or {}).get("product_family_code")
    if family == "moodle":
        return LMSTypeOptions.MOODLE
    return LMSTypeOptions.CANVAS


def get_lms_ids(launch_data: dict) -> tuple[str | None, str | None]:
    """
    Returns (course id, user id) as the LMS knows them.
    Canvas ids come from custom fields (see
    https://gist.github.com/jbasdf/15fb8abed66fbaf623cdfbdd45bfb1c4), other
    platforms use the standard LTI claims.
    """
    custom = launch_data.get(CLAIM_CUSTOM) or {}
    course_id = custom.get("canvas_course_id") or (
        launch_data.get(CLAIM_CONTEXT) or {}
    ).get("id")
    user_id = custom.get("canvas_user_id") or launch_data.get("sub")
    return course_id, user_id


@csrf_exempt
def login(request):
    if not settings.LTI_ENABLED:
        raise Exception("LTI disabled")

    # clear old sessions (just to be safe)
    auth_logout(request)

    tool_conf = lti_util.get_tool_conf()
    oidc_login = DjangoOIDCLogin(request, tool_conf)

    target_link_uri = request.POST.get(
        "target_link_uri", request.GET.get("target_link_uri")
    )
    if not target_link_uri:
        raise Exception('Missing "target_link_uri" param')

    return oidc_login.redirect(target_link_uri)


class ExtendedDjangoMessageLaunch(DjangoMessageLaunch):
    def validate_deployment(self):
        if settings.DEBUG:
            return self
        return super().validate_deployment()


@csrf_exempt
@require_POST
def launch(request):
    if not settings.LTI_ENABLED:
        raise Exception("LTI disabled")

    tool_conf = lti_util.get_tool_conf()
    message_launch = ExtendedDjangoMessageLaunch(request, tool_conf)

    message_launch_data = message_launch.get_launch_data()

    # check if instructor
    roles = message_launch_data.get(
        "https://purl.imsglobal.org/spec/lti/claim/roles", []
    )

    has_admin_role = (
        "http://purl.imsglobal.org/vocab/lis/v2/membership#Administrator" in roles
    )
    has_content_developer_role = (
        "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper" in roles
    )
    has_instructor_role = (
        "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor" in roles
    )
    has_ta_role = (
        "http://purl.imsglobal.org/vocab/lis/v2/membership/Instructor#TeachingAssistant"
        in roles
    )

    role = UserRole.STUDENT
    if has_admin_role:
        role = UserRole.INSTRUCTOR
    elif has_content_developer_role:
        role = UserRole.INSTRUCTOR
    elif has_instructor_role and not has_ta_role:
        role = UserRole.INSTRUCTOR
    elif has_ta_role:
        role = UserRole.INSTRUCTOR

    if settings.DEBUG:
        pprint(message_launch_data)

    launch_iss = message_launch_data.get("iss")

    lms_type = get_lms_type(message_launch_data)
    lms_course_id, lms_user_id = get_lms_ids(message_launch_data)

    if not lms_course_id or not lms_user_id:
        raise Exception(
            "Missing course/user id in the LTI launch. For Canvas, check that the "
            "custom_fields block is configured on the developer key"
        )

    # create/sync user
    auth_user, created = MyUser.objects.get_or_create(
        # Make the username unique to the launch ISS, so different
        # institution's Canvas instance creates unique usernames
        username=f"{lms_user_id}+{launch_iss}"
    )
    auth_user.first_name = message_launch_data.get("given_name")
    auth_user.last_name = message_launch_data.get("family_name")

    auth_user.set_unusable_password()
    auth_user.save()

    auth_user.backend = "django.contrib.auth.backends.ModelBackend"  # type: ignore
    auth_login(request, auth_user)

    # make the authentication token for the frontend
    auth_token, _ = Token.objects.get_or_create(user=auth_user)

    # todo: this does not distinguish multiple organizations of the same LMS type
    organization = (
        Organization.objects.filter(lms_type=lms_type).first()
        or Organization.objects.first()
    )

    course, created = Course.objects.get_or_create(
        lms_course_id=lms_course_id,
        defaults={
            "name": message_launch_data.get(
                "https://purl.imsglobal.org/spec/lti/claim/context", {}
            ).get("label"),
            "organization": organization,
        },
    )

    # remember how to reach the LTI Advantage services (Names and Roles) for this course
    memberships_url = (message_launch_data.get(CLAIM_NRPS) or {}).get(
        "context_memberships_url"
    )
    if memberships_url:
        course.lms_iss = launch_iss
        course.lms_client_id = message_launch.get_client_id()
        course.lms_memberships_url = memberships_url
        course.save()

    course_member, created = CourseMember.objects.get_or_create(
        user=auth_user,
        course=course,
        defaults={
            "first_name": auth_user.first_name,
            "last_name": auth_user.last_name,
            "lms_id": lms_user_id,
        },
    )
    course_member.role = role
    course_member.save()

    if lms_type == LMSTypeOptions.CANVAS:
        # Canvas API access needs an OAuth2 token on top of the LTI login
        return redirect(
            f"{reverse('canvas-oauth-initiate')}?redirect_path=/course/{course.pk}"
        )

    client_url = os.environ.get("FRONTEND_BASE_URL")
    return redirect(
        f"{client_url}/authenticate?token={auth_token}&path=/course/{course.pk}"
    )
