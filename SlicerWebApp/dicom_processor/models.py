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
    Stores the results of processing a DicomSeries.
    This links a DicomSeries to its generated data, like heatmaps and predictions.
    """
    dicom_series = models.OneToOneField(
        DicomSeries,
        on_delete=models.CASCADE,
        related_name='processing_result'
    )
    result_type = models.CharField(max_length=50, default='heatmap_and_prediction')
    
    # === MODIFICATION START ===
    # We now store paths and both prediction probabilities directly.
    
    # Path to the generated heatmap NRRD file
    heatmap_file_path = models.CharField(max_length=512, blank=True, null=True)

    # Path to the generated volume NRRD file for the 3D viewer
    nrrd_file_path = models.CharField(max_length=512, blank=True, null=True)
    
    # Store both probabilities from the model.
    # We assume the model outputs probabilities for two classes.
    ece_probability = models.FloatField(null=True, blank=True)
    non_ece_probability = models.FloatField(null=True, blank=True)

    # === MODIFICATION END ===

    processed_date = models.DateTimeField(auto_now_add=True)
    
    # Storing slice counts as a JSON string to avoid recalculating
    # e.g., "{'axial': 128, 'coronal': 256, 'sagittal': 256}"
    slice_counts_json = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Result for {self.dicom_series.name}"

