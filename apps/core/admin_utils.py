import csv

from django.contrib import admin
from django.http import HttpResponse


@admin.action(description="Export selected to CSV")
def export_as_csv(modeladmin, request, queryset):
    meta = modeladmin.model._meta
    names = [f.name for f in meta.fields]
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f"attachment; filename={meta.model_name}s.csv"
    writer = csv.writer(response)
    writer.writerow(names)
    for obj in queryset:
        writer.writerow([str(getattr(obj, n)) for n in names])
    return response
