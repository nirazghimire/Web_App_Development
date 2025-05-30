import os
import numpy as np
import pydicom
import SimpleITK as sitk
from skimage.transform import resize
from tensorflow.keras.models import load_model
import uuid
from django.conf import settings
import matplotlib.pyplot as plt


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
    volume = create_volume_from_dicom(dicom_directory)  # shape (D, H, W)
    volume = np.transpose(volume, (2, 1, 0))             # shape (W, H, D)

    resized = resize(volume, (150, 150, 90), anti_aliasing=True)
    input_vol = np.expand_dims(resized, axis=(0, -1))    # shape (1, 150, 150, 90, 1)

    model_path = os.path.join(settings.BASE_DIR, 'dicom_processor', 'model_weights.hdf5')
    model = load_model(model_path)

    # Grad-CAM style logic
    import tensorflow as tf
    last_conv = "activation_20"
    grad_model = tf.keras.models.Model([model.inputs], [model.get_layer(last_conv).output, model.output])

    with tf.GradientTape() as tape:
        conv_out, preds = grad_model(input_vol)
        pred_index = tf.argmax(preds[0])
        class_output = preds[:, pred_index]

    grads = tape.gradient(class_output, conv_out)[0]
    pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2, 3))
    conv_out = conv_out[0]
    cam = np.zeros(conv_out.shape[0:3], dtype=np.float32)

    for i, w in enumerate(pooled_grads):
        cam += w * conv_out[:, :, :, i]

    cam = np.maximum(cam, 0)
    heatmap = resize(cam, volume.shape[::-1], anti_aliasing=True)

    # Save heatmap
    save_dir = os.path.join(settings.MEDIA_ROOT, 'heatmaps', str(uuid.uuid4()))
    os.makedirs(save_dir, exist_ok=True)

    heatmap_img = sitk.GetImageFromArray(heatmap.astype(np.float32))
    heatmap_path = os.path.join(save_dir, 'heatmap.nrrd')
    sitk.WriteImage(heatmap_img, heatmap_path)

    return save_dir
