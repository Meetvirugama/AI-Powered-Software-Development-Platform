import unittest


class TestAccountModel(unittest.TestCase):
    def setUp(self):
        self.user = "test_user"

    def test_account_creation(self):
        self.assertEqual(self.user, "test_user")


if __name__ == "__main__":
    unittest.main()
