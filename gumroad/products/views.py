import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
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
User = get_user_model()


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


class SuccessView(generic.TemplateView):
    template_name = "success.html"


class CreateCheckoutSessionView(generic.View):
    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, slug=self.kwargs["slug"])

        success_url = request.build_absolute_uri("/success/")
        cancel_url = request.build_absolute_uri("/cancel/")

        # Determine if we use an existing ID or just the email
        customer_id = None
        customer_email = None

        if request.user.is_authenticated:
            if request.user.stripe_customer_id:
                customer_id = request.user.stripe_customer_id
            else:
                customer_email = request.user.email

        try:
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                customer_email=customer_email,
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
                metadata={
                    "product_id": product.id,
                },
            )
            return redirect(checkout_session.url, code=303)

        except stripe.error.StripeError as e:
            print(f"Stripe Error: {e}")
            return redirect("discover")


@csrf_exempt
def stripe_webhook(request, *args, **kwargs):
    payload = request.body
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        product_id = session["metadata"].get("product_id")
        stripe_customer_id = session.get("customer")
        stripe_customer_email = session["customer_details"]["email"]

        # 1. Fetch Product Safely
        product = Product.objects.filter(id=product_id).first()
        if not product:
            print(f"Product ID {product_id} not found.")
            return HttpResponse(status=404)

        # 2. Find User (Direct Import to avoid ImportError)
        # We import here to solve the circular dependency once and for all
        from gumroad.users.models import User
        from gumroad.users.models import UserLibrary

        # Lookup: Priority is Stripe ID, then Case-Insensitive Email
        user = User.objects.filter(stripe_customer_id=stripe_customer_id).first()
        if not user:
            user = User.objects.filter(email__iexact=stripe_customer_email).first()

        # 3. Fulfillment Logic
        if user:
            # Update the Stripe ID if it's missing (Crucial for your Admin check)
            if user.stripe_customer_id != stripe_customer_id:
                user.stripe_customer_id = stripe_customer_id
                user.save()

            # Update User Library
            library, created = UserLibrary.objects.get_or_create(user=user)

            # Check if product is already in library to prevent duplicates
            if product not in library.products.all():
                library.products.add(product)
                print(f"Product '{product.name}' added to {user.email}'s library.")
            else:
                print(f"User {user.email} already owns '{product.name}'.")
        else:
            print(f"Webhook error: No user found with email {stripe_customer_email}")

    return HttpResponse(status=200)
