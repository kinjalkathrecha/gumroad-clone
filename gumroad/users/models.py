from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import CharField
from django.db.models.signals import post_save
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from gumroad.products.models import Product


class User(AbstractUser):
    """
    Default custom user model for gumroad.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})


class UserLibrary(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    products = models.ManyToManyField(Product, blank=True)

    class Meta:
        verbose_name_plural = "UserLibraries"

    def __str__(self):
        return self.user.email


def post_save_user_receiver(sender, instance, created, **kwargs):
    # This line ensures 'library' exists whether it's a NEW user or an UPDATE
    library, _ = UserLibrary.objects.get_or_create(user=instance)

    # Only run the fulfillment logic for brand-new accounts
    if created:
        from gumroad.products.models import (
            PurchasedProduct,
        )  # Local import to avoid circularity

        # Find any products bought as a guest with this email
        purchases = PurchasedProduct.objects.filter(email__iexact=instance.email)

        for purchase in purchases:
            library.products.add(purchase.product)
            print(
                f"Linked legacy purchase {purchase.product.name} to new user {instance.email}"
            )


post_save.connect(post_save_user_receiver, sender=User)
