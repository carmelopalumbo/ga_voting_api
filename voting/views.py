"""
Voting app URLs - Active session, vote, results
"""
from django.urls import path
from .views import ActiveVotingSessionView, CastVoteView, VotingResultsView

app_name = 'voting'

urlpatterns = [
    # Active voting session with options and has_voted check
    path('voting/active/', ActiveVotingSessionView.as_view(), name='active_voting_session'),
    
    # Cast vote
    path('voting/vote/', CastVoteView.as_view(), name='cast_vote'),
    
    # Results (TODO: implement later)
    path('voting/results/<int:session_id>/', VotingResultsView.as_view(), name='voting_results'),
]