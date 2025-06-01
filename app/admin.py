from django.contrib import admin
from .models import Assessment, Result

@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('location_name', 'latitude', 'longitude', 'system_type', 'created_at')
    search_fields = ('location_name',)
    list_filter = ('system_type', 'created_at')

@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'optimal_tilt', 'optimal_orientation', 'daily_output', 'monthly_output', 'yearly_output', 'co2_saved', 'trees_equivalent', 'created_at')
    search_fields = ('assessment__location_name',)
    list_filter = ('created_at',)