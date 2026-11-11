from lti.claims import (
    CLAIM_CONTEXT,
    CLAIM_CUSTOM,
    LaunchData,
    LmsLaunch,
    LtiLaunchError,
)


def parse_canvas_launch(launch_data: LaunchData) -> LmsLaunch:
    # Canvas's standard "sub" and context.id claims are opaque LTI ids, not the
    # Canvas ids that the Canvas REST API needs. The Canvas ids come from custom
    # fields, which need to be defined on the Canvas developer key, see
    #   https://gist.github.com/jbasdf/15fb8abed66fbaf623cdfbdd45bfb1c4
    custom = launch_data.get(CLAIM_CUSTOM) or {}
    course_id = custom.get("canvas_course_id")
    user_id = custom.get("canvas_user_id")

    if not course_id or not user_id:
        raise LtiLaunchError(
            "Missing canvas_course_id/canvas_user_id custom claims. Check that "
            "the custom_fields block is configured on the Canvas developer key"
        )

    return LmsLaunch(
        course_id=str(course_id),
        user_id=str(user_id),
        course_name=(launch_data.get(CLAIM_CONTEXT) or {}).get("label"),
        first_name=launch_data.get("given_name"),
        last_name=launch_data.get("family_name"),
    )
