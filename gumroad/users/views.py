import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, UpdateView, TemplateView
from django.views import generic
from django.shortcuts import redirect

stripe.api_key = settings.STRIPE_SECRET_KEY
User = get_user_model()


class UserProfileView(LoginRequiredMixin, TemplateView):
    template_name = "profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        details_submitted = False

        # 1. Check if the user even has a stripe ID
        if user.stripe_account_id:
            try:
                # 2. Retrieve account info from Stripe
                account = stripe.Account.retrieve(user.stripe_account_id)
                details_submitted = account.get("details_submitted", False)
            except stripe.error.StripeError as e:
                # Log the error but don't crash the page
                print(f"Stripe Error: {e}")
                details_submitted = False

        context.update({"details_submitted": details_submitted})
        return context


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.request.user.username})

    def get_object(self):
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self):
        return reverse("users:detail", kwargs={"username": self.request.user.username})


user_redirect_view = UserRedirectView.as_view()


class StripeAccountLinkView(LoginRequiredMixin, generic.View):
    def get(self, request, *args, **kwargs):
        domain = "http://127.0.0.1:8000" if settings.DEBUG else "https://yourdomain.com"
        user = request.user

        # 1. CREATE ACCOUNT IF MISSING
        if not user.stripe_account_id:
            try:
                account = stripe.Account.create(
                    type="express",
                    email=user.email,
                    country="US",
                    capabilities={
                        "card_payments": {"requested": True},
                        "transfers": {"requested": True},
                    },
                )
                user.stripe_account_id = account.id
                user.save()
            except Exception as e:
                print(f"❌ Stripe Account Creation Error: {e}")
                return redirect("profile")

        # 2. GENERATE ONBOARDING LINK
        try:
            # type='account_onboarding' works for both NEW and RESTRICTED accounts
            account_links = stripe.AccountLink.create(
                account=user.stripe_account_id,
                refresh_url=domain + reverse("stripe-account-link"),
                return_url=domain + reverse("profile"),
                type="account_onboarding",
            )
            return redirect(account_links["url"])

        except stripe.error.StripeError as e:
            print(f"❌ Stripe Link Error: {e}")
            return redirect("profile")
