"""
OIDC (OpenID Connect) utilities for DigitID SPID integration.

This module provides functions for:
- Downloading OIDC metadata from DigitID
- Extracting JWKS (JSON Web Key Set) public keys
- Verifying JWT token signatures
- Decoding and extracting user data from SPID tokens
"""

import requests
import jwt
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Cache durations
METADATA_CACHE_DURATION = 60 * 60 * 24  # 24 hours
JWKS_CACHE_DURATION = 60 * 60 * 24      # 24 hours


def get_oidc_metadata_url():
    """
    Get OIDC metadata URL based on environment (test/production).
    
    Returns:
        str: Full URL to OIDC metadata endpoint
    """
    tenant = settings.SPID_TENANT
    policy = "B2C_1A_SIGNUP_SIGNIN_SPID"  # Fixed policy from e-Fil documentation
    
    return (
        f"https://{tenant}.b2clogin.com/{tenant}.onmicrosoft.com/"
        f"v2.0/.well-known/openid-configuration?p={policy}"
    )


def get_oidc_metadata():
    """
    Download OIDC metadata from DigitID.
    Result is cached for 24 hours to avoid repeated requests.
    
    Returns:
        dict: OIDC metadata containing issuer, jwks_uri, etc.
        
    Raises:
        requests.RequestException: If metadata download fails
        
    Example:
        >>> metadata = get_oidc_metadata()
        >>> print(metadata['issuer'])
        >>> print(metadata['jwks_uri'])
    """
    # Check cache first
    cache_key = f"oidc_metadata_{settings.SPID_TENANT}"
    cached_metadata = cache.get(cache_key)
    
    if cached_metadata:
        logger.debug("OIDC metadata retrieved from cache")
        return cached_metadata
    
    # Download metadata
    metadata_url = get_oidc_metadata_url()
    logger.info(f"Downloading OIDC metadata from: {metadata_url}")
    
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        metadata = response.json()
        
        # Cache for 24 hours
        cache.set(cache_key, metadata, METADATA_CACHE_DURATION)
        logger.info("OIDC metadata downloaded and cached successfully")
        
        return metadata
        
    except requests.RequestException as e:
        logger.error(f"Failed to download OIDC metadata: {e}")
        raise


def get_jwks():
    """
    Download JWKS (JSON Web Key Set) - the public keys used to verify JWT signatures.
    Result is cached for 24 hours.
    
    Returns:
        dict: JWKS containing public keys
        
    Raises:
        requests.RequestException: If JWKS download fails
        
    Example:
        >>> jwks = get_jwks()
        >>> print(jwks['keys'])  # List of public keys
    """
    # Check cache first
    cache_key = f"jwks_{settings.SPID_TENANT}"
    cached_jwks = cache.get(cache_key)
    
    if cached_jwks:
        logger.debug("JWKS retrieved from cache")
        return cached_jwks
    
    # Get jwks_uri from metadata
    metadata = get_oidc_metadata()
    jwks_uri = metadata.get('jwks_uri')
    
    if not jwks_uri:
        raise ValueError("jwks_uri not found in OIDC metadata")
    
    logger.info(f"Downloading JWKS from: {jwks_uri}")
    
    try:
        response = requests.get(jwks_uri, timeout=10)
        response.raise_for_status()
        jwks = response.json()
        
        # Cache for 24 hours
        cache.set(cache_key, jwks, JWKS_CACHE_DURATION)
        logger.info("JWKS downloaded and cached successfully")
        
        return jwks
        
    except requests.RequestException as e:
        logger.error(f"Failed to download JWKS: {e}")
        raise


def get_signing_key(token):
    """
    Extract the signing key from JWKS based on the 'kid' (key ID) in the JWT header.
    
    Args:
        token (str): JWT token
        
    Returns:
        jwt.PyJWK: Signing key for verification
        
    Raises:
        ValueError: If signing key not found
    """
    # Decode header without verification to get 'kid'
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get('kid')
    
    if not kid:
        raise ValueError("Token header does not contain 'kid'")
    
    # Get JWKS
    jwks = get_jwks()
    
    # Find the matching key
    signing_key = None
    for key in jwks.get('keys', []):
        if key.get('kid') == kid:
            signing_key = jwt.PyJWK(key)
            break
    
    if not signing_key:
        raise ValueError(f"Signing key with kid '{kid}' not found in JWKS")
    
    logger.debug(f"Found signing key with kid: {kid}")
    return signing_key


