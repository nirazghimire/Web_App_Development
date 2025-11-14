import vtkXMLImageDataReader from '@kitware/vtk.js/IO/XML/XMLImageDataReader';
import vtkHttpDataAccessHelper from '@kitware/vtk.js/IO/Core/DataAccessHelper/HttpDataAccessHelper';
import vtkVolume from '@kitware/vtk.js/Rendering/Core/Volume';
import vtkVolumeMapper from '@kitware/vtk.js/Rendering/Core/VolumeMapper';
import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkPiecewiseFunction from '@kitware/vtk.js/Common/DataModel/PiecewiseFunction';
import vtkVolumeController from '@kitware/vtk.js/Interaction/UI/VolumeController';
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';

import vtkImageSliceMapper from '@kitware/vtk.js/Rendering/Core/ImageSliceMapper';
import vtkImageSlice from '@kitware/vtk.js/Rendering/Core/ImageSlice';

// Store references globally to reuse render windows and views
window.vtkRenderers = {
  volume3D: null,
  slices: {}, // keys: viewAxial, viewSagittal, viewCoronal
};

function createSliceView(container, imageData, axis) {
  if (!container) {
    console.error('[createSliceView] Container element is null or undefined.');
    return null;
  }

  // Reuse existing render window if present
  if (window.vtkRenderers.slices[container.id]) {
    return window.vtkRenderers.slices[container.id];
  }

  const sliceMapper = vtkImageSliceMapper.newInstance();
  sliceMapper.setInputData(imageData);
  sliceMapper.setSlicingMode(axis);

  const slice = vtkImageSlice.newInstance();
  slice.setMapper(sliceMapper);

  const genericRenderWindow = vtkGenericRenderWindow.newInstance({ background: [0, 0, 0] });
  genericRenderWindow.setContainer(container);

  const renderer = genericRenderWindow.getRenderer();
  renderer.addActor(slice);

  const camera = renderer.getActiveCamera();
  camera.setParallelProjection(true);

  switch (axis) {
    case 0: // Sagittal
      camera.setViewUp(0, 0, -1);
      camera.setPosition(1, 0, 0);
      break;
    case 1: // Coronal
      camera.setViewUp(0, 0, -1);
      camera.setPosition(0, -1, 0);
      break;
    case 2: // Axial
      camera.setViewUp(0, -1, 0);
      camera.setPosition(0, 0, 1);
      break;
    default:
      console.warn('[createSliceView] Unknown axis:', axis);
  }

  renderer.resetCamera();
  genericRenderWindow.getRenderWindow().render();

  const sliceView = { genericRenderWindow, sliceMapper, slice };
  window.vtkRenderers.slices[container.id] = sliceView;
  return sliceView;
}

