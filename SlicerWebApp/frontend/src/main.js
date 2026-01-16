// frontend/src/main.js

import '@kitware/vtk.js/favicon';
import '@kitware/vtk.js/Rendering/Profiles/All';

import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkXMLImageDataReader from '@kitware/vtk.js/IO/XML/XMLImageDataReader';
import vtkVolume from '@kitware/vtk.js/Rendering/Core/Volume';
import vtkVolumeMapper from '@kitware/vtk.js/Rendering/Core/VolumeMapper';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkPiecewiseFunction from '@kitware/vtk.js/Common/DataModel/PiecewiseFunction';
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';
import vtkImageSlice from '@kitware/vtk.js/Rendering/Core/ImageSlice';
import vtkImageMapper from '@kitware/vtk.js/Rendering/Core/ImageMapper';
import vtkInteractorStyleImage from '@kitware/vtk.js/Interaction/Style/InteractorStyleImage';
import HttpDataAccessHelper from '@kitware/vtk.js/IO/Core/DataAccessHelper/HttpDataAccessHelper';
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';

import vtkPicker from '@kitware/vtk.js/Rendering/Core/Picker';

import Chart from 'chart.js/auto';
import ChartDataLabels from 'chartjs-plugin-datalabels';
Chart.register(ChartDataLabels);

