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
from app.canvas.lti_launch import parse_canvas_launch
from app.models import CourseMember, Course, Organization
from app.models.course_member import UserRole
from app.models.organization import LMSTypeOptions
from app.moodle.lti_launch import parse_moodle_launch
from lti import lti_util
from lti.claims import CLAIM_NRPS, CLAIM_ROLES, get_lms_type
from pprint import pprint
import os


# Maps the claims of each LMS's launch to what Teamable needs
LAUNCH_PARSERS = {
    LMSTypeOptions.CANVAS: parse_canvas_launch,
    LMSTypeOptions.MOODLE: parse_moodle_launch,
}


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
    roles = message_launch_data.get(CLAIM_ROLES, [])

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
    lms_launch = LAUNCH_PARSERS[lms_type](message_launch_data)

    # create/sync user
    auth_user, created = MyUser.objects.get_or_create(
        # Make the username unique to the launch ISS, so different
        # institutions' LMS instances create unique usernames
        username=f"{lms_launch.user_id}+{launch_iss}"
    )
    # names are only sent if the LMS's privacy settings allow it
    auth_user.first_name = lms_launch.first_name or ""
    auth_user.last_name = lms_launch.last_name or ""

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
        lms_course_id=lms_launch.course_id,
        defaults={
            "name": lms_launch.course_name,
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
            "lms_id": lms_launch.user_id,
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
