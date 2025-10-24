"""
URL configuration for ga_voting_api project.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(request):
    """Simple health check endpoint"""
    return JsonResponse({
        'status': 'ok',
        'service': 'voting-api',
        'version': '1.0.0'
    })


urlpatterns = [
    # Admin panel
    path('admin/', admin.site.urls),
    
    # Health check
    path('health/', health_check, name='health_check'),
    
    # API endpoints
    path('api/auth/', include('authentication.urls')),
    path('api/', include('voting.urls')),
]