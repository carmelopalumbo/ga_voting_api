"""
Admin configuration for voting app
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import VotingSession, Option, CitizenHasVoted, Result


class OptionInline(admin.TabularInline):
    """
    Inline admin for Options within VotingSession
    """
    model = Option
    extra = 2
    fields = ('text', 'display_order', 'image_url')
    ordering = ('display_order',)


@admin.register(VotingSession)
class VotingSessionAdmin(admin.ModelAdmin):
    """
    Admin interface for VotingSession model
    """
    list_display = (
        'title',
        'municipality',
        'type',
        'start_date',
        'end_date',
        'is_active',
        'voting_status',
        'total_voters',
        'total_votes'
    )
    list_filter = ('type', 'is_active', 'results_public', 'municipality', 'start_date')
    search_fields = ('title', 'description', 'municipality__name')
    ordering = ('-start_date',)
    
    fieldsets = (
        ('Informazioni Principali', {
            'fields': ('municipality', 'title', 'description', 'type')
        }),
        ('Periodo di Votazione', {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        ('Configurazione', {
            'fields': ('results_public',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OptionInline]
    
    def voting_status(self, obj):
        """Show if voting is currently open"""
        if obj.is_open():
            return format_html('<span style="color: green;">● Aperta</span>')
        elif obj.is_active:
            return format_html('<span style="color: orange;">● Non ancora iniziata</span>')
        else:
            return format_html('<span style="color: red;">● Chiusa</span>')
    voting_status.short_description = "Status"
    
    def total_voters(self, obj):
        """Count how many people voted"""
        return obj.voters.count()
    total_voters.short_description = "Votanti"
    
    def total_votes(self, obj):
        """Count total anonymous votes"""
        return obj.results.count()
    total_votes.short_description = "Voti"


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    """
    Admin interface for Option model
    """
    list_display = ('text', 'voting_session', 'display_order', 'vote_count')
    list_filter = ('voting_session',)
    search_fields = ('text', 'voting_session__title')
    ordering = ('voting_session', 'display_order')
    
    fieldsets = (
        ('Informazioni', {
            'fields': ('voting_session', 'text',)
        }),
        ('Visualizzazione', {
            'fields': ('display_order', 'image_url')
        }),
    )
    
    def vote_count(self, obj):
        """Show number of votes for this option"""
        count = obj.get_vote_count()
        return format_html('<strong>{}</strong>', count)
    vote_count.short_description = "Voti Ricevuti"


@admin.register(CitizenHasVoted)
class CitizenHasVotedAdmin(admin.ModelAdmin):
    """
    Admin interface for CitizenHasVoted model
    Shows WHO voted WHERE (but not WHAT they voted)
    """
    list_display = ('citizen_id_display', 'voting_session', 'timestamp')
    list_filter = ('voting_session', 'timestamp')
    search_fields = ('citizen__fiscal_code_hash', 'voting_session__title')
    ordering = ('-timestamp',)
    
    fieldsets = (
        ('Votazione', {
            'fields': ('citizen', 'voting_session')
        }),
        ('Metadata', {
            'fields': ('timestamp',)
        }),
    )
    
    readonly_fields = ('timestamp',)
    
    def citizen_id_display(self, obj):
        """Show citizen ID (not personal data)"""
        return f"Cittadino #{obj.citizen.id}"
    citizen_id_display.short_description = "Cittadino"
    
    # Security: prevent modifications
    def has_add_permission(self, request):
        """Votes can only be added through the API"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Votes cannot be modified"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete vote records"""
        return request.user.is_superuser


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    """
    Admin interface for Result model
    Shows anonymous voting results
    """
    list_display = ('id', 'voting_session', 'option', 'timestamp_display')
    list_filter = ('voting_session', 'option', 'timestamp')
    search_fields = ('voting_session__title', 'option__text')
    ordering = ('-timestamp',)
    
    fieldsets = (
        ('Voto', {
            'fields': ('voting_session', 'option')
        }),
        ('Metadata', {
            'fields': ('timestamp', 'session_hash')
        }),
    )
    
    readonly_fields = ('timestamp', 'session_hash')
    
    def timestamp_display(self, obj):
        """Format timestamp"""
        return obj.timestamp.strftime('%d/%m/%Y %H:%M:%S')
    timestamp_display.short_description = "Data e Ora"
    
    # Security: prevent modifications
    def has_add_permission(self, request):
        """Results can only be added through the API"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Results cannot be modified"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete results"""
        return request.user.is_superuser
