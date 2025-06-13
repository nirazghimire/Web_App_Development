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
from django.http import JsonResponse
from .utils import load_scan_as_3d_volume, get_slice_from_volume_and_save_png, convert_dicom_series_to_nrrd
from datetime import datetime







@login_required
def upload_dicom(request):
    if request.method == 'POST':
        
        form = DicomUploadForm(request.POST) 
        files = request.FILES.getlist('dicom_files')
        
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

            saved_paths = []
            for file in files:
                file_path = os.path.join(upload_dir, file.name)
                saved_paths.append(file_path)
                with open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

           
            # to read its "metadata" (the labels inside the file).
            patient_id = 'UnknownPatient'
            patient_age = ''
            patient_gender = ''
            series_name = f'Series_Upload_{timestamp}' # A default name just in case

            try:
                ds = pydicom.dcmread(saved_paths[0])
                # Get patient info like before
                patient_id = ds.get('PatientID', patient_id)
                patient_age = ds.get('PatientAge', '')
                patient_gender = ds.get('PatientSex', '')
                
                
                series_desc = ds.get('SeriesDescription', '')
                study_desc = ds.get('StudyDescription', '')

                if series_desc:
                    # Best case: use Patient ID and Series Description.
                    series_name = f"{patient_id}_{series_desc}"
                elif study_desc:
                    # Good backup: use Patient ID and Study Description.
                    series_name = f"{patient_id}_{study_desc}"
                else:
                    # Fallback: use Patient ID and the date/time.
                    # This ensures every upload has a unique name.
                    now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
                    series_name = f"{patient_id}_{now_str}"

            except Exception as e:
                messages.warning(request, f"Could not automatically name series from DICOM metadata: {e}. Using a default name.")
                # If reading fails, series_name will remain the default one with the timestamp.

            
            # we now use our automatically generated 'series_name'.
            series = DicomSeries(
                name=series_name, # Use our new automatic name!
                user=request.user,
                file_path=upload_dir,
                patient_id=patient_id,
                patient_age=patient_age,
                patient_gender=patient_gender
            )
            series.save()

            messages.success(request, f"Successfully uploaded and saved series: '{series_name}'")
            return redirect('process_dicom', series_id=series.id)
    else:
        form = DicomUploadForm()

    return render(request, 'dicom_processor/upload.html', {'form': form})


@login_required
def process_dicom(request, series_id):
    
    series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    
    # --- Logic for POST (when the 'Process' button is clicked) ---
    if request.method == 'POST':
        print(f"Starting processing for series ID: {series.id}...")
        heatmap_dir_path, prediction_score = generate_heatmap(series.file_path)
        
        if heatmap_dir_path is not None: 
            print(f"Heatmap generation successful for series ID: {series.id}. Score: {prediction_score}")
            result_file_for_db = os.path.join(heatmap_dir_path, 'heatmap.nrrd') 
            
            try:
                num_slices = len([f for f in os.listdir(series.file_path) if f.lower().endswith(".dcm")])
            except FileNotFoundError:
                num_slices = 0

            # Handle case where prediction_score might be None
            score_to_save = 0.0
            if prediction_score is not None:
                score_to_save = prediction_score
            else:
                print("  > WARNING: Prediction score is None. Saving 0.0 to database.")


            print(f"  > Creating ProcessingResult database entry...")
           
            result = ProcessingResult.objects.create(
                dicom_series=series,
                result_type='heatmap_and_prediction',
                result_file_path=result_file_for_db,
                heatmap_intensity=score_to_save, 
                processed_slices=num_slices 
            )
            print("  > ProcessingResult saved successfully.")
            
            messages.success(request, f"Processing complete for '{series.name}'. Prediction Score: {prediction_score:.2f}" if prediction_score is not None else f"Processing complete for '{series.name}'. Score not available.")
            # Redirect back to the SAME process page, which will now show the new result.
            return redirect('process_dicom', series_id=series.id)
        else:
            # Handle the case where generate_heatmap failed
            print(f"!!! ERROR: Heatmap generation FAILED for series ID: {series.id}. Score returned: {prediction_score}")
            error_message = "Processing failed. Could not generate heatmap"
            if prediction_score is not None:
                error_message += f" (Model score was: {prediction_score:.2f}, but heatmap failed)."
            else:
                error_message += " and model prediction was not available."
            messages.error(request, error_message)
            return redirect('process_dicom', series_id=series.id)
        
   
    # We look for the most recent 'ProcessingResult' linked to this 'series'.
    latest_result = ProcessingResult.objects.filter(dicom_series=series).order_by('-processed_date').first()
    
    
    context = {
        'series': series,
        'latest_result': latest_result # This will be None if no result exists yet
    }
    
    return render(request, 'dicom_processor/process.html', context)





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
        return redirect('dashboard_latest_view')  # Redirect to dashboard if logged in
    return render(request, 'dicom_processor/home.html')

