from django.db import models

class Municipality(models.Model):
    """
    Represents a municipality (Comune) that uses the voting system.
    """
    name = models.CharField(max_length=255, verbose_name="Nome Comune")
    ipa_code = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Codice IPA",
        help_text="Codice IPA del comune (es: c_h501)"
    )
    cap = models.CharField(max_length=255, verbose_name="CAP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data Creazione")

    class Meta:
        verbose_name = "Comune"
        verbose_name_plural = "Comuni"
        ordering = ['name']

    def __str__(self):
        return f"{self.name}"


class Citizen(models.Model):
    """
    Represents a citizen who can vote.
    Personal data is encrypted for privacy.
    """
    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.PROTECT,
        related_name='citizens',
        verbose_name="Comune"
    )
    
    # Hash
    fiscal_code_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Hash Codice Fiscale",
        help_text="SHA-256 hash del codice fiscale"
    )
    
    # Hash (AES-256)
    fiscal_code_encrypted = models.TextField(verbose_name="Codice Fiscale Criptato")
    email_encrypted = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Email Criptata"
    )
    
    # Metadata
    registration_date = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Data Registrazione"
    )

    class Meta:
        verbose_name = "Cittadino"
        verbose_name_plural = "Cittadini"
        ordering = ['-registration_date']
        indexes = [
            models.Index(fields=['fiscal_code_hash']),
            models.Index(fields=['municipality']),
        ]

    def __str__(self):
        # Non mostriamo dati sensibili nell'admin
        return f"Cittadino #{self.id} - {self.municipality.name}"

    def has_voted_in_session(self, voting_session):
        """
        Check if citizen has already voted in a specific voting session.
        """
        from voting.models import CitizenHasVoted
        return CitizenHasVoted.objects.filter(
            citizen=self,
            voting_session=voting_session
        ).exists()