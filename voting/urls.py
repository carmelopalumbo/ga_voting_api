"""
Voting app URLs - Sessions list/detail, vote, results
"""
from django.urls import path
from .views import VotingSessionListView, CastVoteView, VotingResultsView

app_name = 'voting'

urlpatterns = [
    # List all active voting sessions OR get specific session detail
    # GET /api/voting/sessions/  → all sessions
    # GET /api/voting/sessions/?voting_session_id=1  → specific session with has_voted
    path('voting/sessions/', VotingSessionListView.as_view(), name='voting_sessions'),
    
    # Cast vote
    path('voting/vote/', CastVoteView.as_view(), name='cast_vote'),
    
    # Results (TODO: implement later)
    path('voting/results/<int:session_id>/', VotingResultsView.as_view(), name='voting_results'),
]