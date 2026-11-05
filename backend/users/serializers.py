#backend/users/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from voice.access import is_voice_team_manager

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source='public_id', read_only=True)
    platform_role = serializers.CharField(read_only=True)
    is_creator = serializers.BooleanField(read_only=True)
    has_supervisor_access_for_voice_agent = serializers.BooleanField(read_only=True)
    is_voice_team_manager = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'name', 'platform_role', 'is_creator',
            'has_supervisor_access_for_voice_agent', 'is_voice_team_manager',
            'chunk_size', 'overlap_size'
        )
        read_only_fields = ('id', 'email', 'platform_role', 'is_creator', 'has_supervisor_access_for_voice_agent', 'is_voice_team_manager')

    def get_is_voice_team_manager(self, obj) -> bool:
        return is_voice_team_manager(obj)

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    id = serializers.UUIDField(source='public_id', read_only=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'password2', 'email', 'first_name', 'last_name')

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user

class UserInfoSerializer(serializers.ModelSerializer):
    """
    Serializer for user info endpoint that returns SocraticBots user data
    with external_user_id for DARE synchronization.
    """
    platform = serializers.SerializerMethodField()
    platform_role = serializers.CharField(read_only=True)
    is_creator = serializers.BooleanField(read_only=True)
    has_supervisor_access_for_voice_agent = serializers.BooleanField(read_only=True)
    is_voice_team_manager = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'name', 'platform_role', 'is_creator',
            'has_supervisor_access_for_voice_agent', 'is_voice_team_manager',
            'external_user_id',
            'is_active', 'date_joined', 'platform',
            'chunk_size', 'overlap_size'
        )
        read_only_fields = fields

    def get_platform(self, obj):
        return 'SocraticBots'

    def get_is_voice_team_manager(self, obj) -> bool:
        return is_voice_team_manager(obj)
