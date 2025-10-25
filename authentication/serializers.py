"""
Django REST Framework serializers for authentication app.

These serializers handle JSON serialization for:
- Citizen (minimal, privacy-focused)
- Municipality
"""

from rest_framework import serializers
from .models import Municipality, Citizen
from .crypto_utils import decrypt_citizen_data


class MunicipalitySerializer(serializers.ModelSerializer):
    """
    Serializer for Municipality model.
    """
    class Meta:
        model = Municipality
        fields = [
            'id',
            'name',
            'ipa_code',
            'cap'
        ]


class CitizenMinimalSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for Citizen.
    IMPORTANT: Does NOT expose personal data (encrypted fields).
    Only shows ID and municipality.
    Used for API responses where we need to reference a citizen.
    """
    municipality = MunicipalitySerializer(read_only=True)
    
    class Meta:
        model = Citizen
        fields = [
            'id',
            'municipality',
            'is_active',
            'registration_date'
        ]


class CitizenDecryptedSerializer(serializers.Serializer):
    """
    Serializer for decrypted citizen data.
    WARNING: Use ONLY in secure contexts (admin, internal operations).
    NEVER expose this via public API!
    """
    id = serializers.IntegerField()
    fiscal_code = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    municipality = MunicipalitySerializer()
    registration_date = serializers.DateTimeField()
    is_active = serializers.BooleanField()
    
    @staticmethod
    def from_citizen(citizen):
        """
        Create serialized data from Citizen instance.
        Decrypts personal data.
        
        Args:
            citizen: Citizen model instance
            
        Returns:
            dict: Decrypted citizen data
            
        Example:
            >>> data = CitizenDecryptedSerializer.from_citizen(citizen)
            >>> print(data['fiscal_code'])
            'RSSMRA80A01H501Z'
        """
        decrypted = decrypt_citizen_data(citizen)
        
        return {
            'id': citizen.id,
            'fiscal_code': decrypted['fiscal_code'],
            'first_name': decrypted['first_name'],
            'last_name': decrypted['last_name'],
            'email': decrypted['email'],
            'municipality': MunicipalitySerializer(citizen.municipality).data,
            'registration_date': citizen.registration_date,
            'is_active': citizen.is_active
        }


class SPIDCallbackResponseSerializer(serializers.Serializer):
    """
    Serializer for SPID callback response.
    Returns after successful SPID authentication.
    """
    success = serializers.BooleanField()
    message = serializers.CharField()
    citizen_id = serializers.IntegerField()
    redirect_url = serializers.CharField()
    session_token = serializers.CharField(required=False)