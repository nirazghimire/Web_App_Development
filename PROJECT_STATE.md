# Slicer Web App: Current Project State
*Last Updated: March 30, 2026*

This document serves as a memory bridge for future sessions. You can feed this to the AI or refer to it to know exactly where the project stands.

## 1. Security & Production Hardening (Completed)
- **Environment Variables**: Moved sensitive keys (SECRET_KEY, DB passwords) into `.env.prod`.
- **Git Ignore**: Added `.env.prod` to `.gitignore` to prevent leaking credentials to GitHub.
- **Django Settings**: Updated `settings.py` to securely read database credentials from environment variables instead of hardcoded maps.
- **Docker Security**: Modified `Dockerfile` to run the application as a secure, non-root `appuser`.
- **Performance**: Upgraded Gunicorn configuration in `docker-compose.yml` to run with 3 workers, preventing the application from freezing during heavy DICOM processing.

## 2. Cloud Infrastructure Deployment (Completed)
- **Host**: Deployed to Google Cloud Platform (GCP) Compute Engine.
- **Machine Specs**: `e2-medium` (2 vCPU, 4GB RAM), Ubuntu 24.04 LTS, 30GB Boot Disk.
- **Current Status**: The server is fully operational. We installed Docker and `docker-compose`, securely cloned the repository, and manually built the `.env.prod` on the server using `cat << 'EOF'`.

## 3. New Feature: User Registration Flow (Completed)
- **Problem**: The app originally only had a Login page, blocking new users.
- **Solution**: Built a full User Registration flow using Django's secure `UserCreationForm`.
- **Implementation**: 
  - Added `register` logic in `dicom_processor/views.py` with automatic login and validation.
  - Added `path('register/')` routing to `SlicerWebApp/urls.py`.
  - Built `register.html` template using Bootstrap Cards to match the existing login design.
  - Updated the navbar in `base.html` to dynamically show the "Register" button to logged-out users.

## 4. Machine Learning Model Integration (Completed)
- **The Issue**: Git intentionally ignores massive files. Therefore, our `checkpoint_v2_1` AI models were missing from the GCP Server after cloning. Heatmap generation crashed giving a "No model checkpoint found" error on the dashboard.
- **The Solution**: 
  - Manually compressed `checkpoint_v2_1` into a zip file on the local machine.
  - Used the Cloud Console SSH "Upload File" tool to securely transfer the zip to the GCP Server's home directory.
  - Unzipped the model directly into `~/Web_App_Development/SlicerWebApp/dicom_processor/`.
  - Ran `docker compose ... up -d --build` to force Docker to ingest the newly uploaded AI models into the live container environment.

## 5. Domain & SSL Setup (Completed Config)
- **Domain**: `siollab.duckdns.org` (via DuckDNS).
- **SSL**: Configured Let's Encrypt automated SSL certificate generation using a `certbot` Docker container.
- **NGINX**: Updated reverse proxy to handle ACME challenge over port 80 and serve HTTPS traffic securely over port 443.
- **Deployment Status**: Code is prepared locally. Awaiting a `git push` to the GCP Server and a run of the newly provided `init-letsencrypt.sh` script to launch the secure server.

## Next Steps / Future Enhancements (Ideas for Tomorrow)
- **Frontend Decoupling**: Separate the frontend from Django templates and host via GitHub Pages, refactoring authentication to use Token Auth (JWTs).
- **GCP Cost Saving**: Remember to hit "Stop" on the GCP Console to save money when not actively demoing or testing the app.
- **Cloud Storage**: Consider migrating the actual uploaded DICOM files from the Docker volumes to Google Cloud Storage (Bucket) for infinite scale and cheaper object storage.
