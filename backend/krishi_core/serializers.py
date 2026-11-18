import math

from rest_framework import serializers
from .models import (
    User, Farm, CropPlan, MarketPrice,
    Recommendation, Alert, Expense, Notification,
    WeatherCache, ChatMessage
)


def _finite(value):
    """Reject NaN / Infinity, which pass min/max checks silently."""
    if value is not None and not math.isfinite(value):
        raise serializers.ValidationError("Enter a valid number.")
    return value


class BaseModelSerializer(serializers.ModelSerializer):
    _id = serializers.SerializerMethodField()

    def get__id(self, obj):
        return str(obj.id)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        for field in fields.values():
            if isinstance(field, serializers.FloatField):
                field.validators.append(_finite)
            # A record may only point at the user's own farm / crop plan.
            # Without this, anyone could attach data to another user's farm
            # by guessing its id.
            if (user is not None and user.is_authenticated
                    and isinstance(field, serializers.PrimaryKeyRelatedField)
                    and not field.read_only and field.queryset is not None
                    and any(f.name == "owner" for f in field.queryset.model._meta.fields)):
                field.queryset = field.queryset.filter(owner=user)
                label = field.queryset.model._meta.verbose_name
                field.error_messages["does_not_exist"] = f"No {label} with this id in your account."
        return fields


def _check_json_size(value, limit=20000):
    import json
    if len(json.dumps(value, default=str)) > limit:
        raise serializers.ValidationError("This field is too large.")
    return value


class UserSerializer(BaseModelSerializer):
    firstName = serializers.CharField(source='first_name')
    lastName = serializers.CharField(source='last_name', allow_blank=True, default='')
    # Expose `_id` as string so frontend code that checks `user._id` still works
    _id = serializers.SerializerMethodField()

    def get__id(self, obj):
        return str(obj.id)

    class Meta:
        model = User
        fields = [
            'id', '_id', 'username', 'firstName', 'lastName', 'email', 'phone',
            'role', 'farmingMode', 'language', 'avatarUrl', 'location',
            'isVerified', 'settings', 'date_joined'
        ]

# Limits for farm inputs. Soil values follow the Soil Health Card ranges
# (kg/ha for N, P, K); anything outside is a typo, and it would feed nonsense
# into the crop model. Keep in sync with frontend/src/lib/farmLimits.js.
FARM_LIMITS = {
    "areaAcres": (0.01, 10000),
    "ph": (3, 11),
    "nitrogen": (0, 1000),
    "phosphorus": (0, 300),
    "potassium": (0, 1500),
    "organicCarbon": (0, 10),
    "ec": (0, 20),
}


