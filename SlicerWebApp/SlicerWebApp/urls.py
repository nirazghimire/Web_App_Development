# SlicerWebApp/SlicerWebApp/urls.py

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from dicom_processor import views as dicom_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # This line correctly includes all URLs from your app under the '/dicom/' prefix.
    # This will make the path '/dicom/ajax/get_volume_url/...' work.
    path('dicom/', include('dicom_processor.urls')),

    # --- Auth and Main Page URLs ---
    path('login/', auth_views.LoginView.as_view(template_name='dicom_processor/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='dicom_processor:home'), name='logout'),
    
    # --- Root Redirect ---
    # Redirect the root URL ('/') to the main app page ('/dicom/').
    path('', RedirectView.as_view(url='/dicom/', permanent=True)),
]



# Compatibility redirect for old bookmarks / external links that used
# the top-level `/my_uploads/` path. The app's real route is
# `/dicom/my-uploads/` (defined in `dicom_processor.urls`).
urlpatterns += [
    path('my_uploads/', RedirectView.as_view(url='/dicom/my-uploads/', permanent=True)),
]

# This is important for serving user-uploaded files (like the .vti) during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', dicom_views.secure_media_serve, name='secure_media'),
    ]
