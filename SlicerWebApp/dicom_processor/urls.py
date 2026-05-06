# SlicerWebApp/dicom_processor/urls.py

from django.urls import path
from . import views

app_name = 'dicom_processor'  # Add this line

urlpatterns = [
    # Main page routes
    path('', views.home, name='home'),
    path('upload/', views.upload_dicom, name='upload_dicom'),
    path('my-uploads/', views.my_uploads, name='my_uploads'),
    path('process/<int:series_id>/', views.process_dicom, name='process_dicom'),
    
    # Dashboard routes
    path('dashboard/', views.dashboard_view, name='dashboard_latest_view'),
    path('dashboard/<int:series_id>/', views.dashboard_view, name='dashboard_series_view'),
    path('survey/<int:series_id>/', views.survey_view, name='survey_view'),
    
    # Action routes
    path('delete/<int:series_id>/', views.delete_dicom, name='delete_dicom'),

    # AJAX URL endpoints for the dashboard
    path('ajax/get_volume_url/<int:series_id>/', views.get_volume_url, name='get_volume_url'),
    path('ajax/get_heatmap_url/<int:series_id>/', views.get_heatmap_url, name='get_heatmap_url'),
    path('ajax/get_slice_url/', views.get_slice_url_ajax, name='get_slice_url_ajax'),
]