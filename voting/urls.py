"""
Voting app URLs - Active session, vote, results
"""
from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    # Active voting session with options and has_voted check
    path('voting/active/', views.active_voting_session, name='active_voting_session'),
    
    # Cast vote
    path('voting/vote/', views.cast_vote, name='cast_vote'),
    
    # Results (TODO: implement later)
    path('voting/results/<int:session_id>/', views.voting_results, name='voting_results'),
]