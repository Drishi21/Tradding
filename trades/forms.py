from django import forms
from .models import Trade

class TradeForm(forms.ModelForm):
    class Meta:
        model = Trade
        fields = ["symbol", "strike_price", "option_type", "entry_price", "stop_loss", "target", "status"]
