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
        heatmapCtfun.addRGBPoint(0, 0, 0, 0);       // Black/Transparent at 0
        heatmapCtfun.addRGBPoint(10, 0.0, 0.0, 1.0); // Blue starts
        heatmapCtfun.addRGBPoint(96, 0.0, 1.0, 1.0); // Cyan
        heatmapCtfun.addRGBPoint(160, 0.0, 1.0, 0.0); // Green
        heatmapCtfun.addRGBPoint(224, 1.0, 1.0, 0.0); // Yellow
        heatmapCtfun.addRGBPoint(255, 1.0, 0.0, 0.0); // Red

        const heatmapOfun = vtkPiecewiseFunction.newInstance();
        heatmapOfun.addPoint(0, 0.0);
        heatmapOfun.addPoint(10, 0.0);
        heatmapOfun.addPoint(255, 0.5); // Default max opacity

        try {
            loadingMessage.querySelector('span').textContent = 'Requesting data...';
            const response = await fetch(config.volumeUrl);
            const data = await response.json();
            if (!data.success) throw new Error(data.error);
            const fileContents = await HttpDataAccessHelper.fetchBinary(data.volume_url);
            const reader = vtkXMLImageDataReader.newInstance();
            reader.parseAsArrayBuffer(fileContents);

            const imageData = reader.getOutputData(0);

            // --- Load Heatmap Data if available ---
            let heatmapData = null;
            if (config.heatmapUrl) {
                try {
                    console.log('Fetching heatmap from URL:', config.heatmapUrl);
                    const hResponse = await fetch(config.heatmapUrl);
                    const hData = await hResponse.json();
                    if (hData.success) {
                        const hFileContents = await HttpDataAccessHelper.fetchBinary(hData.heatmap_url);
                        const hReader = vtkXMLImageDataReader.newInstance();
                        hReader.parseAsArrayBuffer(hFileContents);
                        heatmapData = hReader.getOutputData(0);
                        console.log('Heatmap loaded. Dimensions:', heatmapData.getDimensions());
                    }
                } catch (e) {
                    console.error("Failed to load heatmap:", e);
                }
            }

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

            function updateAllSlices(i, j, k) {
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
                    const hMapper = vtkImageMapper.newInstance();
                    hMapper.setInputData(heatmapData);
                    hMapper.setSlicingMode(viewConfig.axis);
                    heatmapMappers[viewConfig.axis] = hMapper;

                    const hActor = vtkImageSlice.newInstance();
                    hActor.setMapper(hMapper);
                    hActor.getProperty().setRGBTransferFunction(heatmapCtfun);
                    hActor.getProperty().setScalarOpacity(heatmapOfun);
                    hActor.getProperty().setOpacity(0.5); // Initial opacity
                    hActor.setVisibility(false); // Hidden by default

                    renderer.addActor(hActor);
                    heatmapActors.push(hActor);
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
                    const pos = event.position;
                    picker.initialize();
                    picker.pick([pos.x, pos.y, 0.0], renderer);
                    if (picker.getActors().length > 0) {
                        const pickedPoint = picker.getPickPosition();
                        const worldToIndex = imageData.worldToIndex(pickedPoint);
                        const i = Math.round(worldToIndex[0]);
                        const j = Math.round(worldToIndex[1]);
                        const k = Math.round(worldToIndex[2]);
                        updateAllSlices(i, j, k);
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
                const i = parseInt(e.target.value, 10);
                updateAllSlices(i, sliceMappers[1].getSlice(), sliceMappers[2].getSlice());
            });

            coronalSlider.addEventListener('input', (e) => {
                const j = parseInt(e.target.value, 10);
                updateAllSlices(sliceMappers[0].getSlice(), j, sliceMappers[2].getSlice());
            });

            axialSlider.addEventListener('input', (e) => {
                const k = parseInt(e.target.value, 10);
                updateAllSlices(sliceMappers[0].getSlice(), sliceMappers[1].getSlice(), k);
            });

            // --- Heatmap Controls ---
            const heatmapToggle = document.getElementById('heatmapToggle');
            const heatmapControls = document.getElementById('heatmapControls');
            const opacitySlider = document.getElementById('opacitySlider');

            if (heatmapToggle && heatmapControls && opacitySlider) {
                if (heatmapData) {
                    heatmapToggle.addEventListener('change', (e) => {
                        const visible = e.target.checked;
                        heatmapActors.forEach(actor => actor.setVisibility(visible));
                        heatmapControls.style.display = visible ? 'flex' : 'none';
                        // Force re-render
                        allRenderWindows.forEach(rw => rw.getRenderWindow().render());
                    });

                    opacitySlider.addEventListener('input', (e) => {
                        const opacity = parseFloat(e.target.value);
                        heatmapActors.forEach(actor => actor.getProperty().setOpacity(opacity));

                        // Opacity changes are cheap, but 3x render might be heavy. 
                        // Using requestAnimationFrame ensures we don't render more than 60fps.
                        requestAnimationFrame(() => {
                            allRenderWindows.forEach(rw => rw.getRenderWindow().render());
                        });
                    });
                } else {
                    // Disable toggle if no heatmap
                    heatmapToggle.disabled = true;
                    heatmapToggle.parentElement.title = "No heatmap available";
                }
            } else {
                console.warn("Heatmap controls not found in DOM. Skipping event listeners.");
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

    function setupChart() {
        const config = JSON.parse(document.getElementById('viewer-config').textContent);
        const eceProbability = config.eceProbability;
        if (eceProbability !== null && document.getElementById('probabilityChart')) {
            const ctx = document.getElementById('probabilityChart').getContext('2d');
            const nonEceProbability = 1.0 - eceProbability;
            new Chart(ctx, { type: 'bar', data: { labels: ['ECE', 'Non-ECE'], datasets: [{ data: [eceProbability, nonEceProbability], backgroundColor: ['rgba(217, 83, 79, 0.7)', 'rgba(91, 192, 222, 0.7)'], borderColor: ['rgba(217, 83, 79, 1)', 'rgba(91, 192, 222, 1)'], borderWidth: 1, barPercentage: 0.6, categoryPercentage: 0.7 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Prediction Probability' }, datalabels: { display: true, color: 'black', font: { weight: 'bold' }, anchor: 'end', align: 'end', formatter: (value) => `${(value * 100).toFixed(1)}%` } }, scales: { x: { beginAtZero: true, max: 1.0, title: { display: true, text: 'Probability Score' } }, y: { grid: { display: false } } } } });
        }
    }

    setupVtk();
    setupChart();
});