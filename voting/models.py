from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from authentication.models import Municipality, Citizen

class VotingSession(models.Model):
    """
    Represents a voting session (votazione).
    Can be a referendum, survey, election, etc.
    """
    TYPE_CHOICES = [
        ('referendum', 'Referendum'),
        ('survey', 'Sondaggio'),
        ('election', 'Elezione'),
        ('consultation', 'Consultazione'),
    ]

    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.PROTECT,
        related_name='voting_sessions',
        verbose_name="Comune"
    )
    title = models.CharField(max_length=255, verbose_name="Titolo")
    description = models.TextField(verbose_name="Descrizione")
    type = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        default='referendum',
        verbose_name="Tipo"
    )
    start_date = models.DateTimeField(verbose_name="Data Inizio")
    end_date = models.DateTimeField(verbose_name="Data Fine")
    is_active = models.BooleanField(
        default=True,
        verbose_name="Attiva",
        help_text="Se False, non è possibile votare"
    )
    results_public = models.BooleanField(
        default=False,
        verbose_name="Risultati Pubblici",
        help_text="Se True, i risultati sono visibili a tutti"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data Creazione")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ultimo Aggiornamento")

    class Meta:
        verbose_name = "Sessione di Votazione"
        verbose_name_plural = "Sessioni di Votazione"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.title} - {self.municipality.name}"

    def is_open(self):
        """Check if voting is currently open"""
        now = timezone.now()
        return (
            self.is_active and
            self.start_date <= now <= self.end_date
        )

    def clean(self):
        """Validate that end_date is after start_date"""
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValidationError("La data di fine deve essere successiva alla data di inizio")


class Option(models.Model):
    """
    Represents a voting option (opzione di voto).
    E.g., "Sì", "No", "Candidato Mario Rossi"
    """
    voting_session = models.ForeignKey(
        VotingSession,
        on_delete=models.CASCADE,
        related_name='options',
        verbose_name="Sessione di Votazione"
    )
    text = models.CharField(max_length=255, verbose_name="Testo")
    display_order = models.IntegerField(
        default=0,
        verbose_name="Ordine Visualizzazione",
        help_text="Ordine di visualizzazione nella scheda (più basso = prima)"
    )
    image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name="URL Immagine"
    )

    class Meta:
        verbose_name = "Opzione"
        verbose_name_plural = "Opzioni"
        ordering = ['voting_session', 'display_order']
        indexes = [
            models.Index(fields=['voting_session', 'display_order']),
        ]

    def __str__(self):
        return f"{self.text} - {self.voting_session.title}"

    def get_vote_count(self):
        """Get number of votes for this option"""
        return self.results.count()


class CitizenHasVoted(models.Model):
    """
    Tracks which citizens have voted in which sessions.
    Used ONLY to prevent duplicate votes.
    Does NOT store which option was chosen (for anonymity).
    """
    citizen = models.ForeignKey(
        Citizen,
        on_delete=models.PROTECT,
        related_name='voted_sessions',
        verbose_name="Cittadino"
    )
    voting_session = models.ForeignKey(
        VotingSession,
        on_delete=models.PROTECT,
        related_name='voters',
        verbose_name="Sessione di Votazione"
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Data e Ora Voto")

    class Meta:
        verbose_name = "Cittadino Ha Votato"
        verbose_name_plural = "Cittadini Hanno Votato"
        unique_together = ('citizen', 'voting_session')
        indexes = [
            models.Index(fields=['citizen', 'voting_session']),
            models.Index(fields=['voting_session']),
        ]

    def __str__(self):
        return f"Cittadino #{self.citizen.id} ha votato in {self.voting_session.title}"


class Result(models.Model):
    """
    Stores anonymous voting results.
    CRITICAL: NO link to citizen for complete anonymity.
    """
    voting_session = models.ForeignKey(
        VotingSession,
        on_delete=models.PROTECT,
        related_name='results',
        verbose_name="Sessione di Votazione"
    )
    option = models.ForeignKey(
        Option,
        on_delete=models.PROTECT,
        related_name='results',
        verbose_name="Opzione Scelta"
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Data e Ora")
    session_hash = models.CharField(
        max_length=64,
        verbose_name="Hash Sessione",
        help_text="Random hash per evitare correlazioni temporali"
    )

    class Meta:
        verbose_name = "Risultato"
        verbose_name_plural = "Risultati"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['voting_session']),
            models.Index(fields=['option']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"Voto per {self.option.text} in {self.voting_session.title}"