"""
Voting views - Active session, cast vote, results
"""
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
import logging

from .models import VotingSession, Option, CitizenHasVoted, Result
from .serializers import VotingSessionSerializer, VotingSessionDetailSerializer, CastVoteSerializer
from authentication.models import Citizen
from authentication.crypto_utils import generate_session_hash

logger = logging.getLogger(__name__)


class VotingSessionListView(APIView):
    """
    List all active voting sessions OR get specific session details.
    Public endpoint - no authentication required.
    
    Query params:
        voting_session_id (optional): If provided, returns details for that specific session
        
    Examples:
        GET /api/voting/sessions/  → Returns all active sessions
        GET /api/voting/sessions/?voting_session_id=1  → Returns details for session #1
    """
    
    def get(self, request):
        """
        Get all active voting sessions OR specific session details.
        """
        try:
            voting_session_id = request.GET.get('voting_session_id')
            
            # Check if user is authenticated (has session)
            citizen_id = request.session.get('citizen_id')
            citizen = None
            
            if citizen_id:
                try:
                    citizen = Citizen.objects.select_related('municipality').get(id=citizen_id)
                    request.citizen = citizen  # Add to request for serializer
                    logger.info(f"Request from authenticated citizen: {citizen.id}")
                except Citizen.DoesNotExist:
                    logger.warning(f"Citizen ID {citizen_id} in session but not found in DB")
            
            # CASE 1: Specific voting session requested
            if voting_session_id:
                try:
                    voting_session = VotingSession.objects.select_related('municipality').prefetch_related(
                        'options'
                    ).get(id=voting_session_id, is_active=True)
                    
                    # Check if voting is open
                    if not voting_session.is_open():
                        return Response({
                            'error': 'Voting is closed',
                            'detail': 'This voting session is not currently open',
                            'start_date': voting_session.start_date,
                            'end_date': voting_session.end_date
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Use DetailSerializer to include has_voted
                    serializer = VotingSessionDetailSerializer(voting_session, context={'request': request})
                    
                    logger.info(f"Voting session details retrieved: {voting_session.id} - {voting_session.title}")
                    
                    return Response(serializer.data)
                    
                except VotingSession.DoesNotExist:
                    return Response({
                        'error': 'Voting session not found',
                        'detail': f'No active voting session with id {voting_session_id}'
                    }, status=status.HTTP_404_NOT_FOUND)
            
            # CASE 2: List all active sessions
            else:
                # Get all active voting sessions with proper prefetching
                voting_sessions = VotingSession.objects.filter(
                    is_active=True
                ).select_related('municipality').prefetch_related('options')
                
                # Only show sessions that are currently open (between start and end date)
                open_sessions = [vs for vs in voting_sessions if vs.is_open()]
                
                if not open_sessions:
                    return Response({
                        'message': 'No active voting sessions',
                        'count': 0,
                        'sessions': []
                    })
                
                # Serialize (use basic serializer for list, not detail)
                serializer = VotingSessionSerializer(open_sessions, many=True)
                
                logger.info(f"Listed {len(open_sessions)} active voting session(s)")
                
                return Response({
                    'count': len(open_sessions),
                    'sessions': serializer.data
                })
            
        except Exception as e:
            logger.error(f"Error retrieving voting sessions: {e}", exc_info=True)
            return Response({
                'error': 'Failed to retrieve voting sessions',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CastVoteView(APIView):
    """
    Cast a vote for a specific option.
    
    Request body:
    - voting_session_id: int
    - option_id: int
    
    Returns:
    - success: boolean
    - message: success/error message
    - timestamp: when vote was cast
    """
    
    def post(self, request):
        """
        Cast a vote with atomic transaction.
        
        This endpoint:
        1. Validates the vote (session open, option valid, no duplicate)
        2. Records WHO voted (CitizenHasVoted)
        3. Records WHAT was voted (Result) - anonymously with random hash
        
        All in an atomic transaction to ensure data consistency.
        """
        try:
            # 1. Check authentication
            citizen_id = request.session.get('citizen_id')
            
            if not citizen_id:
                return Response({
                    'error': 'Authentication required',
                    'detail': 'You must be logged in via SPID to vote'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            try:
                citizen = Citizen.objects.select_related('municipality').get(id=citizen_id)
            except Citizen.DoesNotExist:
                return Response({
                    'error': 'Citizen not found',
                    'detail': 'Your authentication session is invalid'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # 2. Validate input data
            request.citizen = citizen  # Add to request for serializer
            serializer = CastVoteSerializer(data=request.data, context={'request': request})
            
            if not serializer.is_valid():
                return Response({
                    'error': 'Invalid vote data',
                    'detail': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            voting_session_id = serializer.validated_data['voting_session_id']
            option_id = serializer.validated_data['option_id']
            
            # 3. Get voting session and option
            try:
                voting_session = VotingSession.objects.select_related('municipality').get(
                    id=voting_session_id
                )
                option = Option.objects.get(id=option_id)
            except (VotingSession.DoesNotExist, Option.DoesNotExist):
                return Response({
                    'error': 'Invalid vote',
                    'detail': 'Voting session or option not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # 4. Verify citizen is from correct municipality
            if citizen.municipality.id != voting_session.municipality.id:
                logger.warning(
                    f"Citizen {citizen.id} attempted to vote in wrong municipality voting. "
                    f"Citizen municipality: {citizen.municipality.name}, "
                    f"Voting municipality: {voting_session.municipality.name}"
                )
                
                return Response({
                    'error': 'Access denied',
                    'detail': f'This voting is only for residents of {voting_session.municipality.name}'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # 5. Cast vote in atomic transaction
            with transaction.atomic():
                # Check for duplicate vote (with SELECT FOR UPDATE to prevent race conditions)
                has_voted = CitizenHasVoted.objects.select_for_update().filter(
                    citizen=citizen,
                    voting_session=voting_session
                ).exists()
                
                if has_voted:
                    logger.warning(f"Citizen {citizen.id} attempted to vote twice in session {voting_session_id}")
                    return Response({
                        'error': 'Already voted',
                        'detail': 'You have already voted in this session'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Record WHO voted (with timestamp and IP)
                citizen_vote_record = CitizenHasVoted.objects.create(
                    citizen=citizen,
                    voting_session=voting_session,
                    ip_address=self._get_client_ip(request)
                )
                
                # Record WHAT was voted (anonymous with random session hash)
                result = Result.objects.create(
                    voting_session=voting_session,
                    option=option,
                    session_hash=generate_session_hash()  # Random hash for anonymity
                )
                
                timestamp = citizen_vote_record.timestamp
            
            logger.info(
                f"Vote cast successfully - Citizen: {citizen.id}, "
                f"Voting: {voting_session.title}, "
                f"Municipality: {voting_session.municipality.name}"
            )
            
            return Response({
                'success': True,
                'message': 'Vote recorded successfully',
                'timestamp': timestamp,
                'voting_session_id': voting_session_id,
                'voting_session_title': voting_session.title
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error casting vote: {e}", exc_info=True)
            return Response({
                'error': 'Failed to cast vote',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_client_ip(self, request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class VotingResultsView(APIView):
    """
    Get voting results for a specific session.
    Only available if results are public.
    
    TODO: Implement later - low priority
    
    This will show:
    - Vote counts per option
    - Percentages
    - Total voters
    - Charts/graphs (optional)
    """
    
    def get(self, request, session_id):
        """
        Get results for a voting session.
        
        TODO: Implement later
        """
        return Response({
            'message': 'Voting results endpoint - TODO: implement later',
            'status': 'not_implemented'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)