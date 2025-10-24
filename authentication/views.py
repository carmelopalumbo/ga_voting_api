"""
Authentication app URLs - SPID login and callback
"""
from django.urls import path
from .views import SPIDLoginView, SPIDCallbackView

app_name = 'authentication'

urlpatterns = [
    # SPID authentication flow
    path('spid/login/', SPIDLoginView.as_view(), name='spid_login'),
    path('spid/callback/', SPIDCallbackView.as_view(), name='spid_callback'),
]