@login_required
def my_uploads(request):
    series_list = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date')
    return render(request, 'dicom_processor/my_uploads.html', {'series_list': series_list})

@login_required
def dashboard_view(request, series_id=None):
    """
    Displays a dashboard with slice views and now also shows the
    latest ECE Score and a bar chart with ECE/Non-ECE probabilities.
    """
    series_to_display = None
    patient_info = {'name': "N/A", 'patient_id': '', 'patient_age': '', 'patient_gender': ''}
    view_data = {
        'axial': {'url': None, 'is_ready': False},
        'coronal': {'url': None, 'is_ready': False},
        'sagittal': {'url': None, 'is_ready': False},
    }
    
    # These variables will hold the data for our new chart. They start empty.
    latest_processing_result = None
    chart_labels = ['Non-ECE', 'ECE'] # Default labels
    chart_probabilities = [0, 0] # Default probabilities

    # --- This part finds the correct DICOM series to show (remains the same) ---
    if series_id:
        series_to_display = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    else:
        series_to_display = DicomSeries.objects.filter(user=request.user).order_by('-uploaded_date').first()
        if series_to_display:
            return redirect('dashboard_series_view', series_id=series_to_display.id)
        else:
            messages.info(request, "No DICOM series found. Please upload a series first.")

    # --- This part populates the data if a series was found ---
    if series_to_display:
        patient_info['name'] = series_to_display.name
        patient_info['patient_id'] = series_to_display.patient_id
        patient_info['patient_age'] = series_to_display.patient_age
        patient_info['patient_gender'] = series_to_display.patient_gender

        # --- NEW LOGIC: Rerun model prediction to get both probabilities for the chart ---
        # Why are we doing this? We need both the ECE and Non-ECE probabilities for the bar chart.
        # The easiest way to get them fresh is to do a quick prediction here.
        # This is a bit inefficient, and a future improvement would be to save both
        # probabilities in the database when the user first clicks "Process".
        # But for now, to get the feature working, this is the most direct way.
        
        # We need the model's output, so we call generate_heatmap but we only need the score part.
        # We pass a special flag to tell it to just give us the prediction, not generate a new heatmap file.
        # Note: We would need to modify 'generate_heatmap' to accept this flag.
        # For simplicity in this step, we will call it and it will generate a temporary heatmap we don't use.
        # A future optimization is to split 'generate_heatmap' into 'get_prediction' and 'create_heatmap' functions.
        
        # For now, let's just find the latest result and simulate having both probabilities from it.
        latest_processing_result = ProcessingResult.objects.filter(
            dicom_series=series_to_display
        ).order_by('-processed_date').first()

        if latest_processing_result:
            # The model gives two probabilities. The one we saved is the higher one.
            # Let's assume the classes are [Non-ECE, ECE].
            # If the score is > 0.5, we can assume it's the ECE probability.
            # This is a simplification based on the model's binary output.
            ece_prob = latest_processing_result.heatmap_intensity
            non_ece_prob = 1.0 - ece_prob
            # We sort them so ECE is always the second bar, matching the label order.
            chart_probabilities = [non_ece_prob, ece_prob]


    # This is the "context" bag we send to the HTML template.
    context = {
        'series': series_to_display,
        'patient_info': patient_info,
        'view_data': view_data, # For the 2D views
        'processing_result': latest_processing_result, 

        # --- NEW CHART DATA ---
        # We're sending the labels and the two probabilities for our new bar chart.
        'chart_labels': chart_labels,
        'chart_probabilities': chart_probabilities,
    }
    return render(request, 'dicom_processor/dashboard.html', context)