def verify_jwt_signature(token):
    """
    Verify JWT signature using public key from JWKS.
    This ensures the token was issued by DigitID and hasn't been tampered with.
    
    Args:
        token (str): JWT token to verify
        
    Returns:
        dict: Decoded token payload if signature is valid
        
    Raises:
        jwt.InvalidTokenError: If signature verification fails
        jwt.ExpiredSignatureError: If token is expired
        
    Example:
        >>> payload = verify_jwt_signature(token)
        >>> print(payload['sub'])  # User identifier
    """
    try:
        # Get the signing key
        signing_key = get_signing_key(token)
        
        # Get metadata for issuer validation
        metadata = get_oidc_metadata()
        expected_issuer = metadata.get('issuer')
        
        # Verify signature and decode
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=['RS256'],  # DigitID uses RS256
            audience=settings.SPID_CLIENT_ID,  # Token must be for our client
            issuer=expected_issuer,  # Token must be from DigitID
            options={
                'verify_signature': True,
                'verify_exp': True,  # Check expiration
                'verify_aud': True,  # Check audience
                'verify_iss': True,  # Check issuer
            }
        )
        
        logger.info("JWT signature verified successfully")
        return decoded
        
    except jwt.ExpiredSignatureError:
        logger.error("JWT token has expired")
        raise
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT verification failed: {e}")
        raise


def decode_spid_token(token):
    """
    Decode and extract user data from SPID JWT token.
    Performs signature verification and extracts citizen information.
    
    Args:
        token (str): JWT token from DigitID callback
        
    Returns:
        dict: Extracted user data with keys:
            - fiscal_code: Codice fiscale (always present)
            - first_name: Nome (if available)
            - last_name: Cognome (if available)
            - email: Email (if available)
            - spid_level: SPID authentication level
            - raw_claims: All claims from token (for debugging)
            
    Raises:
        jwt.InvalidTokenError: If token verification fails
        ValueError: If fiscal code not found in token
        
    Example:
        >>> user_data = decode_spid_token(token)
        >>> print(user_data['fiscal_code'])
        'RSSMRA80A01H501Z'
        >>> print(user_data['first_name'])
        'Mario'
    """
    # Verify signature and decode
    payload = verify_jwt_signature(token)
    
    # Extract user data
    # Note: Field names may vary based on DigitID configuration
    # Common fields: fiscalNumber, given_name, family_name, email
    
    fiscal_code = (
        payload.get('fiscalNumber') or 
        payload.get('fiscal_number') or
        payload.get('fiscalcode') or
        payload.get('cf')
    )
    
    if not fiscal_code:
        logger.error(f"Fiscal code not found in token. Available claims: {list(payload.keys())}")
        raise ValueError("Fiscal code not found in SPID token")
    
    # Normalize fiscal code (uppercase, strip)
    fiscal_code = fiscal_code.strip().upper()
    
    # Extract other fields
    user_data = {
        'fiscal_code': fiscal_code,
        'first_name': payload.get('given_name') or payload.get('name') or payload.get('givenName'),
        'last_name': payload.get('family_name') or payload.get('surname') or payload.get('familyName'),
        'email': payload.get('email'),
        'spid_level': payload.get('acr') or payload.get('spidLevel'),
        'raw_claims': payload,  # Keep all claims for debugging
    }
    
    logger.info(f"SPID token decoded successfully for fiscal code: {fiscal_code[:4]}****")
    return user_data


def extract_token_from_callback(request):
    """
    Extract JWT token from SPID callback request.
    DigitID can send token via query parameter or form data.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: JWT token
        
    Raises:
        ValueError: If token not found in request
        
    Example:
        >>> token = extract_token_from_callback(request)
    """
    # Try different possible locations
    token = (
        request.GET.get('id_token') or
        request.POST.get('id_token') or
        request.GET.get('token') or
        request.POST.get('token')
    )
    
    if not token:
        logger.error("Token not found in callback request")
        logger.debug(f"GET params: {list(request.GET.keys())}")
        logger.debug(f"POST params: {list(request.POST.keys())}")
        raise ValueError("Token not found in SPID callback")
    
    return token


# ==============================================================================
# TESTING FUNCTIONS (for development)
# ==============================================================================

def test_oidc_connection():
    """
    Test OIDC connection to DigitID.
    Useful for verifying configuration and network connectivity.
    
    Usage:
        >>> from authentication.oidc_utils import test_oidc_connection
        >>> test_oidc_connection()
        ✓ OIDC metadata downloaded
        ✓ JWKS downloaded
        ✓ Found X signing keys
    """
    try:
        # Test metadata download
        metadata = get_oidc_metadata()
        print(f"✓ OIDC metadata downloaded")
        print(f"  Issuer: {metadata.get('issuer')}")
        print(f"  JWKS URI: {metadata.get('jwks_uri')}")
        
        # Test JWKS download
        jwks = get_jwks()
        num_keys = len(jwks.get('keys', []))
        print(f"✓ JWKS downloaded")
        print(f"  Found {num_keys} signing key(s)")
        
        print("\n✅ OIDC connection test passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ OIDC connection test failed: {e}")
        return False


if __name__ == "__main__":
    test_oidc_connection()