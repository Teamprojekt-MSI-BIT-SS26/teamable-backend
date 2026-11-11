from lti.claims import CLAIM_CONTEXT, LaunchData, LmsLaunch, LtiLaunchError


def parse_moodle_launch(launch_data: LaunchData) -> LmsLaunch:
    # Moodle sends its own ids in the LTI standard claims: "sub" is the Moodle
    # user id and context.id the Moodle course id. NRPS returns the same user
    # id, so students imported from the roster can be matched by lms_id.
    context = launch_data.get(CLAIM_CONTEXT) or {}
    course_id = context.get("id")
    user_id = launch_data.get("sub")

    if not course_id or not user_id:
        raise LtiLaunchError("Missing sub or context.id claim in the Moodle launch")

    return LmsLaunch(
        course_id=str(course_id),
        user_id=str(user_id),
        course_name=context.get("title") or context.get("label"),
        first_name=launch_data.get("given_name"),
        last_name=launch_data.get("family_name"),
    )