document.addEventListener('DOMContentLoaded', function () {
    const config = JSON.parse(document.getElementById('viewer-config').textContent);
    const loadingMessage = document.getElementById('loadingMessage');

    if (!config.seriesId) {
        loadingMessage.innerHTML = `<p class="text-info">No DICOM series loaded. Please select one from <a href="/dicom/my-uploads/">My Uploads</a>.</p>`;
        return;
    }

    async function setupVtk() {
        const loadingOverlay = document.getElementById('loadingOverlay');
        const allRenderWindows = [];
        const sliceMappers = {}; // Base image mappers
        const heatmapMappers = {}; // Heatmap mappers
        const heatmapActors = []; // Keep track of all heatmap actors to toggle visibility/opacity

        // Crosshair Storage
        const crosshairActors = {}; // { axis: { h: actor, v: actor } }

        const sagittalSlider = document.getElementById('sagittalSlider');
        const coronalSlider = document.getElementById('coronalSlider');
        const axialSlider = document.getElementById('axialSlider');
        const sagittalSliceLabel = document.getElementById('sagittalSliceLabel');
        const coronalSliceLabel = document.getElementById('coronalSliceLabel');
        const axialSliceLabel = document.getElementById('axialSliceLabel');
        const resetButton = document.getElementById('resetViewsButton');

        // --- Heatmap Color Functions ---
        const heatmapCtfun = vtkColorTransferFunction.newInstance();
        // "Jet" / Rainbow colormap: Blue -> Cyan -> Green -> Yellow -> Red
        // Optimized for medical imaging with better contrast
        heatmapCtfun.addRGBPoint(0, 0, 0, 0);            // Black - no attention
        heatmapCtfun.addRGBPoint(50, 0.0, 0.0, 0.8);     // Dark Blue
        heatmapCtfun.addRGBPoint(100, 0.0, 0.5, 1.0);    // Cyan-Blue
        heatmapCtfun.addRGBPoint(150, 0.0, 1.0, 0.5);    // Cyan-Green
        heatmapCtfun.addRGBPoint(180, 0.5, 1.0, 0.0);    // Yellow-Green
        heatmapCtfun.addRGBPoint(210, 1.0, 1.0, 0.0);    // Bright Yellow
        heatmapCtfun.addRGBPoint(240, 1.0, 0.5, 0.0);    // Orange
        heatmapCtfun.addRGBPoint(255, 1.0, 0.0, 0.0);    // Bright Red - highest attention

        const heatmapOfun = vtkPiecewiseFunction.newInstance();
        heatmapOfun.addPoint(0, 0.0);         // Fully transparent at 0
        heatmapOfun.addPoint(50, 0.1);        // Start to show
        heatmapOfun.addPoint(150, 0.4);       // Medium opacity
        heatmapOfun.addPoint(255, 0.6);       // Max opacity (default 50%)

        // --- COLORMAP PRESETS ---
        const colormapPresets = {
            viridis: {
                points: [
                    [0, 0.267004, 0.004874, 0.329415],
                    [64, 0.282623, 0.140461, 0.469165],
                    [128, 0.253935, 0.265254, 0.529983],
                    [192, 0.206756, 0.371758, 0.553806],
                    [255, 0.993248, 0.906157, 0.143936]
                ],
                gradient: 'linear-gradient(to right, #440154, #31688e, #35b779, #fde724)'
            },
            jet: {
                points: [
                    [0, 0, 0, 0.5],
                    [64, 0, 0.5, 1],
                    [128, 0, 1, 0.5],
                    [192, 0.5, 1, 0],
                    [255, 1, 0.5, 0]
                ],
                gradient: 'linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)'
            },
            hot: {
                points: [
                    [0, 0, 0, 0],
                    [85, 0.5, 0, 0],
                    [170, 1, 0.5, 0],
                    [255, 1, 1, 1]
                ],
                gradient: 'linear-gradient(to right, #000000, #800000, #ff8000, #ffffff)'
            },
            cool: {
                points: [
                    [0, 0, 1, 1],
                    [128, 0.5, 0.5, 1],
                    [255, 1, 0, 1]
                ],
                gradient: 'linear-gradient(to right, #00ffff, #8080ff, #ff00ff)'
            },
            plasma: {
                points: [
                    [0, 0.050383, 0.029803, 0.529975],
                    [64, 0.282623, 0.140461, 0.469165],
                    [128, 0.940015, 0.375966, 0.131028],
                    [192, 0.951564, 0.925701, 0.131368],
                    [255, 0.940015, 0.975251, 0.131028]
                ],
                gradient: 'linear-gradient(to right, #0d0887, #7d03a8, #ec8902, #f89540, #f0f921)'
            },
            inferno: {
                points: [
                    [0, 0.001462, 0.000466, 0.013866],
                    [64, 0.282623, 0.140461, 0.469165],
                    [128, 0.865732, 0.317254, 0.226051],
                    [192, 0.988362, 0.998364, 0.644924],
                    [255, 0.988362, 0.998364, 0.644924]
                ],
                gradient: 'linear-gradient(to right, #000004, #420a68, #932667, #fca238, #fcfea4)'
            },
            turbo: {
                points: [
                    [0, 0.18995, 0.07176, 0.23217],
                    [64, 0.05175, 0.29803, 0.90326],
                    [128, 0.40567, 0.80353, 0.71671],
                    [192, 0.84159, 0.37514, 0.08406],
                    [255, 0.88771, 0.08217, 0.14033]
                ],
                gradient: 'linear-gradient(to right, #30123b, #0571b0, #48c642, #f7cb45, #e63e1b)'
            },
            magma: {
                points: [
                    [0, 0.001462, 0.000466, 0.013866],
                    [64, 0.218959, 0.090838, 0.389348],
                    [128, 0.666852, 0.236988, 0.385799],
                    [192, 0.987053, 0.906157, 0.143936],
                    [255, 0.987053, 0.991438, 0.749504]
                ],
                gradient: 'linear-gradient(to right, #000004, #3b0f6f, #8c2980, #fcfdbf, #fcfdbf)'
            }
        };

        let currentColormap = 'viridis'; // Track current colormap

        // Helper function to update loading message
        function updateLoading(message, step = null, total = null) {
            const msgEl = loadingMessage.querySelector('span');
            if (msgEl) {
                if (step && total) {
                    msgEl.textContent = `${message} (${step}/${total})`;
                } else {
                    msgEl.textContent = message;
                }
            }
        }

        try {
            updateLoading('Requesting volume data...', 1, 5);
            const response = await fetch(config.volumeUrl);
            const data = await response.json();
            if (!data.success) throw new Error(data.error);

            updateLoading('Downloading 3D volume...', 2, 5);
            const fileContents = await HttpDataAccessHelper.fetchBinary(data.volume_url);

            updateLoading('Parsing volume data...', 3, 5);
            const reader = vtkXMLImageDataReader.newInstance();
            reader.parseAsArrayBuffer(fileContents);

            const imageData = reader.getOutputData(0);

            // --- Load Heatmap Data if available ---
            let heatmapData = null;
            console.log('Heatmap loading: config.heatmapUrl =', config.heatmapUrl);
            if (config.heatmapUrl) {
                try {
                    updateLoading('Loading AI heatmap overlay...', 4, 5);
                    console.log('🔄 Fetching heatmap from URL:', config.heatmapUrl);
                    const hResponse = await fetch(config.heatmapUrl);
                    const hData = await hResponse.json();
                    console.log('📥 Heatmap response:', hData);
                    if (hData.success && hData.heatmap_url) {
                        console.log('📥 Loading heatmap binary from:', hData.heatmap_url);
                        const hFileContents = await HttpDataAccessHelper.fetchBinary(hData.heatmap_url);
                        const hReader = vtkXMLImageDataReader.newInstance();
                        hReader.parseAsArrayBuffer(hFileContents);
                        heatmapData = hReader.getOutputData(0);

                        // Validate heatmap dimensions match original volume
                        if (heatmapData) {
                            const heatmapDims = heatmapData.getDimensions();
                            const volumeDims = imageData.getDimensions();
                            console.log('✅ Heatmap loaded successfully. Dimensions:', heatmapDims);
                            console.log('   Volume dimensions:', volumeDims);

                            // Check for dimension mismatch
                            if (heatmapDims[0] !== volumeDims[0] ||
                                heatmapDims[1] !== volumeDims[1] ||
                                heatmapDims[2] !== volumeDims[2]) {
                                console.warn('⚠️  Heatmap dimensions do not match volume dimensions. This may cause alignment issues.');
                            }
                        }
                    } else {
                        console.warn('⚠️  Heatmap URL missing or request unsuccessful:', hData);
                    }
                } catch (e) {
                    console.error("❌ Failed to load heatmap:", e);
                    // Continue without heatmap
                }
            } else {
                console.log('ℹ️  No heatmapUrl in config - heatmap disabled for this series');
            }

            updateLoading('Setting up 3D visualization...', 5, 5);

            const bounds = imageData.getBounds(); // [xmin, xmax, ymin, ymax, zmin, zmax]
            const center = imageData.getCenter();
            const dims = imageData.getDimensions();
            const spacing = imageData.getSpacing();
            const origin = imageData.getOrigin();

            // ... (Heatmap loading logic) ...

            // --- CROSSHAIR HELPER ---
            function createCrosshairActor(orientationAxis) {
                // orientationAxis: 0=Sagittal(yz), 1=Coronal(xz), 2=Axial(xy)
                // We need two lines: Horizontal and Vertical relative to the view.

                const polyData = vtkPolyData.newInstance();
                // 2 lines = 4 points
                const pts = new Float32Array(12); // 4 points * 3 coords
                polyData.getPoints().setData(pts, 3);

                // 2 cells (lines)
                const lines = new Uint16Array([2, 0, 1, 2, 2, 3]); // size + ptIds
                polyData.getLines().setData(lines);

                const mapper = vtkMapper.newInstance();
                mapper.setInputData(polyData);

                const actor = vtkActor.newInstance();
                actor.setMapper(mapper);
                actor.getProperty().setColor(1, 1, 0); // Yellow
                actor.getProperty().setLineWidth(1.5);
                actor.setPickable(false); // Don't let the picker pick the lines themselves

                return { actor, polyData };
            }

            // ... (3D View Setup - keep as is) ...

            // ... (Slider Elements - keep as is) ...

            // ... (Heatmap Color Functions - keep as is) ...

            function updateCrosshairs(i, j, k) {
                // Convert indices to world coordinates for the lines
                // Formula: world = origin + index * spacing
                const x = origin[0] + i * spacing[0];
                const y = origin[1] + j * spacing[1];
                const z = origin[2] + k * spacing[2];

                // Bounds for the lines
                const b = bounds; // [x_min, x_max, y_min, y_max, z_min, z_max]

                // --- AXIAL VIEW (Axis 2) ---
                // Shows XY plane.
                // Vertical Line (Sagittal plane): x = current x, y goes min to max
                // Horizontal Line (Coronal plane): y = current y, x goes min to max
                if (crosshairActors[2]) {
                    const pd = crosshairActors[2].polyData;
                    const pts = pd.getPoints().getData();
                    // Vertical line (constant x)
                    pts[0] = x; pts[1] = b[2]; pts[2] = z + 0.1; // +0.1 to sit slightly on top
                    pts[3] = x; pts[4] = b[3]; pts[5] = z + 0.1;
                    // Horizontal line (constant y)
                    pts[6] = b[0]; pts[7] = y; pts[8] = z + 0.1;
                    pts[9] = b[1]; pts[10] = y; pts[11] = z + 0.1;
                    pd.getPoints().setData(pts, 3);
                    pd.modified();
                }

                // --- CORONAL VIEW (Axis 1) ---
                // Shows XZ plane.
                // Vertical Line (Sagittal plane): x = current x
                // Horizontal Line (Axial plane): z = current z
                if (crosshairActors[1]) {
                    const pd = crosshairActors[1].polyData;
                    const pts = pd.getPoints().getData();
                    // Vertical line (constant x)
                    pts[0] = x; pts[1] = y - 0.1; pts[2] = b[4];
                    pts[3] = x; pts[4] = y - 0.1; pts[5] = b[5];
                    // Horizontal line (constant z)
                    pts[6] = b[0]; pts[7] = y - 0.1; pts[8] = z;
                    pts[9] = b[1]; pts[10] = y - 0.1; pts[11] = z;
                    pd.getPoints().setData(pts, 3);
                    pd.modified();
                }

                // --- SAGITTAL VIEW (Axis 0) ---
                // Shows YZ plane.
                // Vertical Line (Coronal plane): y = current y
                // Horizontal Line (Axial plane): z = current z
                if (crosshairActors[0]) {
                    const pd = crosshairActors[0].polyData;
                    const pts = pd.getPoints().getData();
                    // Vertical line (constant y)
                    pts[0] = x - 0.1; pts[1] = y; pts[2] = b[4];
                    pts[3] = x - 0.1; pts[4] = y; pts[5] = b[5];
                    // Horizontal line (constant z)
                    pts[6] = x - 0.1; pts[7] = b[2]; pts[8] = z;
                    pts[9] = x - 0.1; pts[10] = b[3]; pts[11] = z;
                    pd.getPoints().setData(pts, 3);
                    pd.modified();
                }
            }

            // --- SYNCHRONIZATION FLAG ---
            // Prevents slider input events from triggering when values are updated programmatically
            let isUpdatingSliders = false;

            function updateAllSlices(i, j, k) {
                // Set flag to prevent slider input events
                isUpdatingSliders = true;

                // Update Base Mappers (keep existing)
                if (sliceMappers[0] && i >= 0 && i < dims[0]) {
                    sliceMappers[0].setSlice(i);
                    sagittalSlider.value = i;
                    sagittalSliceLabel.textContent = i;
                }
                if (sliceMappers[1] && j >= 0 && j < dims[1]) {
                    sliceMappers[1].setSlice(j);
                    coronalSlider.value = j;
                    coronalSliceLabel.textContent = j;
                }
                if (sliceMappers[2] && k >= 0 && k < dims[2]) {
                    sliceMappers[2].setSlice(k);
                    axialSlider.value = k;
                    axialSliceLabel.textContent = k;
                }

                // Update Heatmap Mappers (keep existing)
                if (heatmapMappers[0]) heatmapMappers[0].setSlice(i);
                if (heatmapMappers[1]) heatmapMappers[1].setSlice(j);
                if (heatmapMappers[2]) heatmapMappers[2].setSlice(k);

                // --- UPDATE CROSSHAIRS ---
                updateCrosshairs(i, j, k);

                allRenderWindows.forEach(rw => {
                    // rw.getRenderer().resetCameraClippingRange(); // Optional: might be too expensive to do every frame?
                    rw.getRenderWindow().render();
                });

                // Clear flag after updates are complete
                isUpdatingSliders = false;
            }

            function resetViews() {
                const i = Math.floor(dims[0] / 2);
                const j = Math.floor(dims[1] / 2);
                const k = Math.floor(dims[2] / 2);
                updateAllSlices(i, j, k);
                renWin3D.getRenderer().resetCamera();
                renWin3D.getRenderWindow().render();
            }

            const sliceViewConfigs = [
                { id: 'viewAxial', axis: 2, slider: axialSlider },
                { id: 'viewSagittal', axis: 0, slider: sagittalSlider },
                { id: 'viewCoronal', axis: 1, slider: coronalSlider }
            ];
            const picker = vtkPicker.newInstance();
            picker.setTolerance(0.005);

            // ... (loop over sliceViewConfigs) ... 
            sliceViewConfigs.forEach(viewConfig => {
                const renWin = vtkGenericRenderWindow.newInstance({ background: [0, 0, 0] });
                renWin.setContainer(document.getElementById(viewConfig.id));
                allRenderWindows.push(renWin);
                const renderer = renWin.getRenderer();
                const camera = renderer.getActiveCamera();

                // Base Slice
                const sliceMapper = vtkImageMapper.newInstance();
                sliceMapper.setInputData(imageData);
                sliceMapper.setSlicingMode(viewConfig.axis);
                sliceMappers[viewConfig.axis] = sliceMapper;
                const slice = vtkImageSlice.newInstance();
                slice.setMapper(sliceMapper);
                slice.getProperty().setColorWindow(400);
                slice.getProperty().setColorLevel(40);
                renderer.addActor(slice);

                // Heatmap Slice (Overlay)
                if (heatmapData) {
                    try {
                        const hMapper = vtkImageMapper.newInstance();
                        hMapper.setInputData(heatmapData);
                        hMapper.setSlicingMode(viewConfig.axis);
                        heatmapMappers[viewConfig.axis] = hMapper;

                        const hActor = vtkImageSlice.newInstance();
                        hActor.setMapper(hMapper);
                        hActor.getProperty().setRGBTransferFunction(heatmapCtfun);
                        hActor.getProperty().setScalarOpacity(heatmapOfun);
                        hActor.getProperty().setOpacity(0.5); // Initial opacity (50%)
                        hActor.setVisibility(false); // Hidden by default

                        renderer.addActor(hActor);
                        heatmapActors.push(hActor);
                        console.log(`✓ Heatmap overlay created for ${viewConfig.id} (actor #${heatmapActors.length})`);
                        console.log(`  Heatmap dims: ${heatmapData.getDimensions()}, Volume dims: ${imageData.getDimensions()}`);
                    } catch (e) {
                        console.error(`✗ Failed to add heatmap overlay to ${viewConfig.id}:`, e);
                    }
                } else {
                    console.log(`⚠ No heatmap data available for ${viewConfig.id}`);
                }

                // Add Crosshair Actor for this view
                const ch = createCrosshairActor(viewConfig.axis);
                crosshairActors[viewConfig.axis] = ch;
                renderer.addActor(ch.actor);

                viewConfig.slider.max = dims[viewConfig.axis] - 1;
                const iStyle = vtkInteractorStyleImage.newInstance();
                renWin.getInteractor().setInteractorStyle(iStyle);
                camera.setParallelProjection(true);
                renderer.resetCamera();
                switch (viewConfig.axis) {
                    case 0: camera.setPosition(bounds[0] - 1, center[1], center[2]); camera.setViewUp(0, 0, -1); camera.setParallelScale((bounds[5] - bounds[4]) / 2); break;
                    case 1: camera.setPosition(center[0], bounds[2] - 1, center[2]); camera.setViewUp(0, 0, -1); camera.setParallelScale((bounds[5] - bounds[4]) / 2); break;
                    case 2: camera.setPosition(center[0], center[1], bounds[5] + 1); camera.setViewUp(0, -1, 0); camera.setParallelScale((bounds[3] - bounds[2]) / 2); break;
                }
                renderer.resetCameraClippingRange();

                // Interaction
                const interactor = renWin.getInteractor();
                interactor.onMouseWheel(event => {
                    const currentSlice = sliceMapper.getSlice();
                    const newSlice = currentSlice + Math.sign(event.spinY);
                    const i = (viewConfig.axis === 0) ? newSlice : sliceMappers[0].getSlice();
                    const j = (viewConfig.axis === 1) ? newSlice : sliceMappers[1].getSlice();
                    const k = (viewConfig.axis === 2) ? newSlice : sliceMappers[2].getSlice();
                    updateAllSlices(i, j, k);
                });
                interactor.onLeftButtonPress((event) => {
                    console.log(`=== LEFT CLICK on ${viewConfig.id} ===`);
                    console.log('Event:', event);
                    const pos = event.position;
                    console.log('Mouse position:', pos);

                    picker.initialize();
                    picker.pick([pos.x, pos.y, 0.0], renderer);
                    console.log('Picker actors found:', picker.getActors().length);

                    if (picker.getActors().length > 0) {
                        const pickedPoint = picker.getPickPosition();
                        console.log('Picked point (world coords):', pickedPoint);

                        const worldToIndex = imageData.worldToIndex(pickedPoint);
                        console.log('World to index result:', worldToIndex);

                        let i = Math.round(worldToIndex[0]);
                        let j = Math.round(worldToIndex[1]);
                        let k = Math.round(worldToIndex[2]);

                        // IMPORTANT: Only update the coordinates visible in this view
                        // Keep the perpendicular axis at its current slice
                        const currentI = sliceMappers[0].getSlice();
                        const currentJ = sliceMappers[1].getSlice();
                        const currentK = sliceMappers[2].getSlice();

                        console.log(`Picked indices before correction: i=${i}, j=${j}, k=${k}`);
                        console.log(`Current slices: i=${currentI}, j=${currentJ}, k=${currentK}`);

                        // Based on view orientation, keep the perpendicular axis unchanged
                        switch (viewConfig.axis) {
                            case 0: // Sagittal view: shows Y-Z plane, keep X unchanged
                                i = currentI;
                                console.log('Sagittal view: keeping i (X) = ' + i);
                                break;
                            case 1: // Coronal view: shows X-Z plane, keep Y unchanged
                                j = currentJ;
                                console.log('Coronal view: keeping j (Y) = ' + j);
                                break;
                            case 2: // Axial view: shows X-Y plane, keep Z unchanged
                                k = currentK;
                                console.log('Axial view: keeping k (Z) = ' + k);
                                break;
                        }

                        console.log(`Final indices: i=${i}, j=${j}, k=${k}`);
                        console.log(`Current slices before update: i=${sliceMappers[0]?.getSlice()}, j=${sliceMappers[1]?.getSlice()}, k=${sliceMappers[2]?.getSlice()}`);

                        updateAllSlices(i, j, k);

                        console.log(`Current slices after update: i=${sliceMappers[0]?.getSlice()}, j=${sliceMappers[1]?.getSlice()}, k=${sliceMappers[2]?.getSlice()}`);
                        console.log(`Slider values after update: sagittal=${sagittalSlider.value}, coronal=${coronalSlider.value}, axial=${axialSlider.value}`);

                        // Prevent default interactor behavior from interfering
                        event.callData.handled = true;
                        console.log('✓ Event handled');
                    } else {
                        console.log('✗ No actors picked');
                    }
                    console.log('=== END CLICK ===\n');
                });
                renWin.getRenderWindow().render();
            });

            // ... (rest of function) ...




            // --- 3D View Setup ---
            const renWin3D = vtkGenericRenderWindow.newInstance({ background: [0, 0, 0] });
            renWin3D.setContainer(document.getElementById('view3D'));
            allRenderWindows.push(renWin3D);

            const actor = vtkVolume.newInstance();
            const mapper = vtkVolumeMapper.newInstance();
            actor.setMapper(mapper);
            mapper.setInputData(imageData);

            const ctfun = vtkColorTransferFunction.newInstance();
            ctfun.addRGBPoint(-1000, 0, 0, 0);
            ctfun.addRGBPoint(500, 0.6, 0.6, 0.6);
            ctfun.addRGBPoint(1200, 1.0, 1.0, 0.9);
            ctfun.addRGBPoint(3000, 1.0, 1.0, 1.0);

            const ofun = vtkPiecewiseFunction.newInstance();
            ofun.addPoint(-1000, 0.0);
            ofun.addPoint(250, 0.0);
            ofun.addPoint(500, 0.2);
            ofun.addPoint(3000, 0.8);

            actor.getProperty().setRGBTransferFunction(0, ctfun);
            actor.getProperty().setScalarOpacity(0, ofun);
            renWin3D.getRenderer().addVolume(actor);

            renWin3D.getRenderer().resetCamera();
            const camera3D = renWin3D.getRenderer().getActiveCamera();
            const distance = camera3D.getDistance();
            camera3D.setPosition(center[0], bounds[2] - distance, center[2]);
            camera3D.setViewUp(0, 0, -1);
            renWin3D.getRenderer().resetCameraClippingRange();

            const axes = vtkAxesActor.newInstance();
            const orientationWidget = vtkOrientationMarkerWidget.newInstance({ actor: axes, interactor: renWin3D.getInteractor() });
            orientationWidget.setEnabled(true);
            orientationWidget.setViewportCorner(vtkOrientationMarkerWidget.Corners.BOTTOM_LEFT);
            orientationWidget.setViewportSize(0.15);



            sagittalSlider.addEventListener('input', (e) => {
                if (isUpdatingSliders) return; // Skip if programmatically updated
                const i = parseInt(e.target.value, 10);
                updateAllSlices(i, sliceMappers[1].getSlice(), sliceMappers[2].getSlice());
            });

            coronalSlider.addEventListener('input', (e) => {
                if (isUpdatingSliders) return; // Skip if programmatically updated
                const j = parseInt(e.target.value, 10);
                updateAllSlices(sliceMappers[0].getSlice(), j, sliceMappers[2].getSlice());
            });

            axialSlider.addEventListener('input', (e) => {
                if (isUpdatingSliders) return; // Skip if programmatically updated
                const k = parseInt(e.target.value, 10);
                updateAllSlices(sliceMappers[0].getSlice(), sliceMappers[1].getSlice(), k);
            });

            // --- Heatmap Controls ---
            const heatmapToggle = document.getElementById('heatmapToggle');
            const heatmapControls = document.getElementById('heatmapControls');
            const opacitySlider = document.getElementById('opacitySlider');
            const colormapSelect = document.getElementById('colormapSelect');
            const heatmapValueReadout = document.getElementById('heatmapValueReadout');
            const colormapGradient = document.getElementById('colormapGradient');

            // Debug: Log heatmap setup status
            console.log('=== HEATMAP SETUP DEBUG ===');
            console.log('heatmapToggle element:', heatmapToggle);
            console.log('heatmapControls element:', heatmapControls);
            console.log('opacitySlider element:', opacitySlider);
            console.log('colormapSelect element:', colormapSelect);
            console.log('heatmapValueReadout element:', heatmapValueReadout);
            console.log('colormapGradient element:', colormapGradient);
            console.log('heatmapData loaded:', !!heatmapData);
            console.log('heatmapActors count:', heatmapActors.length);
            console.log('=== END DEBUG ===');

            // Function to update colormap across all heatmap actors
            function setColormap(colormapName) {
                const preset = colormapPresets[colormapName];
                if (!preset) {
                    console.warn(`Unknown colormap: ${colormapName}`);
                    return;
                }

                console.log(`Switching colormap to: ${colormapName}`);

                // Clear existing color points
                heatmapCtfun.removeAllPoints();

                // Add new color points from preset
                preset.points.forEach(point => {
                    heatmapCtfun.addRGBPoint(point[0], point[1], point[2], point[3]);
                });

                // Update legend gradient
                if (colormapGradient) {
                    colormapGradient.style.background = preset.gradient;
                }

                // Update all heatmap actors with new color function
                heatmapActors.forEach(actor => {
                    actor.getProperty().setRGBTransferFunction(heatmapCtfun);
                });

                // Update scalar opacity function for better visibility
                heatmapOfun.removeAllPoints();
                heatmapOfun.addPoint(0, 0.0);         // Fully transparent at 0
                heatmapOfun.addPoint(50, 0.1);        // Start to show
                heatmapOfun.addPoint(150, 0.4);       // Medium opacity
                heatmapOfun.addPoint(255, 0.6);       // Max opacity

                heatmapActors.forEach(actor => {
                    actor.getProperty().setScalarOpacity(heatmapOfun);
                });

                currentColormap = colormapName;

                // Re-render all views
                allRenderWindows.forEach(rw => rw.getRenderWindow().render());
            }

            if (heatmapToggle && heatmapControls && opacitySlider) {
                // ALWAYS enable toggle - let it work even if heatmap isn't available yet
                heatmapToggle.disabled = false;

                // Setup toggle click handler
                heatmapToggle.addEventListener('change', (e) => {
                    const visible = e.target.checked;
                    console.log(`🎬 Heatmap toggle changed to: ${visible ? '✅ ON' : '❌ OFF'}, actors count: ${heatmapActors.length}`);

                    // Only show controls if heatmap exists
                    if (heatmapActors.length > 0) {
                        heatmapActors.forEach((actor, i) => {
                            actor.setVisibility(visible);
                            console.log(`   Actor ${i}: visibility = ${visible}`);
                        });
                        heatmapControls.style.display = visible ? 'flex' : 'none';
                        console.log(`   Controls display: ${visible ? 'flex' : 'none'}`);

                        // Force re-render
                        allRenderWindows.forEach((rw, i) => {
                            console.log(`   Rendering window ${i}`);
                            rw.getRenderWindow().render();
                        });
                    } else {
                        console.warn('⚠️  Heatmap toggle clicked but no heatmap actors available');
                        // Don't show controls if no heatmap
                        heatmapControls.style.display = 'none';
                    }
                });

                // Setup opacity slider
                opacitySlider.addEventListener('input', (e) => {
                    const opacity = parseFloat(e.target.value);
                    if (heatmapActors.length > 0) {
                        heatmapActors.forEach(actor => actor.getProperty().setOpacity(opacity));

                        // Opacity changes are cheap, but 3x render might be heavy. 
                        // Using requestAnimationFrame ensures we don't render more than 60fps.
                        requestAnimationFrame(() => {
                            allRenderWindows.forEach(rw => rw.getRenderWindow().render());
                        });
                    }
                });

                // Setup colormap selector
                if (colormapSelect) {
                    colormapSelect.addEventListener('change', (e) => {
                        if (heatmapActors.length > 0) {
                            setColormap(e.target.value);
                        }
                    });
                }

                // Setup hover handler for heatmap values
                allRenderWindows.forEach((renWin, idx) => {
                    const domElement = renWin.getContainer();
                    if (domElement) {
                        domElement.addEventListener('mousemove', (event) => {
                            if (!heatmapToggle.checked || !heatmapData || heatmapActors.length === 0) return;

                            const rect = domElement.getBoundingClientRect();
                            const x = event.clientX - rect.left;
                            const y = event.clientY - rect.top;

                            // Try to pick at this position
                            try {
                                const picker2 = vtkPicker.newInstance();
                                picker2.setTolerance(0.005);
                                picker2.initialize();
                                picker2.pick([x, y, 0.0], renWin.getRenderer());

                                if (picker2.getActors().length > 0) {
                                    const pickedPoint = picker2.getPickPosition();
                                    const worldToIndex = heatmapData.worldToIndex(pickedPoint);
                                    const i = Math.round(worldToIndex[0]);
                                    const j = Math.round(worldToIndex[1]);
                                    const k = Math.round(worldToIndex[2]);

                                    // Get the actual scalar value from heatmap data
                                    try {
                                        const scalars = heatmapData.getPointData().getScalars();
                                        const dims = heatmapData.getDimensions();

                                        // Check bounds
                                        if (i >= 0 && i < dims[0] && j >= 0 && j < dims[1] && k >= 0 && k < dims[2]) {
                                            const index = i + j * dims[0] + k * dims[0] * dims[1];
                                            if (index >= 0 && index < scalars.getNumberOfTuples()) {
                                                const value = scalars.getValue(index);
                                                if (heatmapValueReadout) {
                                                    heatmapValueReadout.textContent = `${value.toFixed(2)}`;
                                                }
                                            }
                                        }
                                    } catch (e) {
                                        // Silently fail if unable to read value
                                    }
                                }
                            } catch (e) {
                                // Silently fail picker
                            }
                        });

                        // Reset display on mouse leave
                        domElement.addEventListener('mouseleave', () => {
                            if (heatmapValueReadout) {
                                heatmapValueReadout.textContent = '--';
                            }
                        });
                    }
                });

                // Log status
                if (heatmapData && heatmapActors.length > 0) {
                    console.log(`✓ Heatmap system initialized with ${heatmapActors.length} actors`);
                } else {
                    console.warn(`⚠ Heatmap controls enabled but no data loaded. heatmapData: ${!!heatmapData}, actors: ${heatmapActors.length}`);
                }
            } else {
                console.warn("Heatmap control elements not found in DOM");
            }

            resetButton.addEventListener('click', resetViews);
            resetViews();

            loadingOverlay.style.display = 'none';
            allRenderWindows.forEach(r => r.resize());

        } catch (error) {
            console.error('Failed to initialize VTK.js viewer:', error);
            loadingMessage.innerHTML = `<p class="text-danger">Error: ${error.message}</p>`;
        }
    }

    function setupAIProbabilityGraph() {
        const configElement = document.getElementById('viewer-config');
        if (!configElement) {
            console.error('viewer-config element not found');
            return;
        }

        let config;
        try {
            config = JSON.parse(configElement.textContent);
        } catch (e) {
            console.error('Failed to parse viewer-config:', e);
            return;
        }

        const eceProbability = config.eceProbability;
        const analysisContent = document.getElementById('analysisContent');
        const noAnalysisMessage = document.getElementById('noAnalysisMessage');
        const probabilityChart = document.getElementById('probabilityChart');
        const probValue = document.getElementById('probValue');

        console.log('=== setupAIProbabilityGraph ===');
        console.log('Full config:', config);
        console.log('eceProbability value:', eceProbability);
        console.log('eceProbability type:', typeof eceProbability);
        console.log('analysisContent element:', analysisContent);
        console.log('noAnalysisMessage element:', noAnalysisMessage);

        // Show/hide analysis content based on data availability
        const hasValidProbability = eceProbability !== null &&
            eceProbability !== undefined &&
            eceProbability !== 'null' &&
            !isNaN(eceProbability) &&
            eceProbability !== '';

        console.log('hasValidProbability:', hasValidProbability);

        if (hasValidProbability) {
            const nonEceProbability = 1.0 - parseFloat(eceProbability);

            // Show analysis content, hide no-analysis message
            if (analysisContent) analysisContent.style.display = 'block';
            if (noAnalysisMessage) noAnalysisMessage.style.display = 'none';

            console.log('Displaying AI analysis with ECE probability:', eceProbability);

            // Update probability value
            if (probValue) {
                probValue.textContent = `${(parseFloat(eceProbability) * 100).toFixed(1)}`;
            }

            // Create Doughnut Chart
            if (probabilityChart && probabilityChart.getContext) {
                try {
                    const ctx = probabilityChart.getContext('2d');

                    // Destroy existing chart if it exists
                    const existingChart = Chart.getChart(ctx);
                    if (existingChart) {
                        existingChart.destroy();
                    }

                    new Chart(ctx, {
                        type: 'doughnut',
                        data: {
                            labels: ['ECE Risk', 'Non-ECE'],
                            datasets: [{
                                data: [parseFloat(eceProbability), nonEceProbability],
                                backgroundColor: [
                                    'rgba(220, 53, 69, 0.8)',    // Red for ECE Risk
                                    'rgba(40, 167, 69, 0.8)'     // Green for Non-ECE
                                ],
                                borderColor: [
                                    'rgba(220, 53, 69, 1)',
                                    'rgba(40, 167, 69, 1)'
                                ],
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: true,
                            circumference: 360,
                            rotation: 0,
                            plugins: {
                                legend: {
                                    position: 'bottom',
                                    labels: {
                                        color: '#f8f9fa',
                                        font: {
                                            size: 11,
                                            weight: '500'
                                        },
                                        padding: 8,
                                        usePointStyle: true
                                    }
                                },
                                title: {
                                    display: true,
                                    text: 'ECE Probability',
                                    color: '#f8f9fa',
                                    font: {
                                        size: 13,
                                        weight: 'bold'
                                    },
                                    padding: 8
                                },
                                datalabels: {
                                    color: '#f8f9fa',
                                    font: {
                                        weight: 'bold',
                                        size: 11
                                    },
                                    formatter: (value) => `${(value * 100).toFixed(1)}%`
                                },
                                tooltip: {
                                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                                    titleColor: '#f8f9fa',
                                    bodyColor: '#f8f9fa',
                                    borderColor: '#f8f9fa',
                                    borderWidth: 1,
                                    padding: 8,
                                    titleFont: {
                                        size: 12,
                                        weight: 'bold'
                                    },
                                    bodyFont: {
                                        size: 11
                                    },
                                    callbacks: {
                                        label: function (context) {
                                            return `${context.label}: ${(context.parsed * 100).toFixed(1)}%`;
                                        }
                                    }
                                }
                            }
                        }
                    });

                    console.log('✓ Doughnut chart created successfully');
                } catch (e) {
                    console.error('✗ Failed to create AI probability chart:', e);
                }
            } else {
                console.warn('probabilityChart element not found or no getContext method');
            }
        } else {
            console.log('No valid AI probability data, showing default message');
            if (analysisContent) analysisContent.style.display = 'none';
            if (noAnalysisMessage) noAnalysisMessage.style.display = 'block';
        }
    }

    setupVtk();
    setupAIProbabilityGraph();
});