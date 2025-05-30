from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class DicomSeries(models.Model):
    """
    Model to store DICOM series information.
    """
    name = models.CharField(max_length=255)
    patient_id = models.CharField(max_length=50, blank=True)
    patient_age = models.CharField(max_length=10, blank=True)
    patient_gender = models.CharField(max_length=10, blank=True)
    uploaded_date = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file_path = models.CharField(max_length=255, unique=True)
    window_center = models.FloatField(default=40)
    window_width = models.FloatField(default=400)
    modality = models.CharField(max_length=10, blank=True)

    def __str__(self):
        return self.name
    
class ProcessingResult(models.Model):
    """
    Model to store processing results of DICOM series.
    """
    dicom_series = models.ForeignKey(DicomSeries, on_delete=models.CASCADE, related_name='processing_results')
    result_file_path = models.CharField(max_length=255)
    processed_date = models.DateTimeField(auto_now_add=True)
    result_type = models.CharField(max_length=50) 
    heatmap_intensity = models.FloatField()
    processed_slices = models.IntegerField()


    def __str__(self):
        return f"{self.result_type} for  {self.dicom_series.name}"
    
