"""
Authentication app URLs - SPID login and callback
"""
from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    # SPID authentication flow
    path('spid/login/', views.spid_login, name='spid_login'),
    path('spid/callback/', views.spid_callback, name='spid_callback'),
]