async function initializeVtkViewer(seriesId) {
  const loadingOverlay = document.getElementById('loadingOverlay');
  const loadingMessage = document.getElementById('loadingMessage');
  const controlPanel = document.getElementById('controlPanel');

  if (!loadingOverlay || !loadingMessage || !controlPanel) {
    console.error('Missing one or more essential DOM elements: loadingOverlay, loadingMessage, controlPanel');
    return;
  }

  loadingOverlay.style.display = 'flex';
  loadingMessage.querySelector('span').textContent = 'Requesting data from server...';

  try {
    const response = await fetch(`/dicom/ajax/get_volume_url/${seriesId}/`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    const data = await response.json();
    if (!data.success || !data.volume_url) {
      throw new Error(data.error || 'Server did not provide a valid volume URL.');
    }

    loadingMessage.querySelector('span').textContent = 'Downloading 3D volume data...';
    const fileContents = await vtkHttpDataAccessHelper.fetchBinary(data.volume_url);

    loadingMessage.querySelector('span').textContent = 'Parsing 3D volume...';
    const reader = vtkXMLImageDataReader.newInstance();
    reader.parseAsArrayBuffer(fileContents);
    const imageData = reader.getOutputData(0);

    if (!imageData) throw new Error('Failed to parse volume data (imageData is null).');

    console.log('Parsed imageData dimensions:', imageData.getDimensions());

    // Create transfer functions for volume rendering
    const ctfun = vtkColorTransferFunction.newInstance();
    ctfun.addRGBPoint(0, 0.0, 0.0, 0.0);
    ctfun.addRGBPoint(1000, 1.0, 1.0, 1.0);

    const ofun = vtkPiecewiseFunction.newInstance();
    ofun.addPoint(0, 0.0);
    ofun.addPoint(1000, 0.5);

    // Initialize or reuse 3D volume rendering
    let volume3D = window.vtkRenderers.volume3D;
    let actor; // Define actor here to be accessible later

    if (!volume3D) {
      actor = vtkVolume.newInstance(); // Assign to the outer scope actor
      const mapper = vtkVolumeMapper.newInstance();
      mapper.setInputData(imageData);
      actor.setMapper(mapper);
      actor.getProperty().setRGBTransferFunction(0, ctfun);
      actor.getProperty().setScalarOpacity(0, ofun);
      actor.getProperty().setInterpolationTypeToLinear();

      const container3D = document.getElementById('view3D');
      if (!container3D) {
        throw new Error('3D view container not found.');
      }

      const genericRenderWindow3D = vtkGenericRenderWindow.newInstance({ background: [0.1, 0.1, 0.2] });
      genericRenderWindow3D.setContainer(container3D);

      const renderer3D = genericRenderWindow3D.getRenderer();
      renderer3D.addVolume(actor);
      renderer3D.resetCamera();
      genericRenderWindow3D.getRenderWindow().render();

      // Add orientation axes
      const axes = vtkAxesActor.newInstance();
      const orientationWidget = vtkOrientationMarkerWidget.newInstance({
        actor: axes,
        interactor: genericRenderWindow3D.getInteractor(),
      });
      orientationWidget.setEnabled(true);
      orientationWidget.setViewportCorner(vtkOrientationMarkerWidget.Corners.BOTTOM_LEFT);
      orientationWidget.setViewportSize(0.15);

      volume3D = { genericRenderWindow: genericRenderWindow3D, renderer: renderer3D, actor, mapper };
      window.vtkRenderers.volume3D = volume3D;
    } else {
      // Update input data for existing volume rendering
      actor = volume3D.actor; // Get actor from existing view
      volume3D.mapper.setInputData(imageData);
      volume3D.renderer.resetCamera();
      volume3D.genericRenderWindow.getRenderWindow().render();
    }

    // Prepare slice views
    const sliceContainers = [
      { id: 'viewAxial', axis: 2 },
      { id: 'viewSagittal', axis: 0 },
      { id: 'viewCoronal', axis: 1 },
    ];

    sliceContainers.forEach(({ id, axis }) => {
      const container = document.getElementById(id);
      if (!container) {
        console.warn(`Slice container '${id}' not found.`);
        return;
      }
      const sliceView = createSliceView(container, imageData, axis);

      // Initialize slice to middle slice
      if (sliceView) {
        const dims = imageData.getDimensions();
        const midSlice = Math.floor(dims[axis] / 2);
        sliceView.sliceMapper.setSlice(midSlice);
        sliceView.genericRenderWindow.getRenderWindow().render();
      }
    });

    // === FIX IS HERE: The controller now uses the 'actor' as its source ===
    const controller = vtkVolumeController.newInstance({
      source: actor, // Use the vtkVolume actor, not the raw imageData
    });
    controller.setContainer(controlPanel);
    controller.setupContent();

    // Setup sliders dynamically
    setupSliceSliders(imageData);

    loadingOverlay.style.display = 'none';
  } catch (error) {
    console.error('Failed to initialize VTK.js viewer:', error);
    loadingMessage.innerHTML = `
      <div class="p-3 text-center">
        <p class="text-danger"><b>Error Initializing Viewer</b></p>
        <p class="text-white-50">${error.message}</p>
      </div>`;
  }
}

function setupSliceSliders(imageData) {
  const dims = imageData.getDimensions();

  function ensureSlider(containerId, sliderId) {
    const container = document.getElementById(containerId);
    if (!container) {
      console.warn(`Cannot create slider: container '${containerId}' not found.`);
      return null;
    }
    let slider = container.querySelector(`#${sliderId}`);
    if (!slider) {
      const sliderContainer = container.querySelector('.slice-slider-container');
      if (!sliderContainer) {
        console.warn(`No .slice-slider-container inside ${containerId} to append slider.`);
        return null;
      }
      slider = document.createElement('input');
      slider.type = 'range';
      slider.id = sliderId;
      slider.min = 0;
      slider.max = 100;
      slider.value = 0;
      sliderContainer.appendChild(slider);
    }
    return slider;
  }

  // Axial
  const sliderAxial = ensureSlider('viewAxial', 'sliderAxial');
  if (sliderAxial) {
    sliderAxial.min = 0;
    sliderAxial.max = dims[2] - 1;
    sliderAxial.value = Math.floor(dims[2] / 2);
    sliderAxial.oninput = e => {
      const slice = Number(e.target.value);
      const view = window.vtkRenderers.slices['viewAxial'];
      if (view) {
        view.sliceMapper.setSlice(slice);
        view.genericRenderWindow.getRenderWindow().render();
      }
    };
  }

  // Sagittal
  const sliderSagittal = ensureSlider('viewSagittal', 'sliderSagittal');
  if (sliderSagittal) {
    sliderSagittal.min = 0;
    sliderSagittal.max = dims[0] - 1;
    sliderSagittal.value = Math.floor(dims[0] / 2);
    sliderSagittal.oninput = e => {
      const slice = Number(e.target.value);
      const view = window.vtkRenderers.slices['viewSagittal'];
      if (view) {
        view.sliceMapper.setSlice(slice);
        view.genericRenderWindow.getRenderWindow().render();
      }
    };
  }

  // Coronal
  const sliderCoronal = ensureSlider('viewCoronal', 'sliderCoronal');
  if (sliderCoronal) {
    sliderCoronal.min = 0;
    sliderCoronal.max = dims[1] - 1;
    sliderCoronal.value = Math.floor(dims[1] / 2);
    sliderCoronal.oninput = e => {
      const slice = Number(e.target.value);
      const view = window.vtkRenderers.slices['viewCoronal'];
      if (view) {
        view.sliceMapper.setSlice(slice);
        view.genericRenderWindow.getRenderWindow().render();
      }
    };
  }
}

// Export function globally for your inline script to call
window.initializeVtkViewer = initializeVtkViewer;
