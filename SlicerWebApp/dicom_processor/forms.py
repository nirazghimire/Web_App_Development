from django import forms

from django import forms

class DicomUploadForm(forms.Form):
    name = forms.CharField(max_length=255)
