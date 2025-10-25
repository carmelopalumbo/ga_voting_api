"""
Authentication views - SPID login and callback
"""
from django.http import JsonResponse
from django.views import View
from django.conf import settings
from urllib.parse import urlencode
import secrets
import logging
import json
import base64
import time

logger = logging.getLogger(__name__)


class SPIDLoginView(View):
    """
    Endpoint to initiate SPID login flow.
    Generates SPID URL with voting_session_id encoded in state parameter.
    Frontend will redirect user to this URL.
    """
    
    def get(self, request):
        """
        Generate SPID authentication URL.
        
        Query params:
            voting_session_id (required): ID of the voting session
        
        Returns:
            JSON with SPID URL for redirect
            
        Example request:
            GET /api/auth/spid/login/?voting_session_id=123
            
        Example response:
            {
                "spid_url": "https://idppatest.b2clogin.com/...?state=eyJ2b3Rpbmc...",
            }
        """
        try:
            # Get voting_session_id from query params
            voting_session_id = request.GET.get('voting_session_id')
            
            if not voting_session_id:
                return JsonResponse({
                    'error': 'voting_session_id is required',
                    'detail': 'Please provide voting_session_id in query parameters'
                }, status=400)
            
            # Validate voting session exists
            from voting.models import VotingSession
            try:
                voting_session = VotingSession.objects.get(id=voting_session_id)
            except VotingSession.DoesNotExist:
                return JsonResponse({
                    'error': 'Voting session not found',
                    'detail': f'No voting session with id {voting_session_id}'
                }, status=404)
            
            # Check if voting is open
            if not voting_session.is_open():
                return JsonResponse({
                    'error': 'Voting is closed',
                    'detail': 'This voting session is not currently open'
                }, status=400)
            
            # Generate random nonce for security
            nonce = secrets.token_urlsafe(32)
            
            # Create state payload with voting_session_id
            state_payload = {
                'voting_session_id': int(voting_session_id),
                'timestamp': int(time.time()),
                'nonce': secrets.token_urlsafe(16)  # Additional randomness
            }
            
            # Encode state as base64
            state = base64.urlsafe_b64encode(
                json.dumps(state_payload).encode()
            ).decode()
            
            # Build SPID URL
            base_url = (
                f"https://{settings.SPID_TENANT}.b2clogin.com/"
                f"{settings.SPID_TENANT}.onmicrosoft.com/"
                f"{settings.SPID_POLICY}/oauth2/v2.0/authorize"
            )
            
            params = {
                'client_id': settings.SPID_CLIENT_ID,
                'response_type': 'id_token',
                'redirect_uri': settings.SPID_REDIRECT_URI,
                'response_mode': 'form_post',
                'scope': 'openid',
                'nonce': nonce,
                'state': state,  # ← Contains voting_session_id!
                'codiceIpa': voting_session.municipality.ipa_code,  # ← IPA from voting!
            }
            
            spid_url = f"{base_url}?{urlencode(params)}"
            
            logger.info(
                f"SPID login initiated - voting_session: {voting_session_id}, "
                f"municipality: {voting_session.municipality.name}"
            )
            
            return JsonResponse({
                'spid_url': spid_url,
            })
            
        except Exception as e:
            logger.error(f"Error generating SPID URL: {e}", exc_info=True)
            return JsonResponse({
                'error': 'Failed to generate SPID login URL',
                'detail': str(e)
            }, status=500)


