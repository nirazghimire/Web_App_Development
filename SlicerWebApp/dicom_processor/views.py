# SlicerWebApp/dicom_processor/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
import os
import json
import shutil
import traceback
import pydicom

from .models import DicomSeries, ProcessingResult, SurveyResponse
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

def register(request):
    if request.user.is_authenticated:
        return redirect('dicom_processor:home')
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Account created successfully! Welcome, {user.username}.")
            return redirect('dicom_processor:home')
    else:
        form = UserCreationForm()
        
    # We must ensure form elements have bootstrap classes for nice styling
    for field in form.fields.values():
        field.widget.attrs['class'] = 'form-control'
        
    return render(request, 'dicom_processor/register.html', {'form': form})

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

@login_required
def survey_view(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    
    if request.method == "POST":
        SurveyResponse.objects.create(
            user=request.user,
            series=series,
            q1_image_quality=request.POST.get('q1') or None,
            q2_consistency=request.POST.get('q2') or None,
            q3_noise=request.POST.get('q3') or None,
            q4_canal_clear=request.POST.get('q4'),
            q5_confidence_q4=request.POST.get('q5') or None,
            q6_emergency_pathology=request.POST.get('q6'),
            q7_confidence_q6=request.POST.get('q7') or None,
        )
        messages.success(request, "Survey submitted successfully!")
        return redirect('dicom_processor:my_uploads')

    return render(request, 'dicom_processor/survey.html', {'series': series})

# --- File Handling Views ---
@login_required
def upload_dicom(request):
    if request.method == 'POST':
        form = DicomUploadForm(request.POST, request.FILES)
        files = request.FILES.getlist('dicom_files')
        if form.is_valid() and files:
            # --- Check for Duplicates ---
            # Iterate through the first few files to find a valid DICOM with SeriesInstanceUID
            series_uid = ""
            files_to_check = files[:10] # Check first 10 files to avoid performance hit on large uploads
            
            for file_to_check in files_to_check:
                try:
                    # Read the file in memory
                    ds_check = pydicom.dcmread(file_to_check, stop_before_pixels=True, force=True)
                    uid_candidate = getattr(ds_check, "SeriesInstanceUID", "").strip()
                    
                    if uid_candidate:
                        series_uid = uid_candidate
                        break # Stop once we find a valid UID
                except Exception as e:
                     # Not a valid DICOM or read error, continue to next file
                     pass
                finally:
                    # Reset file pointer for the verified file so it can be saved properly
                    file_to_check.seek(0)

            # If we found a UID, check if this user already uploaded it
            if series_uid:
                    existing_series = DicomSeries.objects.filter(user=request.user, series_instance_uid=series_uid).first()
                    if existing_series:
                        messages.error(request, f"This series is already uploaded as a name '{existing_series.name}'")
                        return redirect('dicom_processor:upload_dicom')

            series = DicomSeries.objects.create(
                name="Processing...", user=request.user, 
                patient_id="", patient_age="", patient_gender="", modality="",
                series_instance_uid=series_uid if 'series_uid' in locals() else None
            )
            series_path = os.path.join(settings.MEDIA_ROOT, 'dicom_series', f'series_{series.id}')
            os.makedirs(series_path, exist_ok=True)
            series.file_path = series_path
            series.save(update_fields=['file_path'])
            
            saved_files = []
            for f in files:
                file_dest_path = os.path.join(series_path, f.name)
                with open(file_dest_path, 'wb+') as destination:
                    for chunk in f.chunks():
                        destination.write(chunk)
                saved_files.append(file_dest_path)
            
            # Now scan files to find metadata
            metadata_found = False
            files_to_scan = saved_files[:5] # Scan first 5 files
            
            for file_path in files_to_scan:
                if metadata_found: break
                try:
                    ds = pydicom.dcmread(file_path, stop_before_pixels=True, force=True)
                    
                    # Log all keys to debug
                    print(f"DEBUG: Scanning {os.path.basename(file_path)} - Available Tags: {ds.dir()}")
                    
                    s_desc = getattr(ds, "SeriesDescription", "").strip()
                    p_id = getattr(ds, "PatientID", "").strip()
                    p_name = str(getattr(ds, "PatientName", "")).strip()
                    
                    # Fallback Logic
                    series_name = s_desc
                    if not series_name:
                         if p_id: series_name = f"Scan ({p_id})"
                         elif p_name: series_name = f"Scan ({p_name})"

                    if series_name:
                        series.name = series_name
                        series.patient_id = p_id
                        series.patient_age = getattr(ds, "PatientAge", "")
                        series.patient_gender = getattr(ds, "PatientSex", "")
                        series.modality = getattr(ds, "Modality", "")
                        series.save()
                        print(f"DEBUG: Metadata FOUND in {os.path.basename(file_path)} -> Name: {series_name}")
                        metadata_found = True
                    
                except Exception as e:
                    print(f"DEBUG: Error reading {os.path.basename(file_path)}: {e}")

            if not metadata_found:
                 print("DEBUG: No usable metadata found in first 5 files.")
                 series.name = "Unnamed Series (No Metadata)"
                 series.save()

            return redirect('dicom_processor:my_uploads')
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
        return redirect('dicom_processor:my_uploads')
    return render(request, 'dicom_processor/my_uploads.html')

# --- Processing Views ---
@login_required
@login_required
def process_dicom(request, series_id):
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.POST
        
        try:
            print(f"--- Starting processing for Series ID: {series.id} ---")
            
            # Generate AI heatmap and get ECE probability
            heatmap_vti_path, ece_probability = generate_heatmap(series.file_path)
            
            # Convert DICOM to NRRD for volume viewing
            nrrd_dir = os.path.join(settings.MEDIA_ROOT, "nrrd_files")
            os.makedirs(nrrd_dir, exist_ok=True)
            nrrd_path = os.path.join(nrrd_dir, f"user{series.user.id}_series{series.id}.nrrd")
            convert_dicom_series_to_nrrd(series.file_path, nrrd_path)
            
            # Get slice counts
            volume, _, _ = load_scan_as_3d_volume(series.file_path)
            slice_counts = {'axial': volume.shape[0], 'coronal': volume.shape[1], 'sagittal': volume.shape[2]} if volume is not None else {}
            
            # Save processing result
            ProcessingResult.objects.update_or_create(
                dicom_series=series,
                defaults={
                    'result_type': 'heatmap_and_prediction',
                    'heatmap_vti_path': heatmap_vti_path,
                    'nrrd_file_path': nrrd_path,
                    'ece_probability': ece_probability if ece_probability is not None else 0.0,
                    'non_ece_probability': (1.0 - ece_probability) if ece_probability is not None else 1.0,
                    'slice_counts_json': json.dumps(slice_counts)
                }
            )
            
            if is_ajax:
                from django.urls import reverse
                target_url = reverse('dicom_processor:dashboard_series_view', kwargs={'series_id': series.id})
                return JsonResponse({'success': True, 'redirect_url': target_url})
            else:
                messages.success(request, f"Processing complete for '{series.name}'.")
                return redirect('dicom_processor:dashboard_series_view', series_id=series.id)
        
        except Exception as e:
            error_msg = str(e)
            print(f"Processing Error: {error_msg}")
            traceback.print_exc()
            
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg}, status=500)
            else:
                messages.error(request, f"Processing failed: {error_msg}")
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
    """AJAX view to return the heatmap VTI file URL."""
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

# --- SECURE MEDIA SERVE ---
@login_required
def secure_media_serve(request, path):
    """
    Intercepts media requests to check authentication, 
    then tells Nginx to serve the file internally.
    """
    response = HttpResponse()
    response['X-Accel-Redirect'] = f'/protected_media/{path}'
    return response