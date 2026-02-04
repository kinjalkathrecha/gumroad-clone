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
from django.core.mail import send_mail
from .forms import ProductModelForm
from .models import Product, PurchasedProduct

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
        product = self.get_object()
        has_access = False
        if self.request.user.is_authenticated:
            if product in self.request.user.userlibrary.products.all():
                has_access = True
        context.update(
            {
                "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY,
                "has_access": has_access,
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
        product_img_urls = [
            "https://ded9.com/wp-content/uploads/2021/05/3654e7e5cd4023d6a65bb172fb178be0.jpg"
        ]
        if product.cover:
            product_img_urls.append(product.cover.url)
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
                                "images": product_img_urls,
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
        stripe_customer_details = session.get("customer_details", {})
        stripe_customer_email = stripe_customer_details.get("email")

        # 1. Fetch Product Safely
        product = Product.objects.filter(id=product_id).first()
        if not product:
            return HttpResponse(status=404)

        # 2. Find User
        from gumroad.users.models import User, UserLibrary

        user = User.objects.filter(stripe_customer_id=stripe_customer_id).first()
        if not user:
            user = User.objects.filter(email__iexact=stripe_customer_email).first()

        # 3. Handle PurchasedProduct (Always create this for record-keeping)
        # Using update_or_create prevents duplicate records on webhook retries
        PurchasedProduct.objects.get_or_create(
            email=stripe_customer_email, product=product
        )

        # 4. Fulfillment Logic
        if user:
            # Sync Stripe ID if missing
            if stripe_customer_id and user.stripe_customer_id != stripe_customer_id:
                user.stripe_customer_id = stripe_customer_id
                user.save(update_fields=["stripe_customer_id"])

            # Update User Library
            library, created = UserLibrary.objects.get_or_create(user=user)
            if product not in library.products.all():
                library.products.add(product)

        else:
            # GUEST FLOW: User doesn't exist yet
            # Send the email specifically telling them to use stripe_customer_email to sign up
            send_mail(
                subject="Create an account to access your content",
                message=f"Thank you for purchasing {product.name}! Please sign up at our site using this email ({stripe_customer_email}) to access your purchase.",
                from_email="noreply@yourdomain.com",
                recipient_list=[stripe_customer_email],
                fail_silently=False,
            )

    return HttpResponse(status=200)
