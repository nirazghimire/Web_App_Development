# SlicerWebApp/dicom_processor/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.conf import settings
from .models import DicomSeries, ProcessingResult
from .forms import DicomUploadForm
from .utils import (
    generate_heatmap, 
    load_scan_as_3d_volume, 
    get_slice_from_volume_and_save_png, 
    convert_dicom_series_to_nrrd
)
import os
import pydicom
import time
import json
from datetime import datetime

@login_required
def upload_dicom(request):
    if request.method == 'POST':
        form = DicomUploadForm(request.POST)
        files = request.FILES.getlist('dicom_files')
        
        if not files:
            messages.error(request, "Please upload at least one DICOM file.")
            return redirect('upload_dicom')

        if form.is_valid():
            user_dir = os.path.join(settings.MEDIA_ROOT, f'user_{request.user.id}')
            upload_dir = os.path.join(user_dir, f'upload_{int(time.time())}')
            os.makedirs(upload_dir, exist_ok=True)

            for file in files:
                with open(os.path.join(upload_dir, file.name), 'wb+') as dest:
                    for chunk in file.chunks():
                        dest.write(chunk)

            patient_id, series_name, patient_age, patient_gender = 'Unknown', f'Series_{int(time.time())}', '', ''
            wc, ww = 40, 400
            try:
                first_dcm_path = os.path.join(upload_dir, os.listdir(upload_dir)[0])
                ds = pydicom.dcmread(first_dcm_path)
                patient_id = ds.get('PatientID', 'Unknown')
                series_desc = ds.get('SeriesDescription', '')
                study_desc = ds.get('StudyDescription', '')
                now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
                series_name = f"{patient_id}_{series_desc or study_desc or now_str}"
                patient_age = ds.get('PatientAge', '')
                patient_gender = ds.get('PatientSex', '')
                wc_val = ds.get('WindowCenter', wc)
                ww_val = ds.get('WindowWidth', ww)
                wc = float(wc_val[0]) if isinstance(wc_val, pydicom.multival.MultiValue) else float(wc_val)
                ww = float(ww_val[0]) if isinstance(ww_val, pydicom.multival.MultiValue) else float(ww_val)
            except Exception as e:
                messages.warning(request, f"Could not read full DICOM metadata: {e}")

            series = DicomSeries.objects.create(
                user=request.user,
                name=series_name,
                file_path=upload_dir,
                patient_id=patient_id,
                patient_age=patient_age,
                patient_gender=patient_gender,
                window_center=wc,
                window_width=ww
            )
            messages.success(request, f"Successfully uploaded series: '{series.name}'")
            return redirect('process_dicom', series_id=series.id)
    else:
        form = DicomUploadForm()
    return render(request, 'dicom_processor/upload.html', {'form': form})

