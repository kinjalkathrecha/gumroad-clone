import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.views import generic
from django.views.decorators.csrf import csrf_exempt

from .forms import ProductModelForm
from .models import Product

stripe.api_key = settings.STRIPE_SECRET_KEY


class ProductListView(generic.ListView):
    template_name = "discover.html"
    queryset = Product.objects.filter(active=True)


class ProductDetailView(generic.DetailView):
    template_name = "products/product.html"
    queryset = Product.objects.all()
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY,
            },
        )
        return context


class UserProductListView(LoginRequiredMixin, generic.ListView):
    # shows the user created products
    template_name = "products.html"

    def get_queryset(self):
        return Product.objects.filter(user=self.request.user)


class ProductCreateView(LoginRequiredMixin, generic.CreateView):
    template_name = "products/product_create.html"
    form_class = ProductModelForm

    def get_success_url(self):
        return reverse(
            "products:product-detail",
            kwargs={
                "slug": self.product.slug,
            },
        )

    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.user = self.request.user
        instance.save()
        self.product = instance
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, generic.UpdateView):
    template_name = "products/product_update.html"
    form_class = ProductModelForm

    def get_queryset(self):
        return Product.objects.filter(user=self.request.user)

    def get_success_url(self):
        return reverse(
            "products:product-detail",
            kwargs={
                "slug": self.get_object().slug,
            },
        )


class ProductDeleteView(LoginRequiredMixin, generic.DeleteView):
    template_name = "products/product_delete.html"

    def get_queryset(self):
        return Product.objects.filter(user=self.request.user)

    def get_success_url(self):
        return reverse("user-products")


class CreateCheckoutSessionView(generic.View):
    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, slug=self.kwargs["slug"])

        # This builds the full URL (e.g., http://127.0.0.1:8000/success/)
        # so Stripe knows exactly where to return the user.
        success_url = request.build_absolute_uri("/success/")
        cancel_url = request.build_absolute_uri("/cancel/")

        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": int(product.price),
                            "product_data": {
                                "name": product.name,
                            },
                        },
                        "quantity": 1,
                    },
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return redirect(checkout_session.url, code=303)

        except stripe.error.StripeError:
            # This helps you see if something else went wrong in your terminal
            messages.error(self.request, "There was an error connecting to Stripe.")
            return redirect("discover")


class SuccessView(generic.TemplateView):
    template_name = "success.html"


@csrf_exempt
def stripe_webhook(request, *args, **kwargs):
    payload = request.body
    sig_header = request.headers["stripe-signature"]

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )

    except ValueError:
        return HttpResponse(status=400)

    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        return event["data"]["object"]
    # listen for successful payments

    # who paid for what?

    # give access to the user for product they purchased

    return HttpResponse()
