from django.db import models
from django.utils import timezone

class Assessment(models.Model):
    SYSTEM_CHOICES = [
        ('solar', 'Solar Panels'),
        ('wind', 'Wind Turbines'),
        ('hydro', 'Hydroelectric'),
        ('biomass', 'Biomass'),
        ('geothermal', 'Geothermal'),
        ('hybrid', 'Hybrid System'),
    ]
    location_name = models.CharField(max_length=255)  # For autocomplete
    latitude = models.FloatField()
    longitude = models.FloatField()
    system_type = models.CharField(max_length=20, choices=SYSTEM_CHOICES)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.location_name} ({self.latitude}, {self.longitude}) - {self.get_system_type_display()}"

class Result(models.Model):
    assessment = models.OneToOneField(Assessment, on_delete=models.CASCADE)
    optimal_tilt = models.FloatField()
    optimal_orientation = models.FloatField()
    daily_output = models.FloatField()
    monthly_output = models.FloatField()
    yearly_output = models.FloatField()
    co2_saved = models.FloatField()
    trees_equivalent = models.IntegerField()
    recommended_equipment = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Results for {self.assessment}"