# SlicerWebApp/dicom_processor/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.contrib import messages
import os
import json
import shutil
import traceback
import pydicom

from .models import DicomSeries, ProcessingResult
from .forms import DicomUploadForm
from .utils import (
    generate_heatmap,
    load_scan_as_3d_volume,
    convert_dicom_series_to_nrrd,
    convert_dicom_to_volume
)

# --- Main Views ---
def home(request):
    return render(request, 'dicom_processor/home.html')

@login_required
def my_uploads(request):
    series_list = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date')
    return render(request, 'dicom_processor/my_uploads.html', {'series_list': series_list})

@login_required
def dashboard_view(request, series_id=None):
    series = None
    ece_probability = None
    if series_id:
        series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
        try:
            # --- This is the robust version ---
            # It ensures we only work with a valid ProcessingResult
            result = series.processing_result
            prob = result.ece_probability
            
            # Try to convert the probability to a float. If it fails for any reason,
            # (e.g., it's not a number), treat it as None.
            ece_probability = float(prob)
        except (ProcessingResult.DoesNotExist, TypeError, ValueError, AttributeError):
            # If the result doesn't exist or the probability is not a valid number,
            # ensure it's None so the chart doesn't try to render.
            ece_probability = None
            
    context = {
        'series': series,
        'ece_probability': ece_probability,
    }
    return render(request, 'dicom_processor/dashboard.html', context)

# --- File Handling Views ---
@login_required
def upload_dicom(request):
    if request.method == 'POST':
        form = DicomUploadForm(request.POST, request.FILES)
        files = request.FILES.getlist('dicom_files')
        if form.is_valid():
            try:
                first_file = files[0]
                ds = pydicom.dcmread(first_file, stop_before_pixels=True)
                series_name = getattr(ds, "SeriesDescription", "Unnamed Series")
                patient_id = getattr(ds, "PatientID", "")
                patient_age = getattr(ds, "PatientAge", "")
                patient_gender = getattr(ds, "PatientSex", "")
                modality = getattr(ds, "Modality", "")
            except Exception as e:
                series_name = "Unnamed Series"
                patient_id = patient_age = patient_gender = modality = ""

            series = DicomSeries.objects.create(
                name=series_name, user=request.user, patient_id=patient_id,
                patient_age=patient_age, patient_gender=patient_gender, modality=modality,
            )
            series_path = os.path.join(settings.MEDIA_ROOT, 'dicom_series', f'series_{series.id}')
            os.makedirs(series_path, exist_ok=True)
            series.file_path = series_path
            series.save(update_fields=['file_path'])
            for f in files:
                with open(os.path.join(series_path, f.name), 'wb+') as destination:
                    for chunk in f.chunks():
                        destination.write(chunk)
            return redirect('my_uploads')
    else:
        form = DicomUploadForm()
    return render(request, 'dicom_processor/upload.html', {'form': form})

@login_required
def delete_dicom(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    if request.method == 'POST':
        if series.file_path and os.path.isdir(series.file_path):
            shutil.rmtree(series.file_path)
        series.delete()
        return redirect('my_uploads')
    return render(request, 'dicom_processor/my_uploads.html')

# --- Processing Views ---
@login_required
def process_dicom(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    if request.method == 'POST':
        try:
            print(f"--- Starting processing for Series ID: {series.id} ---")
            heatmap_vti_file_path, prediction_score = generate_heatmap(series.file_path)
            ece_prob = prediction_score if prediction_score is not None else 0.0
            
            nrrd_dir = os.path.join(settings.MEDIA_ROOT, "nrrd_files")
            os.makedirs(nrrd_dir, exist_ok=True)
            nrrd_path = os.path.join(nrrd_dir, f"user{series.user.id}_series{series.id}.nrrd")
            convert_dicom_series_to_nrrd(series.file_path, nrrd_path)
            
            volume, _, _ = load_scan_as_3d_volume(series.file_path)
            slice_counts = {'axial': volume.shape[0], 'coronal': volume.shape[1], 'sagittal': volume.shape[2]} if volume is not None else {}
            
            ProcessingResult.objects.update_or_create(
                dicom_series=series,
                defaults={
                    'result_type': 'heatmap_and_prediction',
                    'heatmap_vti_path': heatmap_vti_file_path,
                    'nrrd_file_path': nrrd_path,
                    'ece_probability': ece_prob,
                    'non_ece_probability': 1.0 - ece_prob,
                    'slice_counts_json': json.dumps(slice_counts)
                }
            )
            messages.success(request, f"Processing complete for '{series.name}'.")
            return redirect('dicom_processor:dashboard_series_view', series_id=series.id)
        
        except FileNotFoundError as e:
            messages.error(request, f"Processing failed: {e}")
            return redirect('dicom_processor:process_dicom', series_id=series.id)
        
        except Exception as e:
            messages.error(request, f"An unexpected error occurred during processing: {e}")
            return redirect('dicom_processor:process_dicom', series_id=series.id)

    latest_result = ProcessingResult.objects.filter(dicom_series=series).first()
    return render(request, 'dicom_processor/process.html', {'series': series, 'latest_result': latest_result})

# --- AJAX Views ---
@login_required
def get_volume_url(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    try:
        filename_base = f"series_{series.id}"
        volume_path = convert_dicom_to_volume(series.file_path, output_filename_base=filename_base)
        if volume_path:
            relative_path = os.path.relpath(volume_path, settings.MEDIA_ROOT)
            volume_url = os.path.join(settings.MEDIA_URL, relative_path).replace("\\", "/")
            return JsonResponse({'success': True, 'volume_url': volume_url})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to convert DICOM series.'}, status=500)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def get_heatmap_url(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    try:
        result = series.processing_result
        vti_path = result.heatmap_vti_path
        if vti_path and os.path.exists(vti_path):
            relative_path = os.path.relpath(vti_path, settings.MEDIA_ROOT)
            vti_url = os.path.join(settings.MEDIA_URL, relative_path).replace("\\", "/")
            return JsonResponse({'success': True, 'heatmap_url': vti_url})
        else:
            return JsonResponse({'success': False, 'error': 'Heatmap file not found.'}, status=404)
    except ProcessingResult.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Processing result not found.'}, status=404)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# --- ADDING THIS FUNCTION BACK IN ---
def get_slice_url_ajax(request):
    return JsonResponse({'success': False, 'error': 'This function is not implemented.'})