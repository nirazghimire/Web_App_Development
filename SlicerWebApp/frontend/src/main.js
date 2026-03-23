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
import vtkLookupTable from '@kitware/vtk.js/Common/Core/LookupTable';

import vtkPicker from '@kitware/vtk.js/Rendering/Core/Picker';

import vtkWidgetManager from '@kitware/vtk.js/Widgets/Core/WidgetManager';
import vtkSplineWidget from '@kitware/vtk.js/Widgets/Widgets3D/SplineWidget';
import vtkPlanePointManipulator from '@kitware/vtk.js/Widgets/Manipulators/PlaneManipulator';
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
        const heatmapMappers = {}; // Heatmap overlay mappers
        const heatmapActors = []; // All heatmap actors for visibility/opacity control

        // Crosshair Storage
        const crosshairActors = {}; // { axis: { h: actor, v: actor } }

        const sagittalSlider = document.getElementById('sagittalSlider');
        const coronalSlider = document.getElementById('coronalSlider');
        const axialSlider = document.getElementById('axialSlider');
        const sagittalSliceLabel = document.getElementById('sagittalSliceLabel');
        const coronalSliceLabel = document.getElementById('coronalSliceLabel');
        const axialSliceLabel = document.getElementById('axialSliceLabel');
        const resetButton = document.getElementById('resetViewsButton');

        // --- COLORMAP PRESETS ---
        const colormapPresets = {
            viridis: {
                points: [
                    [0, 0.267004, 0.004874, 0.329415],
                    [64, 0.282623, 0.140926, 0.457517],
                    [128, 0.127568, 0.566949, 0.550556],
                    [192, 0.369214, 0.788888, 0.382914],
                    [255, 0.993248, 0.906157, 0.143936]
                ],
                gradient: 'linear-gradient(to right, #440154, #3b528b, #21908d, #5dc863, #fde725)'
            },
            plasma: {
                points: [
                    [0, 0.050383, 0.029803, 0.527975],
                    [64, 0.417642, 0.000564, 0.658390],
                    [128, 0.798216, 0.280197, 0.469538],
                    [192, 0.976435, 0.582842, 0.255561],
                    [255, 0.940015, 0.975158, 0.131326]
                ],
                gradient: 'linear-gradient(to right, #0d0887, #7e03a8, #cc4778, #f89540, #f0f921)'
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
            turbo: {
                points: [
                    [0, 0.18995, 0.07176, 0.23217],
                    [64, 0.09140, 0.40830, 0.92540],
                    [128, 0.28647, 0.86765, 0.50068],
                    [192, 0.87819, 0.67555, 0.11765],
                    [255, 0.69350, 0.09450, 0.12000]
                ],
                gradient: 'linear-gradient(to right, #30123b, #1760a0, #45c16f, #e0b826, #b11516)'
            }
        };

        let currentColormap = 'viridis';

        // Heatmap color transfer function
        const heatmapCtfun = vtkColorTransferFunction.newInstance();

        // Heatmap opacity transfer function (low values transparent)
        const heatmapOfun = vtkPiecewiseFunction.newInstance();
        heatmapOfun.addPoint(0, 0.0);
        heatmapOfun.addPoint(120, 0.0);   // Hide more background (approx below 47%) - reduces "square" look
        heatmapOfun.addPoint(160, 0.3);   // Smooth transition
        heatmapOfun.addPoint(220, 0.7);
        heatmapOfun.addPoint(255, 0.9);   // High visibility for top risk

        // Apply initial colormap
        function applyColormap(name) {
            const preset = colormapPresets[name];
            if (!preset) return;

            heatmapCtfun.removeAllPoints();
            preset.points.forEach(p => heatmapCtfun.addRGBPoint(p[0], p[1], p[2], p[3]));

            const gradientEl = document.getElementById('colormapGradient');
            if (gradientEl) gradientEl.style.background = preset.gradient;

            currentColormap = name;
        }
        applyColormap('hot');

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

            // Extract volume geometry early so we can compare with heatmap
            const bounds = imageData.getBounds(); // [xmin, xmax, ymin, ymax, zmin, zmax]
            const center = imageData.getCenter();
            const dims = imageData.getDimensions();
            const spacing = imageData.getSpacing();
            const origin = imageData.getOrigin();

            console.log('📦 Volume geometry: dims=', dims, 'spacing=', spacing, 'origin=', origin);

            // --- Load Heatmap Data if available ---
            let heatmapData = null;
            console.log('🔍 DEBUG: config.heatmapUrl =', config.heatmapUrl);
            if (config.heatmapUrl) {
                try {
                    updateLoading('Loading attention overlay...', 4, 5);
                    console.log('🔄 Fetching heatmap endpoint:', config.heatmapUrl);
                    const hResponse = await fetch(config.heatmapUrl);
                    const hData = await hResponse.json();
                    console.log('📥 Heatmap AJAX response:', hData);
                    if (hData.success && hData.heatmap_url) {
                        console.log('⬇️ Downloading heatmap binary from:', hData.heatmap_url);
                        const hBinary = await HttpDataAccessHelper.fetchBinary(hData.heatmap_url);
                        console.log('📦 Heatmap binary size:', hBinary.byteLength, 'bytes');
                        const hReader = vtkXMLImageDataReader.newInstance();
                        hReader.parseAsArrayBuffer(hBinary);
                        heatmapData = hReader.getOutputData(0);

                        // force heatmap to match volume geometry EXACTLY
                        // This fixes the issue where heatmap origin is different from volume origin
                        console.log('⚠️ OVERRIDING HEATMAP GEOMETRY TO MATCH VOLUME');
                        heatmapData.setOrigin(imageData.getOrigin());
                        heatmapData.setSpacing(imageData.getSpacing());
                        heatmapData.setDirection(imageData.getDirection());

                        console.log('✅ Heatmap loaded.');

                        // Check scalar range
                        const scalars = heatmapData.getPointData().getScalars();
                        if (scalars) {
                            const range = scalars.getRange();
                            console.log('📊 Heatmap scalar range:', range);
                            if (range[1] === 0) {
                                console.error('❌ CRITICAL: Heatmap max value is 0 - NO DATA!');
                            }
                        }
                    } else {
                        console.warn('⚠️ Heatmap AJAX failed or no URL:', hData);
                    }
                } catch (e) {
                    console.error('❌ Failed to load heatmap:', e);
                }
            } else {
                console.log('ℹ️ No heatmapUrl in config - heatmap disabled');
            }

            updateLoading('Setting up 3D visualization...', 5, 5);

            // Geometry variables (bounds, center, dims, spacing, origin) are already defined above

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

                // Update Base Mappers
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

                // Update Heatmap Mappers (keep synced with base)
                if (heatmapMappers[0]) heatmapMappers[0].setSlice(i);
                if (heatmapMappers[1]) heatmapMappers[1].setSlice(j);
                if (heatmapMappers[2]) heatmapMappers[2].setSlice(k);

                // --- UPDATE CROSSHAIRS ---
                updateCrosshairs(i, j, k);

                allRenderWindows.forEach(rw => {
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
                // Set interactor style to Image (2D) for slice views
                const sliceInteractorStyle = vtkInteractorStyleImage.newInstance();
                sliceInteractorStyle.setInteractionMode('IMAGE_SLICING'); // Ensure slicing mode
                renWin.getInteractor().setInteractorStyle(sliceInteractorStyle);

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
                slice.setPickable(true); // Ensure main slice is pickable
                renderer.addActor(slice);

                // Heatmap Overlay (if available)
                if (heatmapData) {
                    console.log(`🎨 Creating heatmap overlay for ${viewConfig.id} (axis ${viewConfig.axis})`);
                    const hMapper = vtkImageMapper.newInstance();
                    hMapper.setInputData(heatmapData);
                    hMapper.setSlicingMode(viewConfig.axis);
                    heatmapMappers[viewConfig.axis] = hMapper;

                    const hActor = vtkImageSlice.newInstance();
                    hActor.setMapper(hMapper);

                    // Restore Transfer Functions
                    hActor.getProperty().setRGBTransferFunction(0, heatmapCtfun);
                    hActor.getProperty().setScalarOpacity(0, heatmapOfun);
                    hActor.getProperty().setInterpolationTypeToLinear(); // Ensure smooth gradients
                    hActor.getProperty().setOpacity(1.0);

                    // CRITICAL: Offset the heatmap towards the camera to render in front
                    // Larger offset to ensure it's clearly in front
                    const offsetAmount = 1.0; // 1mm offset
                    const pos = [0, 0, 0];
                    // Camera positions: axis0 looks from -X, axis1 from -Y, axis2 from +Z
                    switch (viewConfig.axis) {
                        case 0: pos[0] = offsetAmount; break; // Sagittal: offset towards -X (camera)
                        case 1: pos[1] = offsetAmount; break; // Coronal: offset towards -Y (camera)
                        case 2: pos[2] = offsetAmount; break;  // Axial: offset towards +Z (camera)
                    }
                    hActor.setPosition(pos);
                    console.log(`   Heatmap position offset: [${pos.join(', ')}]`);

                    hActor.setVisibility(false); // Hidden by default
                    hActor.setPickable(false); // Heatmap should not block picking
                    renderer.addActor(hActor);
                    heatmapActors.push(hActor);
                    console.log(`✅ Heatmap actor added. Total actors: ${heatmapActors.length}`);
                } else {
                    console.log(`⚠️ No heatmap data for ${viewConfig.id}`);
                }

                // Add Crosshair Actor for this view
                const ch = createCrosshairActor(viewConfig.axis);
                ch.actor.setPickable(false); // Crosshairs should not be pickable
                crosshairActors[viewConfig.axis] = ch;
                renderer.addActor(ch.actor);

                viewConfig.slider.max = dims[viewConfig.axis] - 1;

                camera.setParallelProjection(true);
                renderer.resetCamera();
                switch (viewConfig.axis) {
                    case 0: camera.setPosition(bounds[1] + 1, center[1], center[2]); camera.setViewUp(0, 0, -1); camera.setParallelScale((bounds[5] - bounds[4]) / 2); break;
                    case 1: camera.setPosition(center[0], bounds[3] + 1, center[2]); camera.setViewUp(0, 0, -1); camera.setParallelScale((bounds[5] - bounds[4]) / 2); break;
                    case 2: camera.setPosition(center[0], center[1], bounds[5] + 1); camera.setViewUp(0, 1, 0); camera.setParallelScale((bounds[3] - bounds[2]) / 2); break;
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
                    const pos = event.position;
                    picker.initialize();
                    picker.pick([pos.x, pos.y, 0.0], renderer);

                    if (picker.getActors().length > 0) {
                        const pickedPoint = picker.getPickPosition();
                        const worldToIndex = imageData.worldToIndex(pickedPoint);

                        let i = Math.round(worldToIndex[0]);
                        let j = Math.round(worldToIndex[1]);
                        let k = Math.round(worldToIndex[2]);

                        // IMPORTANT: Only update the coordinates visible in this view
                        // Keep the perpendicular axis at its current slice
                        const currentI = sliceMappers[0].getSlice();
                        const currentJ = sliceMappers[1].getSlice();
                        const currentK = sliceMappers[2].getSlice();

                        // Based on view orientation, keep the perpendicular axis unchanged
                        switch (viewConfig.axis) {
                            case 0: // Sagittal view: shows Y-Z plane, keep X unchanged
                                i = currentI;
                                break;
                            case 1: // Coronal view: shows X-Z plane, keep Y unchanged
                                j = currentJ;
                                break;
                            case 2: // Axial view: shows X-Y plane, keep Z unchanged
                                k = currentK;
                                break;
                        }

                        updateAllSlices(i, j, k);

                        // Prevent default interactor behavior from interfering
                        // Check if callData exists before setting handled
                        if (event && event.callData) {
                            event.callData.handled = true;
                        }
                    }
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

            // --- Heatmap Control Handlers ---
            const heatmapToggle = document.getElementById('heatmapToggle');
            const heatmapControls = document.getElementById('heatmapControls');
            const opacitySlider = document.getElementById('opacitySlider');
            const opacityValueEl = document.getElementById('opacityValue');
            const colormapSelect = document.getElementById('colormapSelect');

            if (heatmapToggle) {
                heatmapToggle.addEventListener('change', (e) => {
                    const visible = e.target.checked;
                    heatmapActors.forEach((actor) => {
                        actor.setVisibility(visible);
                    });

                    if (heatmapControls) {
                        heatmapControls.style.display = visible ? 'block' : 'none';
                    }

                    allRenderWindows.forEach((rw) => {
                        rw.getRenderWindow().render();
                    });
                });

                // Disable toggle if no heatmap data
                if (heatmapActors.length === 0) {
                    heatmapToggle.disabled = true;
                    heatmapToggle.parentElement.title = 'No attention data available';
                }
            } else {
                console.error('❌ heatmapToggle element not found!');
            }

            if (opacitySlider) {
                opacitySlider.addEventListener('input', (e) => {
                    const opacity = parseFloat(e.target.value);
                    if (opacityValueEl) opacityValueEl.textContent = Math.round(opacity * 100) + '%';
                    heatmapActors.forEach(actor => actor.getProperty().setOpacity(opacity));
                    requestAnimationFrame(() => {
                        allRenderWindows.forEach(rw => rw.getRenderWindow().render());
                    });
                });
            }

            if (colormapSelect) {
                colormapSelect.addEventListener('change', (e) => {
                    applyColormap(e.target.value);
                    heatmapActors.forEach(actor => {
                        actor.getProperty().setRGBTransferFunction(heatmapCtfun);
                    });
                    allRenderWindows.forEach(rw => rw.getRenderWindow().render());
                });
            }

            resetButton.addEventListener('click', resetViews);
            resetViews();

            // --- WIDGET MANAGER SETUP ---
            const widgetManagers = [];
            const toolWidgets = {
                pencil: []
            };
            const viewManipulators = {}; // Store manipulators to update their origin

            // Helper to get current slice position for a view
            function getSliceOrigin(axis) {
                if (typeof axis === 'undefined') return [0, 0, 0]; // 3D view
                const i = sliceMappers[0].getSlice();
                const j = sliceMappers[1].getSlice();
                const k = sliceMappers[2].getSlice();

                // Convert indices to world coordinates
                const x = origin[0] + i * spacing[0];
                const y = origin[1] + j * spacing[1];
                const z = origin[2] + k * spacing[2];

                return [x, y, z];
            }

            // Function to update all manipulators when slices change
            // This fixes the issue where drawing on Axial view (Z > 0) failed 
            // because the plane was stuck at Z=0.
            function updateManipulators() {
                const i = sliceMappers[0].getSlice();
                const j = sliceMappers[1].getSlice();
                const k = sliceMappers[2].getSlice();

                // Calculate world coordinates
                const x = origin[0] + i * spacing[0];
                const y = origin[1] + j * spacing[1];
                const z = origin[2] + k * spacing[2];

                // Update Sagittal (Axis 0) - Plane X
                if (viewManipulators[0]) {
                    viewManipulators[0].setUserOrigin([x, 0, 0]);
                }
                // Update Coronal (Axis 1) - Plane Y
                if (viewManipulators[1]) {
                    viewManipulators[1].setUserOrigin([0, y, 0]);
                }
                // Update Axial (Axis 2) - Plane Z
                if (viewManipulators[2]) {
                    viewManipulators[2].setUserOrigin([0, 0, z]);
                }
            }

            // Hook into updateAllSlices to update manipulators
            const originalUpdateAllSlices = updateAllSlices;
            updateAllSlices = function (i, j, k) {
                originalUpdateAllSlices(i, j, k);
                updateManipulators();
            };

            // Initialize widgets for ALL views (including 3D)
            allRenderWindows.forEach((renWin, index) => {
                const is2D = index < sliceViewConfigs.length;
                const viewConfig = is2D ? sliceViewConfigs[index] : null;
                const axis = viewConfig ? viewConfig.axis : undefined;

                const renderer = renWin.getRenderer();
                const manager = vtkWidgetManager.newInstance();
                manager.setRenderer(renderer);

                widgetManagers.push(manager);

                // --- SPLINE WIDGET (Pencil/Contour) ---
                const sWidget = vtkSplineWidget.newInstance();
                if (is2D) {
                    // Reuse the same manipulator if possible, or create a new one tracked same way
                    // Creating new one to be safe and simple
                    const manip = vtkPlanePointManipulator.newInstance();
                    switch (axis) {
                        case 0: manip.setUserNormal(1, 0, 0); break;
                        case 1: manip.setUserNormal(0, 1, 0); break;
                        case 2: manip.setUserNormal(0, 0, 1); break;
                    }
                    sWidget.setManipulator(manip);

                    // Add to our update list (we can support multiple per view or just group them)
                    // Simple hack: We'll update ALL manipulators in the view loop
                    // But wait, viewManipulators is 1:1 with axis. 
                    // Let's make viewManipulators an array of manipulators per axis to be robust.
                }

                const sHandle = manager.addWidget(sWidget);
                sHandle.setOutputBorder(true);
                // sHandle.setFreehand(true); // Removed as it caused TypeError

                // Styling
                // sHandle.getRepresentations()[0].getActors()[0].getProperty().setColor(0, 1, 0.5); // Spring Green

                toolWidgets.pencil.push({ widget: sWidget, handle: sHandle, manager });
            });

            // Re-implement updateManipulators to handle multiple tools correctly
            // (Redefine here to close over the actual instances if needed, or stick to the simple one above)
            // The simple one above only stored ONE manipulator per axis. We need to support both tools.
            // Let's redefine viewManipulators to be a list.

            const axisManipulators = { 0: [], 1: [], 2: [] };
            // Re-populate axisManipulators properly
            toolWidgets.pencil.forEach(item => {
                const manip = item.widget.getManipulator();
                if (manip && manip.getUserNormal) {
                    const n = manip.getUserNormal();
                    if (n) {
                        if (n[0] === 1) axisManipulators[0].push(manip);
                        if (n[1] === 1) axisManipulators[1].push(manip);
                        if (n[2] === 1) axisManipulators[2].push(manip);
                    }
                }
            });

            // Improved updateManipulators
            function updateAllManipulators() {
                const i = sliceMappers[0].getSlice();
                const j = sliceMappers[1].getSlice();
                const k = sliceMappers[2].getSlice();

                const x = origin[0] + i * spacing[0];
                const y = origin[1] + j * spacing[1];
                const z = origin[2] + k * spacing[2];

                // Offset to prevent z-fighting (occlusion) - 1.0mm to be safe
                const offset = 1.0;

                axisManipulators[0].forEach(m => m.setUserOrigin([x + offset, 0, 0]));
                axisManipulators[1].forEach(m => m.setUserOrigin([0, y + offset, 0]));
                axisManipulators[2].forEach(m => m.setUserOrigin([0, 0, z + offset]));
            }

            // Override the hook again to use the robust function
            updateAllSlices = function (i, j, k) {
                originalUpdateAllSlices(i, j, k);
                updateAllManipulators();
            };

            // Initial update
            setTimeout(updateAllManipulators, 100);

            // --- TOOLBAR LOGIC ---
            const toolInputs = document.querySelectorAll('input[name="toolMode"]');
            const clearBtn = document.getElementById('clearAnnotationsBtn');

            function updateToolMode() {
                const checkedInput = document.querySelector('input[name="toolMode"]:checked');
                const mode = checkedInput ? checkedInput.value : 'none';
                console.log(`Switching tool mode to: ${mode}`);

                // Disable all first
                toolWidgets.pencil.forEach(item => {
                    item.handle.setEnabled(false);
                });

                // Also disable picking on managers to be safe
                widgetManagers.forEach(m => {
                    m.disablePicking();
                });

                // Re-enable interactions for the selected mode
                if (mode === 'pencil') {
                    toolWidgets.pencil.forEach(item => {
                        item.manager.enablePicking();
                        item.handle.setEnabled(true);
                    });
                }

                allRenderWindows.forEach(rw => rw.getRenderWindow().render());
            }

            // Attach listeners
            toolInputs.forEach(input => {
                input.addEventListener('change', updateToolMode);
            });

            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    if (confirm("Clear all annotations?")) {

                        // MVP: Reloading is safest to avoid lingering state bugs.
                        // 1. Clear Pencil Widgets
                        toolWidgets.pencil.forEach(item => {
                            if (item.manager) {
                                item.manager.removeWidget(item.handle);
                            }
                        });

                        // 2. Reset Arrays
                        toolWidgets.pencil = [];

                        // 3. Re-render
                        allRenderWindows.forEach(rw => rw.getRenderWindow().render());

                        // 4. Reset tool mode
                        updateToolMode();
                    }
                });
            }

            // Initialize default mode
            updateToolMode();



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
                                    display: false
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
                                            if (!context || !context.parsed) return '';
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
