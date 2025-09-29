from rest_framework import serializers
from .models import OptionChainData, Orders

class OptionChainSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionChainData
        fields = "__all__"

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Orders
        fields = "__all__"
