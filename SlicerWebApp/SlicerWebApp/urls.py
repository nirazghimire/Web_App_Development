# SlicerWebApp/SlicerWebApp/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from dicom_processor import views as dicom_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # This line correctly includes all URLs from your app under the '/dicom/' prefix.
    # This will make the path '/dicom/ajax/get_volume_url/...' work.
    path('dicom/', include('dicom_processor.urls')),

    # --- Auth and Main Page URLs ---
    path('login/', auth_views.LoginView.as_view(template_name='dicom_processor/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('', dicom_views.home, name='home'),
    path('my-uploads/', dicom_views.my_uploads, name='my_uploads'),
    
    # --- Dashboard URLs ---
    path('dashboard/<int:series_id>/', dicom_views.dashboard_view, name='dashboard_series_view'),
    path('dashboard/', dicom_views.dashboard_view, name='dashboard_home'),
]

# This is important for serving user-uploaded files (like the .vti) during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

