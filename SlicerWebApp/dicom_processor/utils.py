import os
import numpy as np
import pydicom
import SimpleITK as sitk
from skimage.transform import resize
from tensorflow.keras.models import load_model
import uuid
from django.conf import settings
import matplotlib.pyplot as plt
import tensorflow as tf



def convert_dicom_series_to_nrrd(dicom_directory_path, output_nrrd_path):
    """
    Reads a directory of DICOM slices, combines them into a single 3D volume,
    and saves the volume as a .nrrd file. This is a format that SimpleITK
    is great at writing and VTK.js is great at reading.
    """
    print(f"Starting NRRD conversion for directory: {dicom_directory_path}")
    
    try:
        # Get the list of DICOM filenames for the main series in the folder.
        series_filenames = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(dicom_directory_path)
        if not series_filenames:
            print(f"!!! ERROR: No DICOM files found in: {dicom_directory_path}")
            return False
        
        # Create our reading machine and load the files.
        series_reader = sitk.ImageSeriesReader()
        series_reader.SetFileNames(series_filenames)
        
        # Execute the reader to create the 3D image.
        image_3d = series_reader.Execute()
        
        print(f"  > Image loaded with size: {image_3d.GetSize()} and spacing: {image_3d.GetSpacing()}")
        
        # Save the 3D image to the .nrrd file path we were given.
        sitk.WriteImage(image_3d, output_nrrd_path)
        
        print(f"  > NRRD file written successfully to {output_nrrd_path}")
        return True

    # Why 'except RuntimeError as e'? This is a better "safety net".
    # SimpleITK often reports file reading/writing problems as a 'RuntimeError'.
    # This will catch those errors properly.
    except RuntimeError as e:
        print(f"!!! A runtime error occurred during DICOM to NRRD conversion: {e}")
        return False
    except Exception as e:
        print(f"!!! An unexpected error occurred: {e}")
        return False



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

