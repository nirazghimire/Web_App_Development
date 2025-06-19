from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_dicom, name='upload_dicom'),
    path('process/<int:series_id>/', views.process_dicom, name='process_dicom'),
    path('delete/<int:series_id>/', views.delete_dicom, name='delete_dicom'),
    #path('result/<int:result_id>/', views.view_result, name='view_result'), 
    path('ajax/get_slice_url/', views.get_slice_url_ajax, name='ajax_get_slice_url'),
    path('ajax/get_nrrd_url/<int:series_id>/', views.get_nrrd_url, name='ajax_get_nrrd_url'),
    path('ajax/get_heatmap_url/<int:series_id>/', views.get_heatmap_url, name='get_heatmap_url_ajax'),
 ]

