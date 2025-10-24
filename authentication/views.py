"""
Authentication views - SPID login and callback
"""
from django.http import JsonResponse
from django.views import View


class SPIDLoginView(View):
    """
    Endpoint to initiate SPID login flow.
    Generates SPID URL and redirects user.
    """
    
    def get(self, request):
        """
        Generate SPID authentication URL and redirect user.
        
        TODO: Implement SPID URL generation
        """
        return JsonResponse({
            'message': 'SPID login endpoint - TODO: implement',
            'status': 'not_implemented'
        }, status=501)


class SPIDCallbackView(View):
    """
    Callback endpoint after SPID authentication.
    Validates token, creates/updates citizen, generates JWT, redirects to frontend.
    """
    
    def get(self, request):
        """
        Handle SPID callback (usually GET with code parameter).
        
        TODO: Implement SPID callback handling
        """
        return JsonResponse({
            'message': 'SPID callback endpoint - TODO: implement',
            'status': 'not_implemented'
        }, status=501)
    
    def post(self, request):
        """
        Handle SPID callback (POST with form data).
        
        TODO: Implement SPID callback handling
        """
        return JsonResponse({
            'message': 'SPID callback endpoint - TODO: implement',
            'status': 'not_implemented'
        }, status=501)