class FarmSerializer(BaseModelSerializer):
    class Meta:
        model = Farm
        fields = '__all__'
        read_only_fields = ['owner', 'created_at', 'updated_at']
        extra_kwargs = {
            **{name: {"min_value": lo, "max_value": hi} for name, (lo, hi) in FARM_LIMITS.items()},
            "cropHealthIndex": {"min_value": 0, "max_value": 100},
        }

    def validate_waterResources(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or len(value) > 10 \
                or not all(isinstance(v, str) and 0 < len(v.strip()) <= 50 for v in value):
            raise serializers.ValidationError("Choose up to 10 water sources.")
        return [v.strip() for v in value]

    def validate_location(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Location must be an object with an address.")
        address = value.get("address")
        if address is not None and (not isinstance(address, str) or len(address) > 255):
            raise serializers.ValidationError("Address must be text of at most 255 characters.")
        for key, bound in (("lat", 90), ("lon", 180)):
            v = value.get(key)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise serializers.ValidationError(f"{key} must be a number.")
            if not math.isfinite(v) or abs(v) > bound:
                raise serializers.ValidationError(f"{key} is out of range.")
            value[key] = v
        return _check_json_size(value, 5000)

    def validate_riskRadarData(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object.")
        return _check_json_size(value)

class CropPlanSerializer(BaseModelSerializer):
    class Meta:
        model = CropPlan
        fields = '__all__'
        read_only_fields = ['owner', 'created_at', 'updated_at']
        extra_kwargs = {
            "areaAcres": {"min_value": 0.01, "max_value": 10000},
            "seedRateKgPerAcre": {"min_value": 0, "max_value": 1000},
            "rowSpacingCm": {"min_value": 0, "max_value": 1000},
            "estimatedCost": {"min_value": 0},
            "targetYieldKg": {"min_value": 0},
            "seasonProgressPct": {"min_value": 0, "max_value": 100},
        }

    def validate(self, attrs):
        sow = attrs.get("sowingDate", getattr(self.instance, "sowingDate", None))
        harvest = attrs.get("expectedHarvestDate", getattr(self.instance, "expectedHarvestDate", None))
        if sow and harvest and harvest <= sow:
            raise serializers.ValidationError(
                {"expectedHarvestDate": "Harvest date must be after the sowing date."})
        for name in ("irrigationCycles", "fertilizerEvents", "milestones", "tasks"):
            if name in attrs:
                if not isinstance(attrs[name], list):
                    raise serializers.ValidationError({name: "Must be a list."})
                _check_json_size(attrs[name], 200000)
        return attrs

class MarketPriceSerializer(BaseModelSerializer):
    class Meta:
        model = MarketPrice
        fields = '__all__'



class RecommendationSerializer(BaseModelSerializer):
    class Meta:
        model = Recommendation
        fields = '__all__'
        read_only_fields = ['owner', 'generatedAt', 'created_at', 'updated_at']
        extra_kwargs = {"budgetRs": {"min_value": 0}}

    def validate_cropOptions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list.")
        return _check_json_size(value, 200000)

class AlertSerializer(BaseModelSerializer):
    class Meta:
        model = Alert
        fields = '__all__'
        read_only_fields = ['owner', 'created_at', 'updated_at']
        extra_kwargs = {"riskScorePct": {"min_value": 0, "max_value": 100}}

class ExpenseSerializer(BaseModelSerializer):
    class Meta:
        model = Expense
        fields = '__all__'
        read_only_fields = ['owner', 'date', 'created_at', 'updated_at']
        extra_kwargs = {"amountRs": {"min_value": 0.01, "max_value": 100000000}}

    def validate(self, attrs):
        farm = attrs.get("farm", getattr(self.instance, "farm", None))
        plan = attrs.get("cropPlan", getattr(self.instance, "cropPlan", None))
        if plan is not None and farm is not None and plan.farm_id != farm.id:
            raise serializers.ValidationError({"cropPlan": "This crop plan belongs to a different farm."})
        return attrs

class NotificationSerializer(BaseModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ['owner']

class WeatherCacheSerializer(BaseModelSerializer):
    class Meta:
        model = WeatherCache
        fields = '__all__'

class ChatMessageSerializer(BaseModelSerializer):
    class Meta:
        model = ChatMessage
        fields = '__all__'
        read_only_fields = ['owner']
from rest_framework import serializers


class RetrieveRequestSerializer(serializers.Serializer):
    query = serializers.CharField(allow_blank=False)
    n_results = serializers.IntegerField(required=False, default=3, min_value=1, max_value=20)


class SoilRecommendRequestSerializer(serializers.Serializer):
    # Soil test values (Soil Health Card, kg/ha). Optional: when missing, the
    # crop model averages over typical soils instead of using invented numbers.
    ph = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0, max_value=14.0)
    nitrogen = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0)
    phosphorus = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0)
    potassium = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0)
    organicCarbon = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0, max_value=10.0)
    ec = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0.0, max_value=20.0)
    season = serializers.CharField(required=False, default="kharif")
    areaAcres = serializers.FloatField(required=False, default=1.0, min_value=0.01)
    waterAvailability = serializers.CharField(required=False, default="medium")
    temperature = serializers.FloatField(required=False, allow_null=True, default=25.0)
    humidity = serializers.FloatField(required=False, allow_null=True, default=60.0)
    rainfall = serializers.FloatField(required=False, allow_null=True, default=100.0)
    state = serializers.CharField(required=False, allow_null=True, default="Maharashtra")
    soilType = serializers.CharField(required=False, default="Black")
    startPreparationDate = serializers.CharField(required=False, allow_null=True, default="")
    irrigationType = serializers.CharField(required=False, allow_null=True, default="Drip")


class CropStageTipsRequestSerializer(serializers.Serializer):
    crop = serializers.CharField(allow_blank=False)
    stage = serializers.CharField(allow_blank=False)