def generate_heatmap(dicom_directory):
    """
    Generates a Grad-CAM style heatmap and also returns the model's prediction score.
    Updated with correct input shape and layer name for the new model.
    """
    print("--- Starting generate_heatmap ---")
    print(f"Processing directory: {dicom_directory}")
    volume = create_volume_from_dicom(dicom_directory)
    if volume is None or volume.size == 0:
        print("!!! ERROR: create_volume_from_dicom failed.")
        return None, None 

    volume_transposed = np.transpose(volume, (2, 1, 0))
    print(f"  > Volume transposed to shape: {volume_transposed.shape}")

    # --- FIX #1: Correct Resize Shape ---
    # Why this change? The error message told us the model expects a shape of (90, 90, 25).
    # We now resize the input scan to this exact size.
    correct_shape = (90, 90, 25)
    print(f"  > Resizing volume to the correct model input shape: {correct_shape}")
    resized_volume = resize(volume_transposed, correct_shape, anti_aliasing=True)
    print(f"  > Volume resized to shape: {resized_volume.shape}")
    
    input_vol_for_model = np.expand_dims(resized_volume, axis=(0, -1))
    print(f"  > Final input shape for model: {input_vol_for_model.shape}")

    # --- LOADING THE MODEL ---
    chosen_checkpoint_folder_name = "checkpoint_v2_1" 
    keras_model_filename = "weights-improvement_v2_1.keras"

    model_path = os.path.join(settings.BASE_DIR, 'dicom_processor', chosen_checkpoint_folder_name, keras_model_filename)
    
    print(f"  > Attempting to load model from: {model_path}")
    if not os.path.exists(model_path):
        print(f"!!! ERROR: Model file not found at {model_path}.")
        return None, None 

    try:
        model = load_model(model_path)
        print("  > Model loaded successfully.")
    except Exception as e:
        print(f"!!! ERROR loading Keras model from file {model_path}: {e}")
        return None, None

    # --- PREPARE FOR HEATMAP ---
    prediction_score_value = None 

    # --- FIX #2: Correct Layer Name ---
    # Why this change? The error message listed all the valid layer names.
    # 'activation_41' is the last activation layer before pooling, which is perfect for Grad-CAM.
    last_conv_layer_name = "activation_41" # <<< CORRECTED NAME
    print(f"  > Using layer for Grad-CAM: '{last_conv_layer_name}'")
    
    try:
        grad_model = tf.keras.models.Model(
            [model.inputs], [model.get_layer(last_conv_layer_name).output, model.output]
        )
        print("  > Grad-CAM model created successfully.")
    except ValueError as e:
        print(f"!!! ERROR creating Grad-CAM model. Layer '{last_conv_layer_name}' not found. Heatmap will be skipped.")
        # If Grad-CAM fails, try getting a prediction directly from the main model
        try:
            # Important: The model.predict() expects a compatible shape.
            # If the grad_model creation fails, it's safer to just return.
            # The error above indicates the model itself has a different input layer name or structure.
            # Let's adjust the logic slightly. The primary error is shape mismatch on the model itself.
            preds_only = model.predict(input_vol_for_model)
            pred_index_fallback = np.argmax(preds_only[0])
            prediction_score_value = float(preds_only[0][pred_index_fallback])
            print(f"  > Fallback prediction score (no heatmap): {prediction_score_value}")
            return None, prediction_score_value
        except Exception as e_pred_fallback:
            print(f"!!! ERROR getting fallback prediction: {e_pred_fallback}")
            return None, None

    # --- GENERATE HEATMAP & SCORE ---
    print("  > Generating heatmap and extracting score...")
    with tf.GradientTape() as tape:
        # We pass the correctly shaped input to our model now.
        conv_output, preds = grad_model(input_vol_for_model)
        pred_index = tf.argmax(preds[0]).numpy() 
        prediction_score_value = float(preds[0][pred_index].numpy()) 
        class_channel_for_gradients = preds[:, pred_index] 

        print(f"  > Model prediction values (preds): {preds.numpy()}")
        print(f"  > Predicted class index: {pred_index}")
        print(f"  > Final prediction score value: {prediction_score_value}")

    # The rest of the heatmap generation code remains the same...
    grads = tape.gradient(class_channel_for_gradients, conv_output)
    if grads is None:
        print("!!! ERROR: Gradients are None. Cannot create heatmap. Returning score only.")
        return None, prediction_score_value 

    pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2, 3)) 
    heatmap_conv_output = conv_output[0] 
    cam = np.zeros(heatmap_conv_output.shape[0:3], dtype=np.float32) 

    for i, w in enumerate(pooled_grads):
        cam += w * heatmap_conv_output[:, :, :, i]

    cam = np.maximum(cam, 0) 
    if np.max(cam) > 0: 
        cam = cam / np.max(cam)
    
    # We resize the final heatmap to match the original scan size for correct overlay.
    heatmap_resized = resize(cam, volume_transposed.shape, anti_aliasing=True)
    save_dir_name = str(uuid.uuid4()) 
    heatmap_output_directory = os.path.join(settings.MEDIA_ROOT, 'heatmaps', save_dir_name)
    os.makedirs(heatmap_output_directory, exist_ok=True)

    heatmap_img_sitk = sitk.GetImageFromArray(heatmap_resized.astype(np.float32))
    heatmap_file_path = os.path.join(heatmap_output_directory, 'heatmap.nrrd')
    sitk.WriteImage(heatmap_img_sitk, heatmap_file_path)
    print(f"  > Heatmap saved to: {heatmap_file_path}")
    print("--- Finished generate_heatmap successfully ---")

    return heatmap_output_directory, prediction_score_value



    


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
        print(f"Successfully stacked {len(slices_data)} as 3D volume with shape: {volume.shape}")
        return volume, voxel_spacing
    except ValueError as e:
        print(f"Error stacking slices into a 3D volume: {e}")
        raise ValueError(f"Error stacking slices into a 3D volume: {e}")
        return None, None
    

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
