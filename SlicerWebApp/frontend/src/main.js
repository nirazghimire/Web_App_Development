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

document.addEventListener('DOMContentLoaded', function() {
    const config = JSON.parse(document.getElementById('viewer-config').textContent);
    const loadingMessage = document.getElementById('loadingMessage');

    if (!config.seriesId) {
        loadingMessage.innerHTML = `<p class="text-info">No DICOM series loaded. Please select one from <a href="/my_uploads/">My Uploads</a>.</p>`;
        return;
    }

    async function setupVtk() {
        const loadingOverlay = document.getElementById('loadingOverlay');
        const allRenderWindows = [];
        const sliceMappers = {};

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
            
            // --- MODIFICATION: This function will now also call updateHeatmapSlice ---
            function updateAllSlices(i, j, k) {
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
                
                updateHeatmapSlice(); // Sync the heatmap view

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
                const sliceMapper = vtkImageMapper.newInstance();
                sliceMapper.setInputData(imageData);
                sliceMapper.setSlicingMode(viewConfig.axis);
                sliceMappers[viewConfig.axis] = sliceMapper;
                const slice = vtkImageSlice.newInstance();
                slice.setMapper(sliceMapper);
                slice.getProperty().setColorWindow(400);
                slice.getProperty().setColorLevel(40);
                renderer.addActor(slice);
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
            
            // --- START OF NEW HEATMAP IMPLEMENTATION ---
            let heatmap = {
                renWin: null,
                baseMapper: null,
                heatmapMapper: null,
                heatmapActor: null,
                currentAxis: 2, // Default to Axial (axis 2)
            };

            // This function syncs the heatmap's slice to match the main views
            function updateHeatmapSlice() {
                if (!heatmap.baseMapper) return;

                const newSliceIndex = sliceMappers[heatmap.currentAxis].getSlice();
                heatmap.baseMapper.setSlice(newSliceIndex);
                heatmap.heatmapMapper.setSlice(newSliceIndex);
                heatmap.renWin.getRenderWindow().render();
            }

            // This function sets up the entire heatmap panel
            async function setupHeatmap() {
                const heatmapContainer = document.getElementById('heatmapContainer');
                if (!config.heatmapUrl) {
                    heatmapContainer.innerHTML = '<p class="text-info p-3">No heatmap available for this series.</p>';
                    return;
                }

                // 1. Create the renderer and window for the heatmap panel
                heatmap.renWin = vtkGenericRenderWindow.newInstance({ background: [0, 0, 0] });
                heatmap.renWin.setContainer(heatmapContainer);
                allRenderWindows.push(heatmap.renWin);
                const renderer = heatmap.renWin.getRenderer();
                const camera = renderer.getActiveCamera();
                camera.setParallelProjection(true);

                // 2. Setup the base DICOM layer (greyscale)
                heatmap.baseMapper = vtkImageMapper.newInstance();
                heatmap.baseMapper.setInputData(imageData);
                const baseSlice = vtkImageSlice.newInstance();
                baseSlice.setMapper(heatmap.baseMapper);
                renderer.addActor(baseSlice);

                // 3. Load the heatmap .vti data and set it up as an overlay layer
                const heatmapFileContents = await HttpDataAccessHelper.fetchBinary(config.heatmapUrl);
                const heatmapReader = vtkXMLImageDataReader.newInstance();
                heatmapReader.parseAsArrayBuffer(heatmapFileContents);
                const heatmapData = heatmapReader.getOutputData(0);

                heatmap.heatmapMapper = vtkImageMapper.newInstance();
                heatmap.heatmapMapper.setInputData(heatmapData);
                heatmap.heatmapActor = vtkImageSlice.newInstance();
                heatmap.heatmapActor.setMapper(heatmap.heatmapMapper);
                renderer.addActor(heatmap.heatmapActor);

                // 4. Create color (jet colormap) and opacity functions for the heatmap
                const heatmapCtfun = vtkColorTransferFunction.newInstance();
                heatmapCtfun.addRGBPoint(0, 0, 0, 1);     // Blue
                heatmapCtfun.addRGBPoint(0.5, 1, 1, 0);   // Yellow
                heatmapCtfun.addRGBPoint(1.0, 1, 0, 0);   // Red

                const heatmapOfun = vtkPiecewiseFunction.newInstance();
                heatmapOfun.addPoint(0, 0.0);    // Make low values transparent
                heatmapOfun.addPoint(0.2, 0.0);
                heatmapOfun.addPoint(1.0, 0.5);  // Make high values semi-transparent
                
                heatmap.heatmapActor.getProperty().setRGBTransferFunction(heatmapCtfun);
                heatmap.heatmapActor.getProperty().setScalarOpacity(heatmapOfun);
                
                // 5. Connect the HTML controls (dropdown and sliders) to the heatmap view
                const viewSelector = document.getElementById('heatmapViewSelector');
                const windowSlider = document.getElementById('windowSlider');
                const levelSlider = document.getElementById('levelSlider');
                const opacitySlider = document.getElementById('opacitySlider');

                function setHeatmapView(axis) {
                    heatmap.currentAxis = parseInt(axis, 10);
                    heatmap.baseMapper.setSlicingMode(heatmap.currentAxis);
                    heatmap.heatmapMapper.setSlicingMode(heatmap.currentAxis);
                    updateHeatmapSlice();
                    renderer.resetCamera();
                    renderer.resetCameraClippingRange();
                }

                viewSelector.addEventListener('change', (e) => setHeatmapView(e.target.value));
                
                windowSlider.addEventListener('input', (e) => {
                    baseSlice.getProperty().setColorWindow(parseFloat(e.target.value));
                    heatmap.renWin.getRenderWindow().render();
                });
                levelSlider.addEventListener('input', (e) => {
                    baseSlice.getProperty().setColorLevel(parseFloat(e.target.value));
                    heatmap.renWin.getRenderWindow().render();
                });
                opacitySlider.addEventListener('input', (e) => {
                    heatmap.heatmapActor.getProperty().setOpacity(parseFloat(e.target.value));
                    heatmap.renWin.getRenderWindow().render();
                });
                
                // Set initial values from the sliders
                baseSlice.getProperty().setColorWindow(parseFloat(windowSlider.value));
                baseSlice.getProperty().setColorLevel(parseFloat(levelSlider.value));
                heatmap.heatmapActor.getProperty().setOpacity(parseFloat(opacitySlider.value));

                // Initialize the view
                setHeatmapView(viewSelector.value);
            }
            
            await setupHeatmap();
            // --- END OF HEATMAP IMPLEMENTATION ---

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
            new Chart(ctx, { type: 'bar', data: { labels: ['ECE', 'Non-ECE'], datasets: [{ data: [eceProbability, nonEceProbability], backgroundColor: [ 'rgba(217, 83, 79, 0.7)', 'rgba(91, 192, 222, 0.7)' ], borderColor: [ 'rgba(217, 83, 79, 1)', 'rgba(91, 192, 222, 1)' ], borderWidth: 1, barPercentage: 0.6, categoryPercentage: 0.7 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Prediction Probability' }, datalabels: { display: true, color: 'black', font: { weight: 'bold' }, anchor: 'end', align: 'end', formatter: (value) => `${(value * 100).toFixed(1)}%` } }, scales: { x: { beginAtZero: true, max: 1.0, title: { display: true, text: 'Probability Score' } }, y: { grid: { display: false } } } } });
        }
    }
    
    setupVtk();
    setupChart();
});