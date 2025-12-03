import os
import numpy as np
import pydicom
from skimage.transform import resize
from tensorflow.keras.models import Model, load_model
from tensorflow.keras.layers import Input, Conv3D, MaxPooling3D, Dense, GlobalAveragePooling3D, Dropout, Activation
import uuid
from django.conf import settings
import matplotlib.pyplot as plt
import tensorflow as tf
import vtk
import json


import os
import SimpleITK as sitk
from django.conf import settings 
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

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


def get_model(input_shape=(90, 90, 25, 1), num_classes=2):
    """
    Defines the 3D CNN model architecture, loads weights from a checkpoint, 
    and returns the compiled model.
    """
    
    # --- Define Model Architecture ---
    i = Input(shape=input_shape)
    
    # Block 1
    x = Conv3D(32, (3, 3, 3), activation='relu', padding='same', name='conv3d_1')(i)
    x = MaxPooling3D(pool_size=(2, 2, 2), name='maxpool3d_1')(x)
    
    # Block 2
    x = Conv3D(64, (3, 3, 3), activation='relu', padding='same', name='conv3d_2')(x)
    x = MaxPooling3D(pool_size=(2, 2, 2), name='maxpool3d_2')(x)
    
    # Block 3
    x = Conv3D(128, (3, 3, 3), activation='relu', padding='same', name='conv3d_3')(x)
    x = MaxPooling3D(pool_size=(2, 2, 2), name='maxpool3d_3')(x)

    # Global Average Pooling and Dense Layers
    x = GlobalAveragePooling3D(name='global_avg_pool')(x)
    x = Dense(256, activation='relu', name='dense_1')(x)
    x = Dropout(0.3, name='dropout_1')(x)
    x = Dense(num_classes, name='dense_output')(x)
    x = Activation('softmax', name='activation_softmax')(x)
    
    model = Model(inputs=i, outputs=x)
    
    # --- Load Weights from Checkpoint ---
    checkpoint_dir = os.path.join(settings.BASE_DIR, 'dicom_processor', 'checkpoint_v2_1')
    latest_checkpoint = tf.train.latest_checkpoint(checkpoint_dir)
    
    if latest_checkpoint:
        print(f"--- Loading weights from checkpoint: {latest_checkpoint} ---")
        model.load_weights(latest_checkpoint)
    else:
        raise FileNotFoundError("No model checkpoint found. Aborting heatmap generation.")

    return model

