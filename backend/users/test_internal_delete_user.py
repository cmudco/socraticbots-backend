from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()

URL = '/api/users/internal/delete-user/'


@override_settings(DARE_INTERNAL_KEY='shared-secret')
class InternalDeleteUserTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='expunge@example.com', name='Expunge', password='x', external_user_id=42
        )

    def test_deletes_the_account_linked_to_the_dare_user(self):
        response = self.client.post(
            URL, {'dare_user_id': 42}, format='json', HTTP_X_INTERNAL_KEY='shared-secret'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_requires_the_internal_key(self):
        missing = self.client.post(URL, {'dare_user_id': 42}, format='json')
        wrong = self.client.post(
            URL, {'dare_user_id': 42}, format='json', HTTP_X_INTERNAL_KEY='nope'
        )

        self.assertEqual(missing.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(wrong.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_unknown_dare_user_is_a_404_and_blank_id_is_a_400(self):
        unknown = self.client.post(
            URL, {'dare_user_id': 999}, format='json', HTTP_X_INTERNAL_KEY='shared-secret'
        )
        blank = self.client.post(URL, {}, format='json', HTTP_X_INTERNAL_KEY='shared-secret')

        self.assertEqual(unknown.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(blank.status_code, status.HTTP_400_BAD_REQUEST)
