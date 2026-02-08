from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from gumroad.products.models import Product
from unittest.mock import patch
import json

User = get_user_model()


class WebhookTest(TestCase):
    @patch("gumroad.users.models.stripe.Account.create")
    def setUp(self, mock_account_create):
        mock_account_create.return_value = {"id": "acct_test123"}
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password"
        )
        self.product = Product.objects.create(
            user=self.user, name="Test Product", price=1000, slug="test-product"
        )
        self.client = Client()
        self.webhook_url = "/webhooks/stripe/"

    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_client_reference_id(self, mock_construct_event):
        # Mock the Stripe event
        mock_event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"product_id": self.product.id},
                    "customer": "cus_test123",
                    "client_reference_id": str(self.user.id),
                    "customer_details": {
                        "email": "different@example.com"  # Different email to ensure ID lookup takes precedence
                    },
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Define payload and headers
        payload = json.dumps(mock_event)
        # HTTP_STRIPE_SIGNATURE must be in META, so passing it as keyword arg or in **extra works if capitalized
        extra = {
            "HTTP_STRIPE_SIGNATURE": "test_signature",
        }

        # Send POST request
        response = self.client.post(
            self.webhook_url, payload, content_type="application/json", **extra
        )

        # Check response
        self.assertEqual(response.status_code, 200)

        # Check if product was added to user library
        self.user.refresh_from_db()
        self.assertTrue(
            self.user.userlibrary.products.filter(id=self.product.id).exists()
        )
        self.assertEqual(self.user.stripe_customer_id, "cus_test123")
