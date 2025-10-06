from django.urls import path
from . import views

urlpatterns = [
    path("", views.reversal_list, name="option_reversal_list"),
    path("update/", views.update_reversals, name="update_reversals"),
]