class SPIDCallbackView(View):
    """
    Callback endpoint after SPID authentication.
    Validates JWT token, decodes state to get voting_session_id,
    verifies citizen residence, creates/updates citizen.
    """
    
    def post(self, request):
        """
        Handle SPID callback with JWT token.
        
        Flow:
        1. Extract JWT token and state from request
        2. Decode state to get voting_session_id
        3. Get voting session and municipality
        4. Verify JWT signature with OIDC
        5. Extract user data (fiscal code, name, etc.)
        6. Verify citizen residence matches municipality
        7. Create or update Citizen in database
        8. Create Django session
        9. Redirect to frontend with success
        """
        try:
            from .oidc_utils import extract_token_from_callback, decode_spid_token
            from .crypto_utils import hash_fiscal_code, encrypt_citizen_data
            from .models import Citizen
            from voting.models import VotingSession
            
            logger.info("SPID callback received")
            
            # 1. Extract state parameter
            state = request.POST.get('state') or request.GET.get('state')
            
            if not state:
                logger.error("State parameter missing from callback")
                return JsonResponse({
                    'error': 'Invalid callback',
                    'detail': 'State parameter is required'
                }, status=400)
            
            # 2. Decode state to get voting_session_id
            try:
                state_decoded = base64.urlsafe_b64decode(state).decode()
                state_payload = json.loads(state_decoded)
                voting_session_id = state_payload.get('voting_session_id')
                
                if not voting_session_id:
                    raise ValueError("voting_session_id not in state")
                    
                logger.info(f"State decoded - voting_session_id: {voting_session_id}")
                
            except Exception as e:
                logger.error(f"Failed to decode state: {e}")
                return JsonResponse({
                    'error': 'Invalid state parameter',
                    'detail': 'Could not decode state'
                }, status=400)
            
            # 3. Get voting session and municipality
            try:
                voting_session = VotingSession.objects.select_related('municipality').get(
                    id=voting_session_id
                )
                municipality = voting_session.municipality
                ipa_code = municipality.ipa_code
                
                logger.info(f"Voting session found: {voting_session.title} - {municipality.name}")
                
            except VotingSession.DoesNotExist:
                logger.error(f"Voting session {voting_session_id} not found")
                return JsonResponse({
                    'error': 'Voting session not found',
                    'detail': f'No voting session with id {voting_session_id}'
                }, status=404)
            
            # 4. Extract JWT token
            token = extract_token_from_callback(request)
            
            # 5. Verify and decode JWT
            logger.info("Verifying JWT signature...")
            user_data = decode_spid_token(token)
            
            fiscal_code = user_data['fiscal_code']
            logger.info(f"JWT verified - fiscal code: {fiscal_code[:4]}****")
            
            # 6. Find or create citizen AND verify municipality
            fiscal_code_hash = hash_fiscal_code(fiscal_code)
            citizen = Citizen.objects.filter(fiscal_code_hash=fiscal_code_hash).first()
            
            if citizen:
                # Existing citizen - VERIFY they belong to the correct municipality
                if citizen.municipality.ipa_code != ipa_code:
                    logger.warning(
                        f"Citizen {citizen.id} attempted to vote in wrong municipality. "
                        f"Registered: {citizen.municipality.name} ({citizen.municipality.ipa_code}), "
                        f"Voting: {municipality.name} ({ipa_code})"
                    )
                    
                    return JsonResponse({
                        'error': 'Access denied',
                        'detail': 'Municipality mismatch',
                        'message': (
                            f'This voting is only for residents of {municipality.name}. '
                            f'You are registered in {citizen.municipality.name}.'
                        )
                    }, status=403)
                
                # Municipality verified - update last access
                citizen.save(update_fields=['last_access'])
                logger.info(f"Existing citizen verified: ID {citizen.id}, Municipality: {municipality.name}")
                created = False
                
            else:
                # New citizen - create and associate with THIS municipality
                logger.info(f"Creating new citizen for municipality: {municipality.name}")
                
                encrypted_data = encrypt_citizen_data(
                    fiscal_code=fiscal_code,
                    first_name=user_data.get('first_name', ''),
                    last_name=user_data.get('last_name', ''),
                    email=user_data.get('email')
                )
                
                citizen = Citizen.objects.create(
                    municipality=municipality,
                    **encrypted_data
                )
                
                logger.info(f"New citizen created: ID {citizen.id} for {municipality.name}")
                created = True
            
            # 7. Create session (store citizen ID, municipality, and voting session)
            request.session['citizen_id'] = citizen.id
            request.session['municipality_id'] = municipality.id
            request.session['voting_session_id'] = voting_session_id
            request.session['authenticated_via'] = 'SPID'
            request.session.save()
                
            # 8. Redirect to frontend
            frontend_url = settings.FRONTEND_URL
            # Pass voting_session_id to frontend so it knows which voting to show
            redirect_url = f"{frontend_url}/vote/{voting_session_id}?login=success"
            
            logger.info(
                f"SPID authentication successful - "
                f"Citizen: {citizen.id}, "
                f"Municipality: {municipality.name}, "
                f"Voting: {voting_session.title}"
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Authentication successful',
                'citizen_id': citizen.id,
                'municipality': {
                    'id': municipality.id,
                    'name': municipality.name,
                    'ipa_code': municipality.ipa_code
                },
                'voting_session': {
                    'id': voting_session.id,
                    'title': voting_session.title
                },
                'redirect_url': redirect_url,
                'created': created
            })
            
        except ValueError as e:
            logger.error(f"SPID callback validation error: {e}")
            return JsonResponse({
                'error': 'Invalid SPID response',
                'detail': str(e)
            }, status=400)
            
        except Exception as e:
            logger.error(f"SPID callback error: {e}", exc_info=True)
            return JsonResponse({
                'error': 'Authentication failed',
                'detail': str(e)
            }, status=500)
    
    def get(self, request):
        """
        Handle GET callback (in case DigitID uses GET instead of POST). TO BE REMOVED
        """
        return self.post(request)