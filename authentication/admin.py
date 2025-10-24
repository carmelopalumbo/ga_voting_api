"""
Admin configuration for authentication app
"""
from django.contrib import admin
from .models import Municipality, Citizen


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    """
    Admin interface for Municipality model
    """
    list_display = ('name', 'ipa_code', 'cap', 'created_at')
    list_filter = ()
    search_fields = ('name', 'ipa_code', 'cap')
    ordering = ('name',)
    
    fieldsets = (
        ('Informazioni Principali', {
            'fields': ('name', 'ipa_code')
        }),
    )
    
    readonly_fields = ('created_at',)


@admin.register(Citizen)
class CitizenAdmin(admin.ModelAdmin):
    """
    Admin interface for Citizen model
    NOTE: Personal data is encrypted, so we show only IDs and metadata
    """
    list_display = (
        'id', 
        'municipality', 
        'fiscal_code_hash_short',
        'registration_date'
    )
    list_filter = ('municipality', 'registration_date')
    search_fields = ('fiscal_code_hash',)  # Search by hash
    ordering = ('-registration_date',)
    
    fieldsets = (
        ('Identificazione', {
            'fields': ('municipality', 'fiscal_code_hash'),
            'description': 'Hash del codice fiscale per identificazione'
        }),
        ('Dati Criptati', {
            'fields': (
                'fiscal_code_encrypted',
                'email_encrypted'
            ),
            'classes': ('collapse',),
            'description': 'Dati personali criptati (non leggibili direttamente)'
        }),
        ('Metadata', {
            'fields': ('registration_date',)
        }),
    )
    
    readonly_fields = ('registration_date', 'fiscal_code_hash')
    
    def fiscal_code_hash_short(self, obj):
        """Show first 16 chars of hash"""
        return f"{obj.fiscal_code_hash[:16]}..." if obj.fiscal_code_hash else "-"
    fiscal_code_hash_short.short_description = "CF Hash (troncato)"
    
    # Security: prevent accidental deletion
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete citizens"""
        return request.user.is_superuser