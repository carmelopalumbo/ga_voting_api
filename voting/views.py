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
    List all active voting sessions.
    Public endpoint - no authentication required.
    
    This allows users to see which municipalities have active votings
    and select which one to participate in.
    """
    
    def get(self, request):
        """
        Get list of all active voting sessions across all municipalities.
        
        Returns list of voting sessions with:
        - Basic info (title, dates, type)
        - Municipality details
        - Whether voting is currently open
        
        Example:
            GET /api/voting/sessions/
        """
        try:
            # Get all active voting sessions
            voting_sessions = VotingSession.objects.filter(
                is_active=True
            ).select_related('municipality').prefetch_related('options')
            
            # Only show sessions that are currently open (between start and end date)
            open_sessions = [vs for vs in voting_sessions if vs.is_open()]
            
            if not open_sessions:
                return Response({
                    'message': 'No active voting sessions',
                    'sessions': []
                })
            
            # Serialize
            serializer = VotingSessionSerializer(open_sessions, many=True)
            
            logger.info(f"Listed {len(open_sessions)} active voting session(s)")
            
            return Response({
                'count': len(open_sessions),
                'sessions': serializer.data
            })
            
        except Exception as e:
            logger.error(f"Error listing voting sessions: {e}", exc_info=True)
            return Response({
                'error': 'Failed to retrieve voting sessions',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ActiveVotingSessionView(APIView):
    """
    Get active voting session with options and user's voting status.
    
    Returns:
    - voting_session: active session details with options
    - has_voted: boolean indicating if current user has already voted
    """
    
    def get(self, request, voting_session_id=None):
        """
        Get currently active voting session.
        
        Query params:
            voting_session_id (optional): Specific voting session to retrieve
            
        If voting_session_id is provided, returns that specific session (if active).
        Otherwise, returns any active voting session for the authenticated citizen's municipality.
        """
        try:
            # Check if user is authenticated (has session)
            citizen_id = request.session.get('citizen_id')
            citizen = None
            
            if citizen_id:
                try:
                    citizen = Citizen.objects.select_related('municipality').get(id=citizen_id)
                    logger.info(f"Request from authenticated citizen: {citizen.id}")
                except Citizen.DoesNotExist:
                    logger.warning(f"Citizen ID {citizen_id} in session but not found in DB")
            
            # Get voting session
            if voting_session_id:
                # Specific voting session requested
                try:
                    voting_session = VotingSession.objects.prefetch_related('options').get(
                        id=voting_session_id,
                        is_active=True
                    )
                except VotingSession.DoesNotExist:
                    return Response({
                        'error': 'Voting session not found',
                        'detail': f'No active voting session with id {voting_session_id}'
                    }, status=status.HTTP_404_NOT_FOUND)
            else:
                # Get any active voting session
                # If citizen is authenticated, filter by their municipality
                query = VotingSession.objects.prefetch_related('options').filter(is_active=True)
                
                if citizen:
                    query = query.filter(municipality=citizen.municipality)
                
                voting_session = query.first()
                
                if not voting_session:
                    return Response({
                        'error': 'No active voting sessions',
                        'detail': 'There are currently no active voting sessions'
                    }, status=status.HTTP_404_NOT_FOUND)
            
            # Check if voting is actually open (between start and end dates)
            if not voting_session.is_open():
                return Response({
                    'error': 'Voting is closed',
                    'detail': 'This voting session is not currently open',
                    'start_date': voting_session.start_date,
                    'end_date': voting_session.end_date
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Serialize voting session
            # Pass request in context so serializer can compute has_voted
            if citizen:
                request.citizen = citizen  # Add citizen to request for serializer
            
            serializer = VotingSessionDetailSerializer(voting_session, context={'request': request})
            
            logger.info(f"Active voting session retrieved: {voting_session.id} - {voting_session.title}")
            
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Error retrieving active voting session: {e}", exc_info=True)
            return Response({
                'error': 'Failed to retrieve voting session',
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