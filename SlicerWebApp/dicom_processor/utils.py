import os
import numpy as np
import pydicom
from django.conf import settings
import matplotlib.pyplot as plt
import vtk
import json
import uuid

import SimpleITK as sitk
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

# TensorFlow imports for AI model
import tensorflow as tf
from tensorflow.keras.layers import Conv3D
from skimage.transform import resize


def get_model():
    """
    Loads the pre-trained 3D CNN model for ECE prediction.
    """
    checkpoint_dir = os.path.join(settings.BASE_DIR, 'dicom_processor', 'checkpoint_v2_1')
    model_path = os.path.join(checkpoint_dir, 'weights-improvement_v2_1.keras')
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at: {model_path}")
    
    print(f"--- Loading model from: {model_path} ---")
    model = tf.keras.models.load_model(model_path)
    return model


def generate_heatmap(dicom_directory):
    """
    Generates a Grad-CAM heatmap for ECE detection visualization.
    
    Args:
        dicom_directory: Path to the DICOM series directory.
        
    Returns:
        tuple: (heatmap_vti_path, ece_probability) or (None, None) on failure.
    """
    print(f"--- Starting Heatmap Generation for: {dicom_directory} ---")
    
    if not os.path.exists(dicom_directory):
        print(f"Error: Directory not found: {dicom_directory}")
        return None, None

    # === Step 1: Load DICOM with SimpleITK (preserves geometry) ===
    try:
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(dicom_directory)
        if not dicom_names:
            print("Error: No DICOM files found.")
            return None, None
        reader.SetFileNames(dicom_names)
        sitk_original = reader.Execute()
        print(f"Volume loaded. Size: {sitk_original.GetSize()}")
    except Exception as e:
        print(f"Error reading DICOM: {e}")
        return None, None

    # === Step 2: Preprocess for Model ===
    volume_np = sitk.GetArrayFromImage(sitk_original)  # (z, y, x)
    volume_xyz = np.transpose(volume_np, (2, 1, 0))     # (x, y, z)
    
    target_shape = (90, 90, 25)
    volume_resized = resize(volume_xyz, target_shape, preserve_range=True, anti_aliasing=True)
    
    # Normalize to 0-1
    v_min, v_max = volume_resized.min(), volume_resized.max()
    if v_max > v_min:
        volume_norm = (volume_resized - v_min) / (v_max - v_min)
    else:
        volume_norm = volume_resized
    
    input_tensor = np.expand_dims(volume_norm, axis=(0, -1))  # (1, 90, 90, 25, 1)

    # === Step 3: Load Model ===
    try:
        model = get_model()
    except Exception as e:
        print(f"Model loading failed: {e}")
        return None, None

    # Find the last Conv3D layer
    last_conv_layer_name = None
    for layer in reversed(model.layers):
        if isinstance(layer, Conv3D):
            last_conv_layer_name = layer.name
            break
    
    if not last_conv_layer_name:
        print("Error: No Conv3D layer found in model.")
        return None, None
    print(f"Using conv layer: {last_conv_layer_name}")

    # === Step 4: Grad-CAM ===
    grad_model = tf.keras.models.Model(
        [model.inputs],
        [model.get_layer(last_conv_layer_name).output, model.output]
    )

    with tf.GradientTape() as tape:
        outputs = grad_model(input_tensor)
        conv_outputs = outputs[0]
        predictions = outputs[1]
        
        # Handle list output format
        if isinstance(predictions, list):
            predictions = predictions[0]
        
        # Flatten and get prediction
        preds_flat = tf.reshape(predictions, (1, -1))
        pred_index = tf.argmax(preds_flat[0])
        ece_probability = float(preds_flat[0, 1])  # Class 1 = ECE positive
        
        loss = preds_flat[:, pred_index]

    grads = tape.gradient(loss, conv_outputs)
    pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2, 3))
    
    conv_outputs = conv_outputs[0]
    heatmap = tf.reduce_sum(tf.multiply(pooled_grads, conv_outputs), axis=-1)
    heatmap = tf.maximum(heatmap, 0)  # ReLU
    
    max_val = tf.reduce_max(heatmap)
    if max_val > 0:
        heatmap = heatmap / max_val
    
    heatmap_np = heatmap.numpy()
    print(f"Raw heatmap shape: {heatmap_np.shape}")

    # === Step 5: Resample to Original Geometry ===
    # The heatmap is in (x, y, z) order; SITK expects (z, y, x)
    heatmap_zyx = np.transpose(heatmap_np, (2, 1, 0))
    sitk_heatmap = sitk.GetImageFromArray(heatmap_zyx.astype(np.float32))
    
    # Set the heatmap to cover the same physical space as the original
    sitk_heatmap.SetOrigin(sitk_original.GetOrigin())
    sitk_heatmap.SetDirection(sitk_original.GetDirection())
    
    orig_size = sitk_original.GetSize()
    orig_spacing = sitk_original.GetSpacing()
    heat_size = sitk_heatmap.GetSize()
    
    new_spacing = [
        (orig_size[0] * orig_spacing[0]) / heat_size[0],
        (orig_size[1] * orig_spacing[1]) / heat_size[1],
        (orig_size[2] * orig_spacing[2]) / heat_size[2]
    ]
    sitk_heatmap.SetSpacing(new_spacing)
    
    # Resample to match original grid
    print("Resampling heatmap to match original resolution...")
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(sitk_original)
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetDefaultPixelValue(0)
    resampler.SetOutputPixelType(sitk.sitkFloat32)
    sitk_heatmap_resampled = resampler.Execute(sitk_heatmap)

    # === Step 6: Masking & Thresholding ===
    heatmap_arr = sitk.GetArrayFromImage(sitk_heatmap_resampled)
    original_arr = sitk.GetArrayFromImage(sitk_original)

    # 1. Anatomical Masking (Remove Air)
    # Air is approx -1000 HU. We use -700 as a safe threshold to include skin/soft tissue but exclude outside air.
    # checking shapes just in case, though they should be identical due to resampling
    if heatmap_arr.shape == original_arr.shape:
        print("Applying anatomical mask (threshold > -700 HU)...")
        mask = original_arr > -700
        heatmap_arr = heatmap_arr * mask
    else:
        print(f"Warning: Shape mismatch (Heatmap: {heatmap_arr.shape} vs Original: {original_arr.shape}). Skipping mask.")

    # 2. Threshold low confidence values (Noise Reduction)
    # We still keep a small threshold to clean up very low model activations inside the body
    threshold = np.percentile(heatmap_arr[heatmap_arr > 0], 10) if np.any(heatmap_arr > 0) else 0
    heatmap_arr[heatmap_arr < threshold] = 0
    
    # Rescale to 0-255 for visualization
    if heatmap_arr.max() > 0:
        heatmap_arr = (heatmap_arr / heatmap_arr.max() * 255).astype(np.uint8)
    else:
        heatmap_arr = heatmap_arr.astype(np.uint8)

    # === Step 7: Save as VTI ===
    # heatmap_arr is (z,y,x) from SimpleITK. numpy.ravel() iterates x-fastest, which matches VTK's expectation.
    # DO NOT TRANSPOSE to (x,y,z) or the strides will be wrong!
    flat_data = np.ascontiguousarray(heatmap_arr).ravel()
    
    vtk_data_array = numpy_to_vtk(num_array=flat_data, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    
    vtk_img = vtk.vtkImageData()
    dims = sitk_heatmap_resampled.GetSize()
    vtk_img.SetDimensions(dims[0], dims[1], dims[2])
    vtk_img.SetSpacing(sitk_heatmap_resampled.GetSpacing())
    vtk_img.SetOrigin(sitk_heatmap_resampled.GetOrigin())
    vtk_img.SetDirectionMatrix(sitk_heatmap_resampled.GetDirection())
    vtk_img.GetPointData().SetScalars(vtk_data_array)
    
    # Save to file
    save_dir = os.path.join(settings.MEDIA_ROOT, 'heatmaps_vti', str(uuid.uuid4()))
    os.makedirs(save_dir, exist_ok=True)
    heatmap_vti_path = os.path.join(save_dir, 'heatmap.vti')
    
    writer = vtk.vtkXMLImageDataWriter()
    writer.SetFileName(heatmap_vti_path)
    writer.SetInputData(vtk_img)
    writer.Write()
    
    print(f"Heatmap saved to: {heatmap_vti_path}")
    print(f"ECE Probability: {ece_probability:.4f}")
    
    return heatmap_vti_path, ece_probability




def convert_dicom_series_to_nrrd(dicom_directory_path, output_nrrd_path):
    """
    Reads a directory of DICOM slices, combines them into a single 3D volume,
    and saves the volume as a .nrrd file.
    """
    print(f"Starting NRRD conversion for directory: {dicom_directory_path}")
    try:
        series_filenames = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(dicom_directory_path)
        if not series_filenames:
            print(f"!!! ERROR: No DICOM files found in: {dicom_directory_path}")
            return False
        
        series_reader = sitk.ImageSeriesReader()
        series_reader.SetFileNames(series_filenames)
        image_3d = series_reader.Execute()
        
        sitk.WriteImage(image_3d, output_nrrd_path)
        print(f"  > NRRD file written successfully to {output_nrrd_path}")
        return True
    except Exception as e:
        print(f"!!! An unexpected error occurred during DICOM to NRRD conversion: {e}")
        return False

def convert_dicom_to_volume(dicom_series_path, output_filename_base="volume"):
    """
    Reads a DICOM series, converts it to a 3D image volume, and saves it
    as a .vti file (VTK's native format).

    Args:
        dicom_series_path (str): The directory containing the DICOM files.
        output_filename_base (str): Base name for the output .vti file (without extension).

    Returns:
        str: The full path to the generated .vti file, or None if failed.
    """
    output_filename = f"{output_filename_base}.vti"

    # Check if input path exists and is directory
    if not os.path.isdir(dicom_series_path):
        print(f"[ERROR] Provided path '{dicom_series_path}' is not a valid directory.")
        return None

    try:

       # Create vtkDICOMImageReader and read the series
        reader = vtk.vtkDICOMImageReader()
        reader.SetDirectoryName(dicom_series_path)
        reader.Update()

        image_data = reader.GetOutput()
        if image_data is None:
            print("[ERROR] Failed to read DICOM series with vtkDICOMImageReader.")
            return None

        print(f"[INFO] DICOM series read successfully. Image dimensions: {image_data.GetDimensions()}")

        # Prepare output directory
        output_directory = os.path.join(settings.MEDIA_ROOT, 'volumes')
        os.makedirs(output_directory, exist_ok=True)
        print(f"[INFO] Output directory verified/created: {output_directory}")

        # Define output path
        output_path = os.path.join(output_directory, output_filename)

        # Write to .vti file using vtkXMLImageDataWriter
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetFileName(output_path)
        writer.SetInputData(image_data)
        success = writer.Write()
        if not success:
            print(f"[ERROR] Failed to write .vti file to '{output_path}'.")
            return None

        # Verify file write success
        if not os.path.isfile(output_path):
            print(f"[ERROR] Output file '{output_path}' does not exist after writing.")
            return None
        if os.path.getsize(output_path) == 0:
            print(f"[ERROR] Output file '{output_path}' is empty.")
            return None

        print(f"[SUCCESS] Converted DICOM series to volume file: '{output_path}'")
        return output_path

    except Exception as e:
        print(f"[EXCEPTION] Error during DICOM to VTI conversion: {str(e)}")
        return None


def apply_windowing(img, window_center, window_width):
    lower = window_center - (window_width / 2)
    upper = window_center + (window_width / 2)
    img = np.clip(img, lower, upper)
    img = (img - lower) / (upper - lower) * 255.0
    return img.astype(np.uint8)

def load_dicom_image(dicom_file):
    ds = pydicom.dcmread(dicom_file)
    img = ds.pixel_array.astype(np.float32)
    img *= getattr(ds, 'RescaleSlope', 1)
    img += getattr(ds, 'RescaleIntercept', 0)

    wc = ds.WindowCenter if hasattr(ds, 'WindowCenter') else 40
    ww = ds.WindowWidth if hasattr(ds, 'WindowWidth') else 400
    if isinstance(wc, pydicom.multival.MultiValue): wc = wc[0]
    if isinstance(ww, pydicom.multival.MultiValue): ww = ww[0]
    return apply_windowing(img, wc, ww)

def create_volume_from_dicom(directory):
    slices = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith('.dcm'):
            path = os.path.join(directory, fname)
            slices.append(load_dicom_image(path))
    return np.stack(slices, axis=0)


def generate_views(dicom_folder, output_folder):
    """Generate axial, sagittal, and coronal PNGs from a folder of .dcm files."""
    slices = []
    for filename in sorted(os.listdir(dicom_folder)):
        if filename.lower().endswith(".dcm"):
            ds = pydicom.dcmread(os.path.join(dicom_folder, filename))
            slices.append(ds.pixel_array)
    
    volume = np.stack(slices, axis=0)

    z = volume.shape[0] // 2
    y = volume.shape[1] // 2
    x = volume.shape[2] // 2

    views = {
        'axial.png':     volume[z, :, :],
        'coronal.png':   volume[:, y, :],
        'sagittal.png':  volume[:, :, x],
    }

    os.makedirs(output_folder, exist_ok=True)
    for name, img in views.items():
        plt.imsave(os.path.join(output_folder, name), img, cmap='gray')
    
    return {
        'axial': os.path.join(output_folder, 'axial.png'),
        'coronal': os.path.join(output_folder, 'coronal.png'),
        'sagittal': os.path.join(output_folder, 'sagittal.png'),
    }


def generate_middle_views(dicom_folder, output_folder, user_id, series_id):
    import os
    import pydicom
    import numpy as np

    slices = []
    for filename in sorted(os.listdir(dicom_folder)):
        if filename.lower().endswith(".dcm"):
            ds = pydicom.dcmread(os.path.join(dicom_folder, filename))
            slices.append(ds.pixel_array)

    volume = np.stack(slices, axis=0)

    z = volume.shape[0] // 2
    y = volume.shape[1] // 2
    x = volume.shape[2] // 2

    os.makedirs(output_folder, exist_ok=True)

    paths = {}
    for name, img in {
        'axial':    volume[z, :, :],
        'coronal':  volume[:, y, :],
        'sagittal': volume[:, :, x],
    }.items():
        filename = f"user_{user_id}_series_{series_id}_{name}.png"
        full_path = os.path.join(output_folder, filename)
        plt.imsave(full_path, img, cmap='gray')
        paths[name] = os.path.join('/media/tmp', filename)

    return paths

def generate_all_directional_slices(dicom_folder, output_folder, user_id, series_id):
    """
    Converts all .dcm files into a 3D volume, then saves every slice
    in axial, coronal, and sagittal directions as .png files.
    """
    # 1. Stack all .dcm slices into a 3D cube
    slices = []
    for filename in sorted(os.listdir(dicom_folder)):
        if filename.lower().endswith(".dcm"):
            ds = pydicom.dcmread(os.path.join(dicom_folder, filename))
            slices.append(ds.pixel_array)

    volume = np.stack(slices, axis=0)  # shape: (depth, height, width)

    os.makedirs(output_folder, exist_ok=True)

    total = {
        'axial':    volume.shape[0],
        'coronal':  volume.shape[1],
        'sagittal': volume.shape[2]
    }

    for view, count in total.items():
        for i in range(count):
            if view == 'axial':
                img = volume[i, :, :]
            elif view == 'coronal':
                img = volume[:, i, :]
            elif view == 'sagittal':
                img = volume[:, :, i]
            else:
                continue

            # Normalize image to 0-255
            img = img.astype(np.float32)
            img -= np.min(img)
            img /= np.max(img) if np.max(img) > 0 else 1
            img *= 255
            img = img.astype(np.uint8)

            filename = f"user{user_id}_series{series_id}_{view}_{i}.png"
            full_path = os.path.join(output_folder, filename)
            plt.imsave(full_path, img, cmap='gray')




def load_scan_as_3d_volume(dicom_series_directory_path):
    """
    Reads a series of DICOM files from the specified directory, sorts them by InstanceNumber,
    and stacks them into a 3D numpy array(Volume)."""
    print("Attemting to Load DICOM Series from: ", dicom_series_directory_path)
    slices_data =[]
    dicom_files_path = []

    for filename in os.listdir(dicom_series_directory_path):
        if filename.lower().endswith('.dcm'):
            dicom_files_path.append(os.path.join(dicom_series_directory_path, filename))

    if not dicom_files_path:
        print(f"Error: No .dcm files found in directory: {dicom_series_directory_path}")
        raise ValueError("No DICOM files found in the specified directory.")

    "Lets sort the files by InstanceNumber to ensure correct stacking"

    slice_objects = []
    for file_path in dicom_files_path:
        try:
            dicom_slice = pydicom.dcmread(file_path)
            slice_objects.append(dicom_slice)
        except Exception as e:
            print(f"Warning: Could not read DICOM file {file_path}: {e}")
            raise ValueError(f"Could not read DICOM file {file_path}: {e}")
        

    # if we could not read any of the files , we raise an error
    if not slice_objects:
        print(f"Error: No valid DICOM files found in directory: {dicom_series_directory_path}")
        raise ValueError("No valid DICOM files found in the specified directory.")
    

    # let's sort the slices by InstanceNumber
    try:
        slice_objects.sort(key= lambda slice_obj: int(slice_obj.get("InstanceNumber", 0)) )
        print(f"Sorted {len(slice_objects)} slices by InstanceNumber)")
    except Exception as e:
        #if sorting by InstanceNumber fails, we can sort by filename
        print(f"Warning: Could not sort slices by InstanceNumber: {e}. Sorting by filename instead.")
        pass

    #Extracting pixel data from the sorted slices
    for dicom_slice in slice_objects:
        try:
            pixel_array = dicom_slice.pixel_array
            slices_data.append(pixel_array)
        except Exception as e:
            print(f"Warning: Could not extract pixel data from DICOM slice: {e}")
            raise ValueError(f"Could not extract pixel data from DICOM slice: {e}")
    
    pixel_spacing = [1.0,1.0]  # Default spacing if not found
    slice_thickness = 1.0  # Default thickness if not found


    if slice_objects:
        #pixel_spacing 
        first_slice = slice_objects[0]
        ps = first_slice.get('PixelSpacing', None)
        if ps:
            pixel_spacing = [float(ps[0]), float(ps[1])]
            print(f"Pixel spacing found: {pixel_spacing}")
        else:
            print("Warning: Pixel spacing not found in DICOM metadata, using default values [1.0,1.0].")


    # slice_thickness
        st = first_slice.get('SliceThickness', None)
        if st:
            slice_thickness = float(st)
            print(f"Slice thickness found: {slice_thickness}")
        else:
            sbs = first_slice.get('SpacingBetweenSlices', None)
            if sbs:
                slice_thickness
                print(f"Using SpacingBetweenSlices for slice thickness: {slice_thickness}")
            else:   
                print("Warning: Slice thickness not found in DICOM metadata, using default value 1.0.")


    voxel_spacing = [pixel_spacing[0], pixel_spacing[1], slice_thickness] # col_spacing, row_spacing, slice_thickness


    # Stack the slices into a 3D numpy array
    try:
        volume = np.stack(slices_data, axis=0)  # shape (rows, cols, slices)
        
        # Extract Origin (ImagePositionPatient) from the first slice
        origin = [0.0, 0.0, 0.0]
        if slice_objects:
            first_slice = slice_objects[0]
            ipp = first_slice.get("ImagePositionPatient", None)
            if ipp:
                origin = [float(ipp[0]), float(ipp[1]), float(ipp[2])]
                print(f"Origin found: {origin}")
            else:
                print("Warning: ImagePositionPatient not found, using default origin [0.0, 0.0, 0.0]")
        
        print(f"Successfully stacked {len(slices_data)} as 3D volume with shape: {volume.shape}")
        return volume, voxel_spacing, origin
    except ValueError as e:
        print(f"Error stacking slices into a 3D volume: {e}")
        raise ValueError(f"Error stacking slices into a 3D volume: {e}")
        return None, None, None
    

def get_slice_from_volume_and_save_png(volume_3d, view_orientation, slice_index, 
                                       window_center, window_width, 
                                       output_directory, output_filename_prefix):
    
    print(f"Extracting slice: orientation={view_orientation}, index={slice_index} from volume of shape {volume_3d.shape}")

    # Why these checks?
    # We need to make sure we have everything we need to work.
    if volume_3d is None:
        print("Error: Input 3D volume is None.")
        return None
    if not output_directory or not output_filename_prefix:
        print("Error: Output directory or filename prefix not provided.")
        return None

    

    slice_2d = None # This will hold our cut 2D picture data.

    if view_orientation == "axial":
       
        if 0 <= slice_index < volume_3d.shape[0]:
           
            slice_2d = volume_3d[slice_index, :, :]
            print(f"  Extracted axial slice {slice_index}. Shape: {slice_2d.shape}")
        else:
            print(f"  Error: Axial slice_index {slice_index} is out of bounds for volume depth {volume_3d.shape[0]}.")
            return None

    elif view_orientation == "coronal":
        # Coronal view means slicing through the 'height' dimension (axis 1).
        if 0 <= slice_index < volume_3d.shape[1]: # Check against height
           
            slice_2d = volume_3d[:, slice_index, :]
            print(f"  Extracted coronal slice {slice_index}. Shape: {slice_2d.shape}")
        else:
            print(f"  Error: Coronal slice_index {slice_index} is out of bounds for volume height {volume_3d.shape[1]}.")
            return None

    elif view_orientation == "sagittal":
        # Sagittal view means slicing through the 'width' dimension (axis 2).
        if 0 <= slice_index < volume_3d.shape[2]: # Check against width
            
            slice_2d = volume_3d[:, :, slice_index]
            print(f"  Extracted sagittal slice {slice_index}. Shape: {slice_2d.shape}")
        else:
            print(f"  Error: Sagittal slice_index {slice_index} is out of bounds for volume width {volume_3d.shape[2]}.")
            return None
    else:
        print(f"Error: Unknown view_orientation '{view_orientation}'. Must be 'axial', 'coronal', or 'sagittal'.")
        return None

    
    # If we didn't manage to cut a slice (maybe because of a wrong orientation name), we stop.
    if slice_2d is None: # Should have been caught by orientation check, but good to be safe.
        return None

    
    # Ensure slice_2d is float32 for apply_windowing if it's not already
    if slice_2d.dtype != np.float32:
        slice_2d_float = slice_2d.astype(np.float32)
    else:
        slice_2d_float = slice_2d
        
    windowed_slice = apply_windowing(slice_2d_float, window_center, window_width)
    print(f"  Applied windowing. Resulting dtype: {windowed_slice.dtype}, shape: {windowed_slice.shape}")


    
    os.makedirs(output_directory, exist_ok=True)
    
    
    # We create a unique filename for this specific slice.
    # Example: "user1_series5_axial_10.png"
    output_filename = f"{output_filename_prefix}{view_orientation}_{slice_index}.png"
    full_output_path = os.path.join(output_directory, output_filename)

    
    try:
        
        plt.imsave(full_output_path, windowed_slice, cmap='gray', vmin=0, vmax=255)
        print(f"  Successfully saved PNG: {full_output_path}")
        return full_output_path # Give back the full path to where we saved the picture.
    except Exception as e:
        print(f"  Error saving PNG image {full_output_path}: {e}")
        return None

# Add this entire function to the bottom of your dicom_processor/utils.py file

def convert_nrrd_to_vti(nrrd_file_path, output_filename_base="heatmap_volume"):
    """
    Reads an NRRD file, converts it to a VTK image volume, and saves it
    as a .vti file (VTK's XML format).

    Args:
        nrrd_file_path (str): The full path to the input .nrrd file.
        output_filename_base (str): Base name for the output .vti file.

    Returns:
        str: The full path to the generated .vti file, or None if failed.
    """
    print(f"[INFO] Starting NRRD to VTI conversion for: {nrrd_file_path}")
    
    if not os.path.isfile(nrrd_file_path):
        print(f"[ERROR] NRRD file not found at '{nrrd_file_path}'.")
        return None

    try:
        # Create a vtkNrrdReader
        reader = vtk.vtkNrrdReader()
        reader.SetFileName(nrrd_file_path)
        reader.Update()

        image_data = reader.GetOutput()
        if image_data is None:
            print("[ERROR] Failed to read NRRD file with vtkNrrdReader.")
            return None
        
        print(f"[INFO] NRRD file read successfully. Image dimensions: {image_data.GetDimensions()}")

        # Prepare output directory for the VTI file
        output_directory = os.path.join(settings.MEDIA_ROOT, 'heatmaps_vti')
        
        output_filename = f"{output_filename_base}.vti"
        output_path = os.path.join(output_directory, output_filename)
        
        # Create full output path including subdirectories
        output_file_dir = os.path.dirname(output_path)
        os.makedirs(output_file_dir, exist_ok=True)

    except Exception as e:
        print(f"[EXCEPTION] Error during NRRD to VTI conversion: {str(e)}")
        return None