@login_required
def process_dicom(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    
    if request.method == 'POST':
        print(f"--- Starting processing for Series ID: {series.id} ---")
        
        # NOTE: This assumes your `generate_heatmap` in utils.py returns:
        # (heatmap_directory_path, ece_probability, non_ece_probability)
        heatmap_dir_path, ece_prob, non_ece_prob = generate_heatmap(series.file_path)

        nrrd_dir = os.path.join(settings.MEDIA_ROOT, "nrrd_files")
        os.makedirs(nrrd_dir, exist_ok=True)
        nrrd_path = os.path.join(nrrd_dir, f"user{series.user.id}_series{series.id}.nrrd")
        convert_dicom_series_to_nrrd(series.file_path, nrrd_path)

        volume, _ = load_scan_as_3d_volume(series.file_path)
        slice_counts = {
            'axial': volume.shape[0],
            'coronal': volume.shape[1],
            'sagittal': volume.shape[2]
        } if volume is not None else {}

        # === FIX IS HERE: Saving to the NEW model fields ===
        ProcessingResult.objects.update_or_create(
            dicom_series=series,
            defaults={
                'result_type': 'heatmap_and_prediction',
                'heatmap_file_path': os.path.join(heatmap_dir_path, 'heatmap.nrrd') if heatmap_dir_path else None,
                'nrrd_file_path': nrrd_path,
                'ece_probability': ece_prob if ece_prob is not None else 0.0,
                'non_ece_probability': non_ece_prob if non_ece_prob is not None else 0.0,
                'slice_counts_json': json.dumps(slice_counts)
            }
        )
        messages.success(request, f"Processing complete for '{series.name}'.")
        return redirect('dashboard_series_view', series_id=series.id)

    latest_result = ProcessingResult.objects.filter(dicom_series=series).first()
    return render(request, 'dicom_processor/process.html', {'series': series, 'latest_result': latest_result})

@login_required
def delete_dicom(request, series_id):
    """Handle DICOM deletion requests"""
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    
    if request.method == 'POST':
        series_name = series.name # Get name for message before deleting
        
        # Get the path to the directory to delete
        dicom_dir_path = series.file_path
        
        # Delete the database record first. This will cascade and delete related ProcessingResult.
        series.delete()
        
        # Now, delete the files from the disk
        try:
            if os.path.isdir(dicom_dir_path):
                shutil.rmtree(dicom_dir_path)
                print(f"Successfully deleted directory: {dicom_dir_path}")
        except Exception as e:
            messages.error(request, f"Could not delete files for series '{series_name}'. Please check server permissions. Error: {e}")

        messages.success(request, f"DICOM series '{series_name}' deleted successfully.")
        return redirect('my_uploads')
    
    # If not a POST request, just redirect (or show a confirmation page)
    return redirect('my_uploads')


@login_required
def dashboard_view(request, series_id=None):
    if not series_id:
        latest_series = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date').first()
        if latest_series:
            return redirect('dashboard_series_view', series_id=latest_series.id)
        messages.info(request, "No DICOM series found. Please upload one first.")
        return redirect('upload_dicom')

    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    result = getattr(series, 'processing_result', None)

    if not result:
        messages.warning(request, "This series has not been processed yet. Please process it to view the dashboard.")
        return redirect('process_dicom', series_id=series.id)
    
    # === FIX IS HERE: Reading from the NEW model fields ===
    context = {
        'series': series,
        'processing_result': result,
        'chart_labels': ['Non-ECE', 'ECE'],
        'chart_probabilities': [result.non_ece_probability or 0, result.ece_probability or 0],
        'slice_counts': json.loads(result.slice_counts_json or '{}')
    }
    return render(request, 'dicom_processor/dashboard.html', context)

# ... (The rest of your views: get_slice_url_ajax, get_nrrd_url, get_heatmap_url, etc. remain the same as the previous correct version) ...

@login_required
def get_slice_url_ajax(request):
    series_id = request.GET.get('series_id')
    view_type = request.GET.get('view_type')
    slice_index = int(request.GET.get('slice_index', 0))

    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    volume, _ = load_scan_as_3d_volume(series.file_path)

    if volume is None:
        return JsonResponse({'error': 'Failed to load 3D volume'}, status=500)

    output_dir = os.path.join(settings.MEDIA_ROOT, 'tmp_slices')
    os.makedirs(output_dir, exist_ok=True)
    
    file_prefix = f"user{request.user.id}_series{series.id}_"

    saved_path = get_slice_from_volume_and_save_png(
        volume_3d=volume,
        view_orientation=view_type,
        slice_index=slice_index,
        window_center=series.window_center,
        window_width=series.window_width,
        output_directory=output_dir,
        output_filename_prefix=file_prefix
    )

    if saved_path:
        url = os.path.join(settings.MEDIA_URL, 'tmp_slices', os.path.basename(saved_path))
        return JsonResponse({'success': True, 'slice_url': url})
    else:
        return JsonResponse({'error': 'Failed to generate slice'}, status=500)

@login_required
def get_nrrd_url(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    result = getattr(series, 'processing_result', None)
    
    if result and result.nrrd_file_path and os.path.exists(result.nrrd_file_path):
        url = result.nrrd_file_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL).replace('\\', '/')
        return JsonResponse({'success': True, 'nrrd_url': url})
    return JsonResponse({'error': 'NRRD file not found for this series. Please process the series.'}, status=404)

@login_required
def get_heatmap_url(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    result = getattr(series, 'processing_result', None)
    
    if result and result.heatmap_file_path and os.path.exists(result.heatmap_file_path):
        url = result.heatmap_file_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL).replace('\\', '/')
        return JsonResponse({'success': True, 'heatmap_url': url})
    return JsonResponse({'error': 'Heatmap file not found for this series.'}, status=404)


@login_required
def my_uploads(request):
    series_list = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date')
    return render(request, 'dicom_processor/my_uploads.html', {'series_list': series_list})

def home(request):
    if request.user.is_authenticated:
        latest_series = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date').first()
        if latest_series:
            return redirect('dashboard_series_view', series_id=latest_series.id)
        return redirect('my_uploads') 
    return render(request, 'dicom_processor/home.html')
