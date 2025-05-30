from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import DicomSeries, ProcessingResult
from .forms import DicomUploadForm
import os
from django.conf import settings
import time
from .utils import generate_heatmap  # Import helper
from django.contrib import messages
import pydicom
from .utils import generate_middle_views, generate_all_directional_slices







@login_required
def upload_dicom(request):
    if request.method == 'POST':
        form = DicomUploadForm(request.POST)
        files = request.FILES.getlist('dicom_files')  # Get the list of files from the request
        if len(files) < 1:
            messages.error(request, "Please upload at least one DICOM file.")
            return redirect('upload_dicom')
        elif len(files) < 5:
            messages.warning(request, "Warning: You uploaded very few DICOM files. This may affect results.")


        if form.is_valid() and files:
            user_dir = os.path.join(settings.MEDIA_ROOT, f'user_{request.user.id}')
            os.makedirs(user_dir, exist_ok=True)

            timestamp = int(time.time())
            upload_dir = os.path.join(user_dir, f'upload_{timestamp}')
            os.makedirs(upload_dir, exist_ok=True)

            # Save uploaded files to disk
            saved_paths = []
            for file in files:
                file_path = os.path.join(upload_dir, file.name)
                saved_paths.append(file_path)
                with open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

            # Try reading the first file to extract metadata
            try:
                ds = pydicom.dcmread(saved_paths[0])
                patient_id = ds.get('PatientID', '')
                patient_age = ds.get('PatientAge', '')
                patient_gender = ds.get('PatientSex', '')
            except Exception as e:
                patient_id = ''
                patient_age = ''
                patient_gender = ''
                messages.warning(request, f"Metadata could not be read: {e}")


            series = DicomSeries(
                name=form.cleaned_data['name'],
                user=request.user,
                file_path=upload_dir,
                patient_id=patient_id,
                patient_age=patient_age,
                patient_gender=patient_gender)

            series.save()

            return redirect('process_dicom', series_id=series.id)
    else:
        form = DicomUploadForm()

    return render(request, 'dicom_processor/upload.html', {'form': form})


@login_required
def process_dicom(request, series_id):
    """Handle DICOM processing requests"""
    series = DicomSeries.objects.get(id=series_id)
    
    if request.method == 'POST':
        result_path = generate_heatmap(series.file_path)
        
        result = ProcessingResult.objects.create(
            dicom_series=series,
            result_type='heatmap',
            result_path=result_path
        )
        return redirect('view_result', result_id=result.id)
        
    return render(request, 'dicom_processor/process.html', {'series': series})

@login_required
def delete_dicom(request, series_id):
    """Handle DICOM deletion requests"""
    series = get_object_or_404(DicomSeries, id=series_id, user = request.user)
    
    if request.method == 'POST':
        # Delete the series from the database
        ProcessingResult.objects.filter(dicom_series=series).delete()

        #Delete uploaded dicom files from disk
        if os.path.exists(series.file_path):
            import shutil
            shutil.rmtree(series.file_path)
        #Delete the database record
        series.delete()
        
        messages.success(request, "DICOM series deleted successfully.")
    return redirect('my_uploads')
@login_required
def view_result(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)

    # Determine which view and which slice user requested
    view = request.GET.get('view', 'axial')  # default to axial
    slice_index = int(request.GET.get('slice', 0))

    # Generate slice PNGs if not already done
    output_dir = os.path.join(settings.MEDIA_ROOT, 'tmp')
    generate_all_directional_slices(series.file_path, output_dir, request.user.id, series.id)

    # Count how many slices we have for the selected view
    slice_files = sorted([
        f for f in os.listdir(output_dir)
        if f.startswith(f"user{request.user.id}_series{series.id}_{view}_")
    ])
    total_slices = len(slice_files)

    # Clamp slice index
    slice_index = max(0, min(slice_index, total_slices - 1))

    # Build image path for current slice
    filename = f"user{request.user.id}_series{series.id}_{view}_{slice_index}.png"
    current_slice_url = os.path.join(settings.MEDIA_URL, 'tmp', filename)

    context = {
        'series': series,
        'view': view,
        'slice_index': slice_index,
        'prev_slice': slice_index - 1 if slice_index > 0 else 0,
        'next_slice': slice_index + 1 if slice_index < total_slices - 1 else slice_index,
        'current_slice_url': current_slice_url,
    }

    return render(request, 'dicom_processor/view_result.html', context)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'dicom_processor/home.html')

@login_required
def my_uploads(request):
    series_list = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date')
    return render(request, 'dicom_processor/my_uploads.html', {'series_list': series_list})

@login_required
def dashboard_view(request):
    latest_series = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date').first()
    latest_result = ProcessingResult.objects.filter(dicom_series__user=request.user).order_by('-processed_date').first()

    context = {
        'patient_id': latest_series.patient_id if latest_series else '',
        'patient_age': latest_series.patient_age if latest_series else '',
        'patient_gender': latest_series.patient_gender if latest_series else '',
        'series_id': latest_series.id if latest_series else None,
        'result_id': latest_result.id if latest_result else None,
        'x_axis_labels': list(range(10)),
        'y_axis_values': [0.1, 0.3, 0.5, 0.9, 1.0, 0.8, 0.4, 0.2, 0.1, 0.05],
    }
    return render(request, 'dicom_processor/dashboard.html', context)
