from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_dicom, name='upload_dicom'),
    path('process/<int:series_id>/', views.process_dicom, name='process_dicom'),
    path('delete/<int:series_id>/', views.delete_dicom, name='delete_dicom'),
    #path('result/<int:result_id>/', views.view_result, name='view_result'), 

]
