"""
Django REST Framework serializers for voting app.

These serializers handle JSON serialization/deserialization for:
- Voting sessions
- Options
- Vote casting
- Results
"""

from rest_framework import serializers
from .models import VotingSession, Option, CitizenHasVoted, Result
from authentication.models import Municipality


class MunicipalitySerializer(serializers.ModelSerializer):
    """
    Minimal serializer for Municipality (used in nested serialization).
    """
    class Meta:
        model = Municipality
        fields = ['id', 'name', 'cap']


class OptionSerializer(serializers.ModelSerializer):
    """
    Serializer for voting options.
    Used to display available choices in a voting session.
    """
    vote_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Option
        fields = [
            'id',
            'text',
            'display_order',
            'image_url',
            'vote_count'
        ]
    
    def get_vote_count(self, obj):
        """
        Return vote count only if results are public.
        Otherwise return None to preserve anonymity during voting.
        """
        # Check if voting_session is available
        if not hasattr(obj, 'voting_session') or not obj.voting_session:
            return None
        
        voting_session = obj.voting_session
        
        # Only show results if:
        # 1. Results are marked as public
        # 2. OR voting session has ended
        if voting_session.results_public or not voting_session.is_open():
            return obj.get_vote_count()
        
        return None


class VotingSessionSerializer(serializers.ModelSerializer):
    """
    Serializer for voting sessions.
    Includes nested options and municipality info.
    """
    municipality = MunicipalitySerializer(read_only=True)
    options = OptionSerializer(many=True, read_only=True)
    is_open = serializers.SerializerMethodField()
    total_voters = serializers.SerializerMethodField()
    
    class Meta:
        model = VotingSession
        fields = [
            'id',
            'municipality',
            'title',
            'description',
            'type',
            'start_date',
            'end_date',
            'is_active',
            'is_open',
            'results_public',
            'options',
            'total_voters',
            'created_at'
        ]
    
    def get_is_open(self, obj):
        """Check if voting is currently open."""
        return obj.is_open()
    
    def get_total_voters(self, obj):
        """
        Return total number of people who voted.
        Only shown if results are public.
        """
        if obj.results_public or not obj.is_open():
            return obj.voters.count()
        return None


class VotingSessionDetailSerializer(VotingSessionSerializer):
    """
    Detailed serializer for a single voting session.
    Adds user-specific information like "has_voted".
    """
    has_voted = serializers.SerializerMethodField()
    
    class Meta(VotingSessionSerializer.Meta):
        fields = VotingSessionSerializer.Meta.fields + ['has_voted']
    
    def get_has_voted(self, obj):
        """
        Check if the current user has already voted in this session.
        Requires 'request' in context with authenticated citizen.
        """
        request = self.context.get('request')
        
        if not request or not hasattr(request, 'citizen'):
            return None
        
        citizen = request.citizen
        
        return CitizenHasVoted.objects.filter(
            citizen=citizen,
            voting_session=obj
        ).exists()


class CastVoteSerializer(serializers.Serializer):
    """
    Serializer for casting a vote.
    Validates input and handles vote submission.
    """
    voting_session_id = serializers.IntegerField()
    option_id = serializers.IntegerField()
    
    def validate_voting_session_id(self, value):
        """Validate that voting session exists and is active."""
        try:
            voting_session = VotingSession.objects.get(id=value)
        except VotingSession.DoesNotExist:
            raise serializers.ValidationError("Voting session not found.")
        
        if not voting_session.is_active:
            raise serializers.ValidationError("Voting session is not active.")
        
        if not voting_session.is_open():
            raise serializers.ValidationError("Voting is closed.")
        
        return value
    
    def validate_option_id(self, value):
        """Validate that option exists."""
        if not Option.objects.filter(id=value).exists():
            raise serializers.ValidationError("Option not found.")
        
        return value
    
    def validate(self, data):
        """
        Cross-field validation:
        - Option must belong to the voting session
        - Citizen must not have already voted
        """
        voting_session_id = data.get('voting_session_id')
        option_id = data.get('option_id')
        
        # Check option belongs to voting session
        try:
            option = Option.objects.get(id=option_id)
            if option.voting_session_id != voting_session_id:
                raise serializers.ValidationError({
                    'option_id': 'Option does not belong to this voting session.'
                })
        except Option.DoesNotExist:
            raise serializers.ValidationError({
                'option_id': 'Option not found.'
            })
        
        # Check if citizen has already voted
        request = self.context.get('request')
        if request and hasattr(request, 'citizen'):
            citizen = request.citizen
            voting_session = VotingSession.objects.get(id=voting_session_id)
            
            if CitizenHasVoted.objects.filter(
                citizen=citizen,
                voting_session=voting_session
            ).exists():
                raise serializers.ValidationError({
                    'non_field_errors': ['You have already voted in this session.']
                })
        
        return data


class VoteResponseSerializer(serializers.Serializer):
    """
    Serializer for vote response.
    Returns confirmation after successful vote.
    """
    success = serializers.BooleanField()
    message = serializers.CharField()
    timestamp = serializers.DateTimeField()
    voting_session_id = serializers.IntegerField()


class VotingResultSerializer(serializers.Serializer):
    """
    Serializer for voting results.
    Shows vote counts and percentages for each option.
    """
    voting_session = VotingSessionSerializer(read_only=True)
    results = serializers.SerializerMethodField()
    total_votes = serializers.SerializerMethodField()
    total_voters = serializers.SerializerMethodField()
    
    def get_results(self, obj):
        """
        Get results for each option with vote count and percentage.
        """
        options = obj.options.all()
        total_votes = Result.objects.filter(voting_session=obj).count()
        
        results = []
        for option in options:
            vote_count = option.get_vote_count()
            percentage = (vote_count / total_votes * 100) if total_votes > 0 else 0
            
            results.append({
                'option_id': option.id,
                'option_text': option.text,
                'vote_count': vote_count,
                'percentage': round(percentage, 2)
            })
        
        # Sort by vote_count descending
        results.sort(key=lambda x: x['vote_count'], reverse=True)
        
        return results
    
    def get_total_votes(self, obj):
        """Total number of votes cast (anonymous)."""
        return Result.objects.filter(voting_session=obj).count()
    
    def get_total_voters(self, obj):
        """Total number of citizens who voted."""
        return CitizenHasVoted.objects.filter(voting_session=obj).count()