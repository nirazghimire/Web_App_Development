# Generated by Django 5.2 on 2025-05-06 07:10

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DicomSeries',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('patient_id', models.CharField(blank=True, max_length=50)),
                ('patient_age', models.CharField(blank=True, max_length=10)),
                ('patient_gender', models.CharField(blank=True, max_length=10)),
                ('uploaded_date', models.DateTimeField(auto_now_add=True)),
                ('file_path', models.CharField(max_length=255, unique=True)),
                ('window_center', models.FloatField(default=40)),
                ('window_width', models.FloatField(default=400)),
                ('modality', models.CharField(blank=True, max_length=10)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ProcessingResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('result_file_path', models.CharField(max_length=255)),
                ('processed_date', models.DateTimeField(auto_now_add=True)),
                ('result_type', models.CharField(max_length=50)),
                ('heatmap_intensity', models.FloatField()),
                ('processed_slices', models.IntegerField()),
                ('dicom_series', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='processing_results', to='dicom_processor.dicomseries')),
            ],
        ),
    ]
