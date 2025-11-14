// vite.config.js

import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';

// This is the standard way to get __dirname in an ES module
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  // All paths will now be relative to this config file's location (the project root).
  
  build: {
    // This is the output directory for the final bundled file.
    // It creates an absolute path to your Django app's static folder.
    outDir: resolve(__dirname, 'dicom_processor/static/js/dist'),
    
    emptyOutDir: true,

    rollupOptions: {
      // We provide the full path to the entry file from the project root.
      input: 'frontend/src/main.js', 
      
      output: {
        // These settings ensure all output files have predictable names,
        // which is what Django's static system needs.
        entryFileNames: 'vtk.bundle.js',
        chunkFileNames: 'vtk.chunk.js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
});