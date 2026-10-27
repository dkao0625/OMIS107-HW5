import tempfile
import unittest
from pathlib import Path

from app import create_app


class CampusBitesTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": str(self.database_path),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_token(self):
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def register(self):
        response = self.client.get("/register")
        self.assertEqual(response.status_code, 200)
        return self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "display_name": "Casey Student",
                "username": "casey_1",
                "password": "safe-password-123",
            },
            follow_redirects=True,
        )

    def test_seeded_home_page_renders_search_and_ranked_places(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The Quad Cafe", response.data)
        self.assertIn(b"Brick Oven Pizza", response.data)
        self.assertIn(b"All cuisines", response.data)

        filtered = self.client.get("/?q=tacos&category=Mexican")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"Taco Garden", filtered.data)
        self.assertNotIn(b"The Quad Cafe", filtered.data)

    def test_register_login_and_edit_review(self):
        response = self.register()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Casey Student", response.data)

        place_response = self.client.post(
            "/places/quad-cafe",
            data={
                "csrf_token": self.csrf_token(),
                "rating": "5",
                "review": "The coffee is great and the patio is peaceful.",
            },
            follow_redirects=True,
        )
        self.assertEqual(place_response.status_code, 200)
        self.assertIn(b"Your review has been saved.", place_response.data)
        self.assertIn(b"The coffee is great and the patio is peaceful.", place_response.data)

        updated_response = self.client.post(
            "/places/quad-cafe",
            data={
                "csrf_token": self.csrf_token(),
                "rating": "3",
                "review": "Good coffee, but the line was a bit long.",
            },
            follow_redirects=True,
        )
        self.assertEqual(updated_response.status_code, 200)
        self.assertIn(b"Good coffee, but the line was a bit long.", updated_response.data)

        with self.app.app_context():
            from app import get_db

            reviews = get_db().execute(
                """
                SELECT rating, body FROM reviews
                JOIN users ON users.id = reviews.user_id
                WHERE users.username = 'casey_1'
                """
            ).fetchall()
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["rating"], 3)
        self.assertIn(b"Casey Student", self.client.get("/people/casey_1").data)

    def test_review_requires_login_and_invalid_input_is_rejected(self):
        self.client.get("/places/taco-garden")
        login_required = self.client.post(
            "/places/taco-garden",
            data={
                "csrf_token": self.csrf_token(),
                "rating": "4",
                "review": "A tasty meal.",
            },
        )
        self.assertEqual(login_required.status_code, 302)
        self.assertEqual(login_required.headers["Location"], "/login")

        self.register()
        invalid = self.client.post(
            "/places/taco-garden",
            data={
                "csrf_token": self.csrf_token(),
                "rating": "8",
                "review": "Tiny",
            },
            follow_redirects=True,
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"Choose a rating from 1 to 5 stars.", invalid.data)

        with self.app.app_context():
            from app import get_db

            review = get_db().execute(
                """
                SELECT r.id FROM reviews r
                JOIN users u ON u.id = r.user_id
                JOIN places p ON p.id = r.place_id
                WHERE u.username = 'casey_1' AND p.slug = 'taco-garden'
                """
            ).fetchone()
        self.assertIsNone(review)

    def test_bad_credentials_missing_place_and_csrf_errors_are_clear(self):
        self.client.get("/login")
        bad_login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(),
                "username": "unknown",
                "password": "not-the-password",
            },
        )
        self.assertIn(b"Username or password is incorrect.", bad_login.data)
        self.assertEqual(self.client.get("/places/not-a-place").status_code, 404)

        invalid_post = self.client.post("/login", data={"username": "unknown"})
        self.assertEqual(invalid_post.status_code, 400)
        self.assertIn(b"Your form expired. Please try again.", invalid_post.data)

    def test_accounts_and_reviews_survive_app_restart(self):
        self.register()
        self.client.post(
            "/places/green-bowl",
            data={
                "csrf_token": self.csrf_token(),
                "rating": "5",
                "review": "Fresh food and a generous portion.",
            },
        )

        restarted_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": str(self.database_path),
            }
        )
        restarted_client = restarted_app.test_client()
        with restarted_app.app_context():
            from app import get_db

            review = get_db().execute(
                """
                SELECT r.rating, r.body FROM reviews r
                JOIN users u ON u.id = r.user_id
                WHERE u.username = 'casey_1'
                """
            ).fetchone()
        self.assertEqual(review["rating"], 5)
        self.assertEqual(review["body"], "Fresh food and a generous portion.")
        login_page = restarted_client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        login_response = restarted_client.post(
            "/login",
            data={
                "csrf_token": self._token_from(restarted_client),
                "username": "casey_1",
                "password": "safe-password-123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Casey Student", login_response.data)

    @staticmethod
    def _token_from(client):
        with client.session_transaction() as session:
            return session["_csrf_token"]


if __name__ == "__main__":
    unittest.main()
