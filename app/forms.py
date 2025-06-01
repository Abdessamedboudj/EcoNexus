from django import forms
from .models import Assessment

class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ['location_name', 'latitude', 'longitude', 'system_type']
        widgets = {
            'location_name': forms.TextInput(attrs={'class': 'form-control', 'id': 'location-autocomplete'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'system_type': forms.Select(attrs={'class': 'form-control'}),
        }