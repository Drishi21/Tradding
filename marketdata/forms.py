
from django import forms
from .models import MarketRecord

class MarketRecordForm(forms.ModelForm):
    class Meta:
        model = MarketRecord
        fields = "__all__"
