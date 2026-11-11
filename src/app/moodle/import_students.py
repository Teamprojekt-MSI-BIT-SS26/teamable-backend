from app.models.course import Course
from app.models.course_member import CourseMember, UserRole
from app.models.organization import LMSTypeOptions
from app.moodle.nrps import init_nrps

# platforms send either the full role URI or the short name
LEARNER_ROLES = {"http://purl.imsglobal.org/vocab/lis/v2/membership#Learner", "Learner"}


def import_students_from_moodle(course: Course):
    if (
        course.organization is None
        or course.organization.lms_type != LMSTypeOptions.MOODLE
    ):
        return

    nrps = init_nrps(course)

    for member in nrps.get_members():
        user_id = member.get("user_id")
        if not user_id:
            continue
        if not LEARNER_ROLES.intersection(member.get("roles", [])):
            continue
        if member.get("status", "Active") != "Active":
            continue

        CourseMember.objects.update_or_create(
            course=course,
            lms_id=user_id,
            defaults={
                "first_name": member.get("given_name"),
                "last_name": member.get("family_name"),
                # Moodle sends the user's ID number (typically the student ID)
                "sis_user_id": member.get("lis_person_sourcedid") or None,
                "role": UserRole.STUDENT,
            },
        )