@login_required # Only logged-in users can use this helper
def get_slice_url_ajax(request):
    """
    Handles AJAX requests from the dashboard to get the URL for a specific slice.
    It loads the 3D volume and generates the requested slice PNG on-the-fly.

    Why this function?
    This is like the direct phone line for your dashboard's "Next" and "Previous" buttons.
    When a button is clicked, JavaScript on the dashboard calls this phone line.
    This function then does the work to create the *exact* new picture slice needed
    and tells the JavaScript where to find it. This makes the dashboard feel "live"!
    """

   
    series_id_str = request.GET.get('series_id')     # Note 1: Which DICOM series? (e.g., "5")
    view_type = request.GET.get('view_type')         # Note 2: Which view? (e.g., "axial")
    slice_index_str = request.GET.get('slice_index') # Note 3: Which slice number? (e.g., "10")

   
    if not all([series_id_str, view_type, slice_index_str]):
        # 'JsonResponse' is how we send a structured message (like a dictionary) back to JavaScript.
        # 'status=400' means "Bad Request" - the browser didn't send the right info.
        return JsonResponse({'error': 'Missing parameters (series_id, view_type, or slice_index)'}, status=400)

   
    try:
        series_id = int(series_id_str)
        slice_index = int(slice_index_str)
        
        series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
    except ValueError:
        return JsonResponse({'error': 'Invalid series ID or slice index (must be numbers)'}, status=400)
    # Note: get_object_or_404 handles the DicomSeries.DoesNotExist case.

    # Why this check for 'view_type'?
    # We only know how to make "axial", "coronal", or "sagittal" slices right now.
    # If JavaScript asks for something else (like "banana_view"), we send an error.
    if view_type not in ['axial', 'coronal', 'sagittal']:
        return JsonResponse({'error': 'Invalid view type specified (must be axial, coronal, or sagittal)'}, status=400)

    # --- Step 2: Use our "3D Vision" to load the whole scan ---
    # Why 'load_scan_as_3d_volume(series.file_path)'?
    # This is where we use our new superpower! We call the function you just added to 'utils.py'.
    # 'series.file_path' tells it which folder has all the .dcm files for this scan.
    # It will read all those files and stack them up into a 3D block in the server's memory.
    # It gives us back two things:
    #   'volume_3d': The big 3D block of picture data.
    #   'voxel_spacing': How big each tiny 3D dot (voxel) is. We don't use voxel_spacing in *this* function right now, but it's good to have.
    print(f"AJAX: Attempting to load 3D volume for series {series.id} from {series.file_path}...")
    volume_3d, voxel_spacing = load_scan_as_3d_volume(series.file_path)

   
    if volume_3d is None:
        print(f"AJAX: Failed to load 3D volume for series {series.id}.")
        return JsonResponse({'error': 'Failed to load 3D volume data for this series. Check DICOM files.'}, status=500)
    
    print(f"AJAX: 3D Volume loaded. Shape: {volume_3d.shape}. Voxel spacing: {voxel_spacing}")

    
    output_directory_name = 'tmp_on_the_fly_slices' # Name of the sub-folder inside 'media'
    # 'os.path.join(...)': Builds the full path to this folder (e.g., /path/to/project/media/tmp_on_the_fly_slices/)
    output_directory_path = os.path.join(settings.MEDIA_ROOT, output_directory_name)
    # 'os.makedirs(...)': Makes sure this folder exists. If not, it creates it.
    os.makedirs(output_directory_path, exist_ok=True)

    
    output_filename_prefix = f"user{request.user.id}_series{series.id}_"

    
    wc = series.window_center
    ww = series.window_width

    
    print(f"AJAX: Calling 'get_slice_from_volume_and_save_png': view={view_type}, index={slice_index}, WC={wc}, WW={ww}")
    saved_png_full_path = get_slice_from_volume_and_save_png(
        volume_3d=volume_3d,
        view_orientation=view_type,
        slice_index=slice_index,
        window_center=wc,
        window_width=ww,
        output_directory=output_directory_path,
        output_filename_prefix=output_filename_prefix
    )

    # Why 'if saved_png_full_path'?
    # We check if our "Magic Knife" was successful and actually gave us back a file path.
    if saved_png_full_path:
        
        png_filename = os.path.basename(saved_png_full_path)
        
        slice_png_url = os.path.join(settings.MEDIA_URL, output_directory_name, png_filename)
        
        print(f"AJAX: Successfully generated slice. URL to send to browser: {slice_png_url}")

       
        total_slices_for_view = 0
        if volume_3d is not None: # Safety check
            if view_type == "axial":
                total_slices_for_view = volume_3d.shape[0] # Number of slices in depth
            elif view_type == "coronal":
                total_slices_for_view = volume_3d.shape[1] # Number of "rows" (height)
            elif view_type == "sagittal":
                total_slices_for_view = volume_3d.shape[2] # Number of "columns" (width)

       
        return JsonResponse({
            'success': True, 
            'slice_url': slice_png_url,
            'current_slice_index': slice_index, 
            'total_slices': total_slices_for_view, 
            'view_type': view_type
        })
    else: # Why 'else'? This runs if our "Magic Knife" failed to make the picture.
        print(f"AJAX: 'get_slice_from_volume_and_save_png' failed for: view={view_type}, index={slice_index}")
        return JsonResponse({'error': 'Failed to generate or save the slice image on the server.'}, status=500)

