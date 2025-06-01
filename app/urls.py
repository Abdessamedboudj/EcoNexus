from django.urls import path
from . import views
from django.contrib import admin

urlpatterns = [
    path('', views.index, name='index'),
    path('api/assess', views.assess_location, name='assess_location'),
    path('api/assessment/<int:assessment_id>', views.get_assessment, name='get_assessment'),
]