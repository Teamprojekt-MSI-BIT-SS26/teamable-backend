from rest_framework import serializers

from app.models.attribute import Attribute
from app.services.team_generation import (
    ALGORITHM_TYPES,
    DEFAULT_ALGORITHM_TYPE,
    DEFAULT_MAX_TEAM_SIZE,
    DEFAULT_MIN_TEAM_SIZE,
    TeamGenerationParameters,
)


class GenerateTeamsSerializer(serializers.Serializer):
    """
    Parameters of POST /courses/{id}/generate_teams/. Every field is optional.
    The course is passed as instance.
    """

    algorithm_type = serializers.ChoiceField(
        choices=ALGORITHM_TYPES, default=DEFAULT_ALGORITHM_TYPE
    )
    min_team_size = serializers.IntegerField(min_value=1, default=DEFAULT_MIN_TEAM_SIZE)
    max_team_size = serializers.IntegerField(min_value=1, default=DEFAULT_MAX_TEAM_SIZE)
    total_teams = serializers.IntegerField(min_value=1, required=False)
    attributes = serializers.PrimaryKeyRelatedField(
        queryset=Attribute.objects.all(), many=True, required=False
    )
    # single attribute, as sent by the frontend so far; same as attributes=[attribute]
    attribute = serializers.PrimaryKeyRelatedField(
        queryset=Attribute.objects.all(), required=False
    )
    priorities = serializers.ListField(child=serializers.DictField(), required=False)

    def _validate_course_attribute(self, attribute: Attribute) -> Attribute:
        if attribute.course != self.instance:
            raise serializers.ValidationError("Attribute must belong to the course")
        return attribute

    def validate_attribute(self, value):
        return self._validate_course_attribute(value)

    def validate_attributes(self, value):
        return [self._validate_course_attribute(attribute) for attribute in value]

    def validate(self, attrs):
        if attrs["min_team_size"] > attrs["max_team_size"]:
            raise serializers.ValidationError(
                {"min_team_size": "min_team_size cannot be greater than max_team_size."}
            )
        if "attribute" in attrs and "attributes" in attrs:
            raise serializers.ValidationError(
                "Pass either attribute or attributes, not both."
            )
        if "priorities" in attrs and attrs["algorithm_type"] != "priority":
            raise serializers.ValidationError(
                {
                    "priorities": "priorities can only be used with algorithm_type=priority."
                }
            )
        return attrs

    def to_parameters(self) -> TeamGenerationParameters:
        data = self.validated_data
        attributes = data.get("attributes")  # type: ignore
        if "attribute" in data:  # type: ignore
            attributes = [data["attribute"]]  # type: ignore
        return TeamGenerationParameters(
            algorithm_type=data["algorithm_type"],  # type: ignore
            min_team_size=data["min_team_size"],  # type: ignore
            max_team_size=data["max_team_size"],  # type: ignore
            total_teams=data.get("total_teams"),  # type: ignore
            attributes=attributes,
            priorities=data.get("priorities"),  # type: ignore
        )
