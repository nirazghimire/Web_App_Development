"""
URL configuration for SlicerWebApp project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from dicom_processor import views as dicom_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('dicom/', include('dicom_processor.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='dicom_processor/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    path('', dicom_views.home, name='home'),
    path('my-uploads/', dicom_views.my_uploads, name='my_uploads'),
    path('view/<int:series_id>/', dicom_views.view_result, name='view_result'),

    #dashboard path where it will take the use to the dashboard page with all four views.
    path('dashboard/<int:series_id>/', dicom_views.dashboard_view, name='dashboard_series_view'),

    #if there is no id, then redirect it to the latest dashboard view:
    path('dashboard/', dicom_views.dashboard_view, name='dashboard_latest_view'),
   
]

if settings.DEBUG:
    # This line serves  user-uploaded media files (like .nrrd files)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # This NEW line serves  project's static files (like vtk.js)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)



