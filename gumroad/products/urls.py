from django.urls import path

from .views import ProductDeleteView
from .views import ProductDetailView
from .views import ProductUpdateView

app_name = "products"
urlpatterns = [
    path("<slug>/", ProductDetailView.as_view(), name="product-detail"),
    path("<slug>/update/", ProductUpdateView.as_view(), name="product-update"),
    path("<slug>/delete/", ProductDeleteView.as_view(), name="product-delete"),
]