@login_required
def get_nrrd_url(request, series_id):
    """
    This is our "Data Waiter" for VTK.js.
    It finds or creates the .nrrd file for a series and sends back its URL.
    """
    print(f"--- Data Waiter received request for series ID: {series_id} ---")
    try:
        series = get_object_or_404(DicomSeries, id=series_id, user=request.user)
        print(f"  > Found series '{series.name}'")
    except Exception:
        return JsonResponse({'error': 'Series not found or not authorized.'}, status=404)

    # We now look for a .nrrd file instead of a .vti file.
    nrrd_directory_name = "nrrd_files" # A dedicated folder for our data
    nrrd_filename = f"user{request.user.id}_series{series.id}.nrrd" # A unique name
    
    nrrd_output_directory = os.path.join(settings.MEDIA_ROOT, nrrd_directory_name)
    full_nrrd_path_on_server = os.path.join(nrrd_output_directory, nrrd_filename)
    
    os.makedirs(nrrd_output_directory, exist_ok=True)
    print(f"  > Checking for NRRD file at: {full_nrrd_path_on_server}")

    if not os.path.exists(full_nrrd_path_on_server):
        print(f"  > NRRD file not found. Calling converter to create it...")
        # We call our new 'convert_dicom_series_to_nrrd' function.
        success = convert_dicom_series_to_nrrd(series.file_path, full_nrrd_path_on_server)
        
        if not success:
            print(f"!!! ERROR: NRRD file generation failed for series {series.id}.")
            return JsonResponse({'error': 'Failed to process DICOM series on the server.'}, status=500)
    else:
        print("  > Found existing NRRD file.")

    # We create the web address (URL) for the .nrrd file.
    nrrd_url = os.path.join(settings.MEDIA_URL, nrrd_directory_name, nrrd_filename)
    
    print(f"  > Sending back success response with URL: {nrrd_url}")
    return JsonResponse({
        'success': True,
        'nrrd_url': nrrd_url # We send back the URL for the NRRD file
    })
