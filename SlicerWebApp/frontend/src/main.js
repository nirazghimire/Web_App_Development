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

        try {
            loadingMessage.querySelector('span').textContent = 'Requesting data...';
            const response = await fetch(config.volumeUrl);
            const data = await response.json();
            if (!data.success) throw new Error(data.error);
            const fileContents = await HttpDataAccessHelper.fetchBinary(data.volume_url);
            const reader = vtkXMLImageDataReader.newInstance();
            reader.parseAsArrayBuffer(fileContents);
            const imageData = reader.getOutputData(0);
            const bounds = imageData.getBounds();
            const center = imageData.getCenter();
            const dims = imageData.getDimensions();

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

            const sagittalSlider = document.getElementById('sagittalSlider');
            const coronalSlider = document.getElementById('coronalSlider');
            const axialSlider = document.getElementById('axialSlider');
            const sagittalSliceLabel = document.getElementById('sagittalSliceLabel');
            const coronalSliceLabel = document.getElementById('coronalSliceLabel');
            const axialSliceLabel = document.getElementById('axialSliceLabel');
            const resetButton = document.getElementById('resetViewsButton');

            // --- Heatmap Color Functions ---
            const heatmapCtfun = vtkColorTransferFunction.newInstance();
            heatmapCtfun.addRGBPoint(0, 0, 0, 1);     // Blue
            heatmapCtfun.addRGBPoint(128, 1, 1, 0);   // Yellow
            heatmapCtfun.addRGBPoint(255, 1, 0, 0);   // Red

            const heatmapOfun = vtkPiecewiseFunction.newInstance();
            heatmapOfun.addPoint(0, 0.0);
            heatmapOfun.addPoint(10, 0.0);
            heatmapOfun.addPoint(255, 0.5); // Default max opacity

            function updateAllSlices(i, j, k) {
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

                // Update Heatmap Mappers
                if (heatmapMappers[0]) heatmapMappers[0].setSlice(i);
                if (heatmapMappers[1]) heatmapMappers[1].setSlice(j);
                if (heatmapMappers[2]) heatmapMappers[2].setSlice(k);

                allRenderWindows.forEach(rw => {
                    rw.getRenderer().resetCameraClippingRange();
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
                        allRenderWindows.forEach(rw => rw.getRenderWindow().render());
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