def generate_heatmap(dicom_directory):
    """
    Generates a Grad-CAM style heatmap, saves it directly as a .vti file,
    and returns the model's prediction score.
    """
    print("--- Starting generate_heatmap ---")
    
    # --- Part 1: Load and Prepare Volume ---
    # Use load_scan_as_3d_volume to get volume, spacing, and origin
    try:
        volume, voxel_spacing, origin = load_scan_as_3d_volume(dicom_directory)
    except Exception as e:
        print(f"Error loading volume: {e}")
        return None, None

    if volume is None or volume.size == 0:
        return None, None 

    # volume shape is (depth, height, width) -> (z, y, x)
    # We need to transpose it to (width, height, depth) -> (x, y, z) for processing
    original_shape = volume.shape 
    volume_transposed = np.transpose(volume, (2, 1, 0)) # (width, height, depth)
    
    # Resize for model input
    correct_shape = (90, 90, 25)
    resized_volume = resize(volume_transposed, correct_shape, anti_aliasing=True)
    
    input_vol_for_model = np.expand_dims(resized_volume, axis=(0, -1))

    # --- Part 2: Load Model and Get Prediction (Same as before) ---
    model = get_model()
    if model is None:
        print("!!! ERROR: Failed to get the model. Aborting heatmap generation. !!!")
        return None, None

    # --- Dynamically find the last convolutional layer ---
    last_conv_layer_name = None
    for layer in reversed(model.layers):
        if isinstance(layer, Conv3D):
            last_conv_layer_name = layer.name
            break
            
    if last_conv_layer_name is None:
        print("!!! ERROR: Could not find a Conv3D layer in the model. !!!")
        return None, None
    print(f"--- Using last convolutional layer for Grad-CAM: {last_conv_layer_name} ---")

    grad_model = tf.keras.models.Model(
        [model.inputs], [model.get_layer(last_conv_layer_name).output, model.output]
    )

    # --- Part 3: Generate Heatmap as NumPy Array (Same as before) ---
    with tf.GradientTape() as tape:
        conv_output, preds = grad_model(input_vol_for_model)
        pred_index = tf.argmax(preds[0])
        prediction_score_value = float(preds[0][pred_index].numpy())
        class_channel = preds[:, pred_index]

    grads = tape.gradient(class_channel, conv_output)
    pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2, 3))
    
    conv_output = conv_output[0]
    heatmap_np = np.zeros(conv_output.shape[0:3], dtype=np.float32)

    for i, w in enumerate(pooled_grads):
        heatmap_np += w * conv_output[:, :, :, i]

    heatmap_np = np.maximum(heatmap_np, 0)
    if np.max(heatmap_np) > 0:
        heatmap_np = heatmap_np / np.max(heatmap_np)
    
    # --- OPTIMIZATION: Convert to Uint8 to save space ---
    heatmap_uint8_np = (heatmap_np * 255).astype(np.uint8)

    # --- Part 4: Resize and Save Heatmap Directly to VTI ---
    # We want the heatmap to match the original volume's physical space.
    # The original volume (transposed) has shape (width, height, depth).
    # We will resize the heatmap to a scaled version of this, but keep the aspect ratio.
    
    original_dims = volume_transposed.shape # (x, y, z)
    max_xy_dim = max(original_dims[0], original_dims[1])
    
    scale = 1.0
    if max_xy_dim > 256: # Cap at 256 for performance
        scale = 256.0 / max_xy_dim
        
    new_dims = (
        int(original_dims[0] * scale),
        int(original_dims[1] * scale),
        original_dims[2] # Keep original depth
    )
    
    print(f"--- Resizing heatmap from {heatmap_uint8_np.shape} to {new_dims} ---")
    # Use preserve_range=True for integer-based resizing
    heatmap_resized_np = resize(heatmap_uint8_np, new_dims, anti_aliasing=True, preserve_range=True)
    
    # The resize function might return float, convert back to uint8
    heatmap_final_np = heatmap_resized_np.astype(np.uint8)
    
    # IMPORTANT: VTK expects data in (x, y, z) order for StructuredPoints/ImageData,
    # but the numpy array layout in memory should be such that when raveled, it matches VTK's expectation.
    # VTK iterates x fastest, then y, then z.
    # Numpy defaults to C-order (z, y, x) if we think of indices as [z][y][x].
    # However, our volume_transposed is (x, y, z).
    # To make it compatible with VTK's flat array expectation (x, y, z), we need to ensure the memory layout is correct.
    # Actually, if we have (width, height, depth) in numpy, and we want x to be fastest, we should transpose to (depth, height, width) (z, y, x)
    # and then flatten? No, wait.
    # VTK Image Data:
    # Index = x + y*dims[0] + z*dims[0]*dims[1]
    # This corresponds to Fortran order if we have (x, y, z) array.
    # Or C order if we have (z, y, x) array.
    # Our heatmap_final_np is currently (x, y, z).
    # So we should transpose it to (z, y, x) before flattening (ravel) if we use default C-order ravel.
    
    heatmap_for_vtk = np.transpose(heatmap_final_np, (2, 1, 0)) # (z, y, x)
    heatmap_for_vtk = np.ascontiguousarray(heatmap_for_vtk)
    
    # Verify size
    expected_size = new_dims[0] * new_dims[1] * new_dims[2]
    actual_size = heatmap_for_vtk.size
    print(f"--- VTI Data Check: Expected Size={expected_size}, Actual Size={actual_size} ---")
    
    if expected_size != actual_size:
        print(f"!!! ERROR: Data size mismatch! Resizing failed to produce correct shape. !!!")
        # Fallback or error handling?
        # Let's try to force resize to exact shape if needed, but resize() should handle it.
        # If mismatch, we might have an issue with new_dims calculation vs resize output.
        # resize output shape is determined by new_dims passed to it.
        pass

    # --- Use VTK_UNSIGNED_CHAR for the 8-bit data ---
    vtk_data_array = numpy_to_vtk(num_array=heatmap_for_vtk.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    
    vtk_image_data = vtk.vtkImageData()
    # SetDimensions takes (x, y, z)
    vtk_image_data.SetDimensions(new_dims) 
    
    # Calculate Spacing
    # Original voxel spacing is [col_spacing, row_spacing, slice_thickness] -> [x_spacing, y_spacing, z_spacing]
    # We scaled x and y by 'scale'. So the new spacing should be original_spacing / scale.
    # Z spacing remains the same.
    
    new_spacing = [
        voxel_spacing[0] / scale,
        voxel_spacing[1] / scale,
        voxel_spacing[2]
    ]
    vtk_image_data.SetSpacing(new_spacing)
    
    # Set Origin
    vtk_image_data.SetOrigin(origin)
    
    vtk_image_data.GetPointData().SetScalars(vtk_data_array)
    
    # Prepare output path
    save_dir_name = str(uuid.uuid4())
    output_directory = os.path.join(settings.MEDIA_ROOT, 'heatmaps_vti', save_dir_name)
    os.makedirs(output_directory, exist_ok=True)
    heatmap_vti_path = os.path.join(output_directory, 'heatmap.vti')
    
    # Write the VTI file
    writer = vtk.vtkXMLImageDataWriter()
    writer.SetFileName(heatmap_vti_path)
    writer.SetInputData(vtk_image_data)
    writer.Write()

    print(f"  -> Heatmap saved directly to VTI: {heatmap_vti_path}")
    
    # The function now returns the path to the VTI file and the score
    return heatmap_vti_path, prediction_score_value

    


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
        os.makedirs(output_directory, exist_ok=True)
        
        output_filename = f"{output_filename_base}.vti"
        output_path = os.path.join(output_directory, output_filename)

        # Write to .vti file using vtkXMLImageDataWriter
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetFileName(output_path)
        writer.SetInputData(image_data)
        writer.Write()

        print(f"[SUCCESS] Converted NRRD to VTI file: '{output_path}'")
        return output_path

    except Exception as e:
        print(f"[EXCEPTION] Error during NRRD to VTI conversion: {str(e)}")
        return None
