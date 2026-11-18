from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from rest_framework.test import APIClient
from krishi_core.models import User, PasswordResetOTP, AuthOTP


class PasswordResetOTPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="farmer_test",
            email="farmer.test@example.com",
            phone="9876543210",
            password="OriginalPassword123!"
        )
        self.user.isVerified = True
        self.user.save()

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_forgot_password_generic_response_for_nonexistent_email(self, mock_send_email):
        """Generic 200 response is returned for non-existent email to prevent account enumeration."""
        res = self.client.post("/api/auth/forgot-password", {"email": "nobody@example.com"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("If an account exists", res.data.get("message", ""))
        self.assertEqual(PasswordResetOTP.objects.count(), 0)
        mock_send_email.assert_not_called()

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_forgot_password_creates_otp_and_enforces_cooldown(self, mock_send_email):
        """Requesting OTP creates a record; subsequent request within 60s triggers HTTP 429 cooldown."""
        res1 = self.client.post("/api/auth/forgot-password", {"email": "farmer.test@example.com"}, format="json")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 1)
        mock_send_email.assert_called_once()

        # Immediate second request should be throttled
        res2 = self.client.post("/api/auth/forgot-password", {"email": "farmer.test@example.com"}, format="json")
        self.assertEqual(res2.status_code, 429)
        self.assertIn("retryAfter", res2.data)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 1)

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_replacement_otp_invalidates_previous_otp(self, mock_send_email):
        """When a new OTP is issued, any previously issued OTP is invalidated and superseded."""
        # Issue first OTP
        res1 = self.client.post("/api/auth/forgot-password", {"email": "farmer.test@example.com"}, format="json")
        self.assertEqual(res1.status_code, 200)
        otp1_record = PasswordResetOTP.objects.get(user=self.user)
        otp1_code = otp1_record.otp

        # Manually age the OTP to bypass the 60-second resend cooldown
        otp1_record.created_at = timezone.now() - timedelta(seconds=65)
        otp1_record.save(update_fields=["created_at"])

        # Request replacement OTP
        res2 = self.client.post("/api/auth/forgot-password", {"email": "farmer.test@example.com"}, format="json")
        self.assertEqual(res2.status_code, 200)

        # Verify old OTP is superseded: only 1 OTP exists in database and its code matches the new one
        all_otps = list(PasswordResetOTP.objects.filter(user=self.user))
        self.assertEqual(len(all_otps), 1)
        otp2_code = all_otps[0].otp

        # Attempting to reset using superseded OTP1 must be rejected
        res_old = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": otp1_code,
            "newPassword": "NewSecurePassword123!"
        }, format="json")
        # If otp1 happened to differ from otp2 (almost always), it's rejected
        if otp1_code != otp2_code:
            self.assertEqual(res_old.status_code, 400)

        # Resetting using latest OTP2 must succeed
        res_new = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": otp2_code,
            "newPassword": "NewSecurePassword123!"
        }, format="json")
        self.assertEqual(res_new.status_code, 200)

        # Verify password actually changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePassword123!"))

    def test_otp_single_use_prevents_replay(self):
        """An OTP can only be used once; after successful reset, replay attempts are rejected."""
        otp_record = PasswordResetOTP.objects.create(
            user=self.user,
            otp="654321",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        # First use: success
        res1 = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "654321",
            "newPassword": "FirstResetPassword123!"
        }, format="json")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 0)

        # Second use (replay attack): must fail
        res2 = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "654321",
            "newPassword": "SecondResetPassword123!"
        }, format="json")
        self.assertEqual(res2.status_code, 400)
        self.assertIn("expired or does not exist", res2.data.get("message", ""))

        # Verify second password was NOT set
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("FirstResetPassword123!"))
        self.assertFalse(self.user.check_password("SecondResetPassword123!"))

    def test_expired_otp_is_rejected_and_purged(self):
        """Expired OTP is rejected and purged from the database."""
        PasswordResetOTP.objects.create(
            user=self.user,
            otp="999888",
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        res = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "999888",
            "newPassword": "SomePassword123!"
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired or does not exist", res.data.get("message", ""))
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 0)

    def test_incorrect_otp_is_rejected(self):
        """Submitting an incorrect OTP code fails without deleting the valid record."""
        PasswordResetOTP.objects.create(
            user=self.user,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        res = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "000000",
            "newPassword": "SomePassword123!"
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid OTP", res.data.get("message"))
        self.assertIn("4 attempts remaining", res.data.get("message"))
        # Valid OTP record remains so legitimate user can re-try
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 1)

    def test_password_reset_otp_max_5_attempts_invalidates_code(self):
        """Entering 5 incorrect OTP attempts invalidates the reset code permanently."""
        from django.core.cache import cache
        cache.clear()

        otp_record = PasswordResetOTP.objects.create(
            user=self.user,
            otp="543210",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        for attempt in range(1, 5):
            res = self.client.post("/api/auth/reset-password", {
                "email": "farmer.test@example.com",
                "otp": f"99999{attempt}",
                "newPassword": "ValidStrongPassword123!"
            }, format="json")
            self.assertEqual(res.status_code, 400)
            self.assertIn(f"{5 - attempt} attempt", res.data.get("message"))
            # OTP record remains during attempts 1-4
            self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 1)

        # 5th incorrect attempt invalidates the OTP and deletes it from database
        res5 = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "000005",
            "newPassword": "ValidStrongPassword123!"
        }, format="json")
        self.assertEqual(res5.status_code, 400)
        self.assertIn("Maximum verification attempts exceeded", res5.data.get("message"))
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 0)

        # 6th attempt: OTP no longer exists
        res6 = self.client.post("/api/auth/reset-password", {
            "email": "farmer.test@example.com",
            "otp": "543210",
            "newPassword": "ValidStrongPassword123!"
        }, format="json")
        self.assertEqual(res6.status_code, 400)
        self.assertIn("expired or does not exist", res6.data.get("message"))

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_malformed_email_rejected_before_otp_generation(self, mock_send):
        """Malformed email addresses like bhavya@gmail must be rejected with 400 before OTP generation."""
        invalid_emails = [
            "bhavya@gmail",
            "bhavya@gmail.",
            "plainaddress",
            "@missingusername.com",
            "username@.com",
            "username@domain..com",
        ]
        for bad_email in invalid_emails:
            # 1. OTP Request endpoint
            res_req = self.client.post("/api/auth/otp/request", {"email": bad_email, "purpose": "register"}, format="json")
            self.assertEqual(res_req.status_code, 400)
            self.assertIn("valid email address", res_req.data.get("message", "").lower())

            # 2. Forgot Password endpoint
            res_forgot = self.client.post("/api/auth/forgot-password", {"email": bad_email}, format="json")
            self.assertEqual(res_forgot.status_code, 400)
            self.assertIn("valid email address", res_forgot.data.get("message", "").lower())

        # Email service must never be invoked for invalid addresses
        mock_send.assert_not_called()
        self.assertEqual(AuthOTP.objects.count(), 0)


class AuthenticationFlowsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="ramesh.patel@example.com",
            email="ramesh.patel@example.com",
            phone="9876543211",
            password="SecurePassword123!",
            first_name="Ramesh",
            last_name="Patel",
        )
        self.user.isVerified = True
        self.user.save()

    def test_login_success(self):
        """Valid credentials return 200, JWT tokens, and user profile."""
        res = self.client.post("/api/auth/login", {
            "email": "ramesh.patel@example.com",
            "password": "SecurePassword123!"
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("token", res.data)
        self.assertIn("user", res.data)
        self.assertEqual(res.data["user"]["email"], "ramesh.patel@example.com")

    def test_login_incorrect_password(self):
        """Incorrect password returns 401 with clear message."""
        res = self.client.post("/api/auth/login", {
            "email": "ramesh.patel@example.com",
            "password": "WrongPassword999!"
        }, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Incorrect password", res.data.get("message", ""))

    def test_login_unknown_email_guidance(self):
        """Unknown email returns 401 with accountNotFound flag for signup guidance."""
        res = self.client.post("/api/auth/login", {
            "email": "unknown.farmer@example.com",
            "password": "AnyPassword123!"
        }, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertTrue(res.data.get("accountNotFound"))
        self.assertIn("No account found", res.data.get("message", ""))

    def test_login_unverified_email_triggers_verification(self):
        """Unverified account login is blocked with 403 and requiresVerification flag."""
        unverified = User.objects.create_user(
            username="unverified@example.com",
            email="unverified@example.com",
            phone="9876543299",
            password="Password123!",
        )
        unverified.isVerified = False
        unverified.save()

        res = self.client.post("/api/auth/login", {
            "email": "unverified@example.com",
            "password": "Password123!"
        }, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.data.get("requiresVerification"))

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_signup_otp_request_and_cooldown(self, mock_send):
        """Requesting signup verification OTP creates an AuthOTP record; duplicate within 60s is throttled."""
        res1 = self.client.post("/api/auth/otp/request", {
            "email": "new.farmer@example.com",
            "purpose": "register"
        }, format="json")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(AuthOTP.objects.filter(email="new.farmer@example.com", purpose="register").count(), 1)
        mock_send.assert_called_once()

        # Cooldown throttles immediate subsequent request
        res2 = self.client.post("/api/auth/otp/request", {
            "email": "new.farmer@example.com",
            "purpose": "register"
        }, format="json")
        self.assertEqual(res2.status_code, 429)
        self.assertIn("retryAfter", res2.data)

    def test_signup_with_valid_otp_creates_user(self):
        """Submitting valid signup OTP registers new verified user and returns JWT."""
        AuthOTP.objects.create(
            email="suresh.k@example.com",
            purpose="register",
            otp="789012",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        res = self.client.post("/api/auth/register", {
            "email": "suresh.k@example.com",
            "password": "NewUserPassword123!",
            "firstName": "Suresh",
            "lastName": "Kumar",
            "otp": "789012",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertIn("token", res.data)
        new_user = User.objects.get(email="suresh.k@example.com")
        self.assertTrue(new_user.isVerified)
        self.assertTrue(new_user.check_password("NewUserPassword123!"))

    def test_signup_with_invalid_otp_fails(self):
        """Submitting invalid signup OTP returns 400 and does not create user."""
        AuthOTP.objects.create(
            email="rajesh.p@example.com",
            purpose="register",
            otp="112233",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        res = self.client.post("/api/auth/register", {
            "email": "rajesh.p@example.com",
            "password": "Password123!",
            "firstName": "Rajesh",
            "otp": "999999",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(email="rajesh.p@example.com").exists())

    def test_signup_otp_max_5_attempts_invalidates_code(self):
        """Entering 5 incorrect OTP attempts invalidates signup OTP."""
        from django.core.cache import cache
        cache.clear()

        AuthOTP.objects.create(
            email="attempt.limit@example.com",
            purpose="register",
            otp="654321",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        for attempt in range(1, 5):
            res = self.client.post("/api/auth/otp/verify", {
                "email": "attempt.limit@example.com",
                "otp": f"00000{attempt}",
                "purpose": "register"
            }, format="json")
            self.assertEqual(res.status_code, 400)
            self.assertIn(f"{5 - attempt} attempt", res.data.get("message"))
            self.assertEqual(AuthOTP.objects.filter(email="attempt.limit@example.com", purpose="register").count(), 1)

        # 5th attempt invalidates
        res5 = self.client.post("/api/auth/otp/verify", {
            "email": "attempt.limit@example.com",
            "otp": "000005",
            "purpose": "register"
        }, format="json")
        self.assertEqual(res5.status_code, 400)
        self.assertIn("Maximum verification attempts exceeded", res5.data.get("message"))
        self.assertEqual(AuthOTP.objects.filter(email="attempt.limit@example.com", purpose="register").count(), 0)

    def test_weak_passwords_rejected_by_policy(self):
        """Passwords failing length (8-128), uppercase, lowercase, digit, or special char are rejected."""
        AuthOTP.objects.create(
            email="policy.test@example.com",
            purpose="register",
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        weak_passwords = [
            ("short1!", "Password must be at least 8 characters long"),
            ("nouppercase123!", "uppercase letter"),
            ("NOLOWERCASE123!", "lowercase letter"),
            ("NoDigitsHere!!", "at least one digit"),
            ("NoSpecialChars123", "special character"),
            ("Password123!", "common"),  # CommonPasswordValidator
        ]

        for pwd, expected_err in weak_passwords:
            # We keep the OTP record active by not deleting in this loop
            AuthOTP.objects.filter(email="policy.test@example.com").delete()
            AuthOTP.objects.create(
                email="policy.test@example.com",
                purpose="register",
                otp="123456",
                expires_at=timezone.now() + timedelta(minutes=15)
            )

            res = self.client.post("/api/auth/register", {
                "email": "policy.test@example.com",
                "password": pwd,
                "firstName": "Test",
                "otp": "123456"
            }, format="json")
            self.assertEqual(res.status_code, 400, f"Password '{pwd}' should be rejected but passed")
            self.assertIn("Password does not meet requirements", res.data.get("message", ""))

    def test_signup_duplicate_email_rejected(self):
        """Attempting to register existing email is rejected."""
        AuthOTP.objects.create(
            email="ramesh.patel@example.com",
            purpose="register",
            otp="555666",
            expires_at=timezone.now() + timedelta(minutes=15)
        )
        res = self.client.post("/api/auth/register", {
            "email": "ramesh.patel@example.com",
            "password": "StrongFarmer#2026",
            "firstName": "Duplicate",
            "otp": "555666",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.data.get("message", ""))

    def test_signup_otp_replay_prevented(self):
        """Once a signup OTP is verified, submitting the same code again is rejected (single-use)."""
        AuthOTP.objects.create(
            email="replay.test@example.com",
            purpose="register",
            otp="888999",
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        # First verification succeeds and consumes OTP
        res1 = self.client.post("/api/auth/otp/verify", {
            "email": "replay.test@example.com",
            "otp": "888999",
            "purpose": "register"
        }, format="json")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(AuthOTP.objects.filter(email="replay.test@example.com").count(), 0)

        # Replay attempt fails
        res2 = self.client.post("/api/auth/otp/verify", {
            "email": "replay.test@example.com",
            "otp": "888999",
            "purpose": "register"
        }, format="json")
        self.assertEqual(res2.status_code, 400)
        self.assertIn("expired or does not exist", res2.data.get("message", ""))

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_signup_otp_resend_invalidates_previous_otp(self, mock_send):
        """Requesting a new signup OTP invalidates any previously issued OTP for that email."""
        from django.core.cache import cache
        cache.clear()

        # 1. First OTP
        res1 = self.client.post("/api/auth/otp/request", {"email": "resend.test@example.com", "purpose": "register"}, format="json")
        self.assertEqual(res1.status_code, 200)
        first_otp = AuthOTP.objects.get(email="resend.test@example.com").otp

        # Manually age record past 60s cooldown
        old_record = AuthOTP.objects.get(email="resend.test@example.com")
        old_record.created_at = timezone.now() - timedelta(seconds=65)
        old_record.save(update_fields=["created_at"])

        # 2. Resend replacement OTP
        res2 = self.client.post("/api/auth/otp/request", {"email": "resend.test@example.com", "purpose": "register"}, format="json")
        self.assertEqual(res2.status_code, 200)
        new_otp = AuthOTP.objects.get(email="resend.test@example.com").otp

        # 3. Old OTP must fail
        if first_otp != new_otp:
            res_old = self.client.post("/api/auth/otp/verify", {
                "email": "resend.test@example.com",
                "otp": first_otp,
                "purpose": "register"
            }, format="json")
            self.assertEqual(res_old.status_code, 400)

        # 4. New OTP succeeds
        res_new = self.client.post("/api/auth/otp/verify", {
            "email": "resend.test@example.com",
            "otp": new_otp,
            "purpose": "register"
        }, format="json")
        self.assertEqual(res_new.status_code, 200)

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_valid_email_domains_accepted(self, mock_send):
        """Legitimate email domains (e.g. .com, .org, .co.in, subdomains) are accepted without false positives."""
        valid_emails = [
            "farmer.patel@gmail.com",
            "agri_tech@icar.org.in",
            "krishi.mitra@gov.in",
            "user.name+tag@subdomain.coop.farm",
        ]
        for ok_email in valid_emails:
            from django.core.cache import cache
            cache.clear()
            res = self.client.post("/api/auth/otp/request", {"email": ok_email, "purpose": "register"}, format="json")
            self.assertEqual(res.status_code, 200, f"Valid email '{ok_email}' was unexpectedly rejected.")

    @patch("krishi_core.services.email_service.email_service.send_email", return_value=(True, "OK"))
    def test_password_reset_full_lifecycle(self, mock_send):
        """Complete lifecycle: request OTP -> reset password -> old password fails -> new password succeeds."""
        # 1. Request OTP
        req_res = self.client.post("/api/auth/forgot-password", {
            "email": "ramesh.patel@example.com"
        }, format="json")
        self.assertEqual(req_res.status_code, 200)
        otp = PasswordResetOTP.objects.get(user=self.user).otp

        # 2. Reset Password
        reset_res = self.client.post("/api/auth/reset-password", {
            "email": "ramesh.patel@example.com",
            "otp": otp,
            "newPassword": "BrandNewPassword123!"
        }, format="json")
        self.assertEqual(reset_res.status_code, 200)

        # 3. Old password is now rejected
        old_login = self.client.post("/api/auth/login", {
            "email": "ramesh.patel@example.com",
            "password": "SecurePassword123!"
        }, format="json")
        self.assertEqual(old_login.status_code, 401)

        # 4. New password succeeds
        new_login = self.client.post("/api/auth/login", {
            "email": "ramesh.patel@example.com",
            "password": "BrandNewPassword123!"
        }, format="json")
        self.assertEqual(new_login.status_code, 200)
        self.assertIn("token", new_login.data)

    def test_protected_routes_authorization(self):
        """Unauthenticated requests to /api/auth/me return 401; authenticated requests return user data."""
        # Unauthenticated
        unauth_res = self.client.get("/api/auth/me")
        self.assertEqual(unauth_res.status_code, 401)

        # Authenticated
        login_res = self.client.post("/api/auth/login", {
            "email": "ramesh.patel@example.com",
            "password": "SecurePassword123!"
        }, format="json")
        token = login_res.data["token"]

        auth_res = self.client.get(
            "/api/auth/me",
            HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(auth_res.status_code, 200)
        self.assertEqual(auth_res.data["user"]["email"], "ramesh.patel@example.com")


class CitySearchAndGeocodeTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("requests.get")
    def test_partial_match_sura_returns_surat(self, mock_get):
        """Searching partial prefix 'sura' returns Surat with district and state."""
        mock_get.return_value.status_code = 404
        res = self.client.get("/api/geocode?q=sura&limit=5")
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", [])
        self.assertTrue(len(results) >= 1)
        first = results[0]
        self.assertEqual(first["city"], "Surat")
        self.assertEqual(first["state"], "Gujarat")
        self.assertIn("Surat", first["address"])

    def test_search_surat_is_deduplicated(self):
        """Typing 'surat' returns a deduplicated single Surat suggestion rather than duplicates."""
        res = self.client.get("/api/geocode?q=surat&limit=5")
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", [])
        surat_entries = [r for r in results if r["city"].lower() == "surat"]
        self.assertEqual(len(surat_entries), 1)

    def test_ranking_prefers_prefix_match(self):
        """Prefix matches rank higher than random substring matches."""
        res = self.client.get("/api/geocode?q=pun&limit=5")
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", [])
        self.assertTrue(len(results) >= 1)
        self.assertTrue(results[0]["city"].lower().startswith("pun"))


class ContextualAiAdvisoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="ai_tester",
            email="ai.tester@example.com",
            phone="9123456780",
            password="TestPassword123!"
        )
        self.client.force_authenticate(user=self.user)

    def test_weather_contextual_advisory_synthesis(self):
        """When weather prompt is passed, deterministic agronomic advisory is generated."""
        from krishi_core.views import synthesize_contextual_advisory
        prompt = (
            "Please analyze current weather conditions:\n"
            "Current Weather in Surat, Gujarat:\n"
            "Temperature: 34°C\n"
            "Condition: Clear Sky\n"
            "Rain Probability: 15%\n"
            "Wind Speed: 9.0 km/h\n"
            "Instructions:\n"
            "1. Provide practical recommendations for irrigation."
        )
        advisory = synthesize_contextual_advisory(prompt)
        self.assertIsNotNone(advisory)
        self.assertIn("Surat", advisory)
        self.assertIn("Irrigation Recommendation", advisory)
        self.assertIn("Spraying & Fertilizer Suitability", advisory)

    def test_market_contextual_advisory_synthesis(self):
        """When market prompt is passed, deterministic market analysis is generated."""
        from krishi_core.views import synthesize_contextual_advisory
        prompt = (
            "Please analyze the current market prices:\n"
            "Location: Gujarat\n"
            "Commodity Filter: Soybean\n"
            "Current Mandi Data (Agmarknet / Data.gov.in):\n"
            "- Soybean at Rajkot APMC: Modal Price ₹4,650 [Min: ₹4,500 - Max: ₹4,800]\n"
            "Instructions:\n"
            "1. Compare prices."
        )
        advisory = synthesize_contextual_advisory(prompt)
        self.assertIsNotNone(advisory)
        self.assertIn("Soybean", advisory)
        self.assertIn("Mandi Market Price Analysis", advisory)
        self.assertIn("Practical Selling Considerations", advisory)

    def test_chat_stream_handles_contextual_prompt_gracefully(self):
        """Streaming chat endpoint handles contextual weather handoff and streams advisory chunks."""
        prompt = (
            "Current Weather in Rajkot, Gujarat:\n"
            "Temperature: 30°C\n"
            "Condition: Rain Showers\n"
            "Rain Probability: 75%\n"
            "Wind Speed: 12 km/h"
        )
        res = self.client.post("/api/chat", {"message": prompt, "sessionId": "test-session"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "text/event-stream")
        content = b"".join(res.streaming_content).decode("utf-8")
        self.assertIn("data: ", content)
        self.assertIn("[DONE]", content)
        self.assertTrue("Irrigation" in content or "Halt" in content or "advisory" in content.lower())

    def test_chat_stream_normal_agricultural_question(self):
        """Streaming chat endpoint handles general agronomic questions, retrieves KB, and streams response."""
        res = self.client.post("/api/chat", {
            "message": "How can I improve soil fertility for wheat farming?",
            "sessionId": "test-wheat-session"
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "text/event-stream")
        content = b"".join(res.streaming_content).decode("utf-8")
        self.assertIn("data: ", content)
        self.assertIn("[DONE]", content)
        # Should not return unavailable error when KB chunks are retrieved with <= 1.05 distance
        self.assertNotIn("I do not have enough verified information", content)

    def test_wheat_irrigation_general_question_returns_stages(self):
        """General wheat irrigation query returns physiological growth stages and Crown Root Initiation."""
        res = self.client.post("/api/chat", {
            "message": "What is the best time to irrigate wheat?",
            "sessionId": "test-wheat-irrigation"
        }, format="json")
        self.assertEqual(res.status_code, 200)
        content = b"".join(res.streaming_content).decode("utf-8")
        self.assertIn("data: ", content)
        self.assertIn("[DONE]", content)
        # Must address critical stages such as Crown Root Initiation (CRI)
        self.assertTrue("Crown Root" in content or "CRI" in content or "Tillering" in content)

    def test_wheat_irrigation_harvest_question_returns_harvesting_stage(self):
        """Explicit harvesting stage question returns guidance to stop irrigation before harvest."""
        res = self.client.post("/api/chat", {
            "message": "When should I stop irrigation before wheat harvest?",
            "sessionId": "test-wheat-harvest"
        }, format="json")
        self.assertEqual(res.status_code, 200)
        content = b"".join(res.streaming_content).decode("utf-8")
        self.assertIn("data: ", content)
        self.assertIn("[DONE]", content)
        # Parse SSE stream into full text
        import json
        full_text = "".join(
            json.loads(line[6:])["chunk"]
            for line in content.splitlines()
            if line.startswith("data: ") and "[DONE]" not in line and "chunk" in line
        )
        self.assertTrue(
            "10 to 15 days" in full_text or "10–15 days" in full_text or "10-15 days" in full_text
        )


class AlertRestorationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="alert_tester",
            email="alert.tester@example.com",
            phone="9123456781",
            password="TestPassword123!"
        )
        self.client.force_authenticate(user=self.user)
        from krishi_core.models import Alert
        self.alert = Alert.objects.create(
            owner=self.user,
            title="Pest Risk Warning",
            category="crop_health",
            severity="warning",
            status="active"
        )

    def test_dismiss_and_restore_alert_lifecycle(self):
        """Alert can be dismissed via PATCH and subsequently restored to active."""
        # 1. Dismiss alert
        res_dismiss = self.client.patch(f"/api/alerts/{self.alert.id}", {"status": "dismissed"}, format="json")
        self.assertEqual(res_dismiss.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, "dismissed")

        # 2. Restore alert
        res_restore = self.client.patch(f"/api/alerts/{self.alert.id}", {"status": "active"}, format="json")
        self.assertEqual(res_restore.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, "active")


class SoilRecommendationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="soil_tester",
            email="soil.tester@example.com",
            phone="9123456782",
            password="TestPassword123!"
        )
        self.client.force_authenticate(user=self.user)

    def test_soil_recommend_returns_ranked_crops_and_summary(self):
        """POST /api/soil_recommend returns ranked crop list and agronomist summary."""
        payload = {
            "ph": 6.8,
            "nitrogen": 140,
            "phosphorus": 35,
            "potassium": 180,
            "organicCarbon": 0.6,
            "ec": 0.35,
            "season": "kharif",
            "areaAcres": 2.0,
            "waterAvailability": "medium",
            "state": "Gujarat"
        }
        res = self.client.post("/api/soil_recommend", payload, format="json")
        self.assertEqual(res.status_code, 200)
        recs = res.data.get("recommendations", [])
        self.assertTrue(len(recs) >= 1)
        self.assertIn("cropName", recs[0])
        self.assertIn("suitabilityScore", recs[0])
        self.assertTrue(bool(res.data.get("llm_summary")))


class ChatSessionAndHistoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(
            username="farmer_history_1",
            email="farmer1@example.com",
            phone="9123456788",
            password="TestPassword123!"
        )
        self.user2 = User.objects.create_user(
            username="farmer_history_2",
            email="farmer2@example.com",
            phone="9123456789",
            password="TestPassword123!"
        )
        from krishi_core.models import ChatMessage
        self.ChatMessage = ChatMessage

    def test_chat_sessions_returns_user_conversations_with_titles(self):
        """GET /api/chat/sessions returns sessions with first user query as title."""
        self.client.force_authenticate(user=self.user1)
        self.ChatMessage.objects.create(
            owner=self.user1,
            sessionId="session-wheat-irrigation",
            role="user",
            content="What is the best irrigation schedule for wheat?"
        )
        self.ChatMessage.objects.create(
            owner=self.user1,
            sessionId="session-wheat-irrigation",
            role="assistant",
            content="For wheat, the critical stage is Crown Root Initiation (CRI) at 20-25 days."
        )

        res = self.client.get("/api/chat/sessions")
        self.assertEqual(res.status_code, 200)
        sessions = res.data
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["sessionId"], "session-wheat-irrigation")
        self.assertEqual(sessions[0]["title"], "What is the best irrigation schedule for wheat?")
        self.assertEqual(sessions[0]["message_count"], 2)

    def test_chat_history_delete_deletes_specified_session_only(self):
        """DELETE /api/chat/<sid> deletes all messages in that session for the user."""
        self.client.force_authenticate(user=self.user1)
        self.ChatMessage.objects.create(
            owner=self.user1,
            sessionId="session-to-delete",
            role="user",
            content="Question in session to delete"
        )
        self.ChatMessage.objects.create(
            owner=self.user1,
            sessionId="session-to-keep",
            role="user",
            content="Question in session to keep"
        )

        res = self.client.delete("/api/chat/session-to-delete")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get("success"))

        remaining_sessions = [m.sessionId for m in self.ChatMessage.objects.filter(owner=self.user1)]
        self.assertNotIn("session-to-delete", remaining_sessions)
        self.assertIn("session-to-keep", remaining_sessions)

    def test_chat_history_prevents_cross_user_access(self):
        """A user cannot view or delete another user's conversation."""
        self.ChatMessage.objects.create(
            owner=self.user1,
            sessionId="private-session-user1",
            role="user",
            content="Secret farm data"
        )

        self.client.force_authenticate(user=self.user2)
        # Attempt to get user1's session
        res_get = self.client.get("/api/chat/private-session-user1")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(len(res_get.data), 0)

        # Attempt to delete user1's session
        res_del = self.client.delete("/api/chat/private-session-user1")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.data.get("deleted"), 0)

        # Confirm user1's data is still intact
        self.assertEqual(self.ChatMessage.objects.filter(owner=self.user1, sessionId="private-session-user1").count(), 1)


class PredictDiseaseTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="scanner_tester",
            email="scanner@example.com",
            phone="9123456790",
            password="TestPassword123!"
        )
        self.client.force_authenticate(user=self.user)

    def test_predict_disease_missing_image_returns_400(self):
        """POST /api/disease/predict without an image file returns HTTP 400."""
        res = self.client.post("/api/disease/predict", {}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.data)

    def test_predict_disease_invalid_file_type_returns_400(self):
        """POST /api/disease/predict with a non-image file returns HTTP 400."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_txt = SimpleUploadedFile("notes.txt", b"just text", content_type="text/plain")
        res = self.client.post("/api/disease/predict", {"image": fake_txt}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.data)


class GeocodingHierarchicalTests(TestCase):
    def setUp(self):
        from .views import _GEOCODE_CACHE
        _GEOCODE_CACHE.clear()
        self.client = APIClient()

    def test_exact_city_match(self):
        """Exact city match returns status 200 with is_approximate=False."""
        res = self.client.get("/api/geocode?q=Ahmedabad&limit=1")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data.get("is_approximate"))
        self.assertEqual(res.data.get("city"), "Ahmedabad")

    @patch("requests.get")
    def test_hierarchical_regional_match(self, mock_get):
        """Sub-district with known state resolves to regional hub with is_approximate=True."""
        mock_get.return_value.status_code = 404
        res = self.client.get("/api/geocode?q=Navrangpura,%20Gujarat&limit=1")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get("is_approximate"))
        self.assertEqual(res.data.get("state"), "Gujarat")
        self.assertEqual(res.data.get("original_query"), "Navrangpura, Gujarat")
        self.assertIn("Regional Center", res.data.get("display_name"))

    def test_genuinely_unresolved_location_returns_404(self):
        """Genuinely unknown query with no valid state or district returns HTTP 404."""
        res = self.client.get("/api/geocode?q=NonexistentCityZzZ123987&limit=1")
        self.assertEqual(res.status_code, 404)
        self.assertIn("error", res.data)


class PredictionsAndKbFallbackTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="ml_tester",
            email="ml_tester@example.com",
            phone="9123456791",
            password="TestPassword123!"
        )
        self.client.force_authenticate(user=self.user)

    def test_yield_prediction_uses_ml_model(self):
        """Yield prediction returns numeric output from verified model artifact."""
        payload = {
            "Crop": "Wheat",
            "Crop_Year": 2026,
            "Season": "Rabi",
            "State": "Gujarat",
            "Area": 2.0,
            "Annual_Rainfall": 600.0,
            "Fertilizer": 120.0,
            "Pesticide": 25.0
        }
        res = self.client.post("/api/predict_yield", payload, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("predicted_yield", res.data)
        self.assertTrue(isinstance(res.data["predicted_yield"], (int, float)))
        self.assertTrue(res.data.get("is_ml_prediction"))
        self.assertEqual(res.data.get("source"), "ml_model")

    def test_fertilizer_recommendation_uses_kb_fallback(self):
        """Fertilizer recommendation falls back to verified ICAR schedule when model binary is absent."""
        payload = {
            "Crop_Type": "Wheat",
            "Crop_Growth_Stage": "Top-dress 1",
            "Season": "Rabi",
            "Soil_Type": "Loam"
        }
        res = self.client.post("/api/recommend_fertilizer", payload, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("recommended_fertilizer", res.data)
        self.assertFalse(res.data.get("is_ml_prediction"))
        self.assertEqual(res.data.get("source"), "knowledge_base")
        self.assertIn("Urea", res.data["recommended_fertilizer"])

    def test_irrigation_prediction_uses_kb_fallback(self):
        """Irrigation recommendation uses agronomic moisture thresholds when model binary is absent."""
        payload = {
            "Crop_Type": "Wheat",
            "Crop_Growth_Stage": "Vegetative",
            "Soil_Moisture": 30.0,
            "Forecast_Rainfall_7Days_mm": 0.0
        }
        res = self.client.post("/api/predict_irrigation", payload, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("irrigation_need", res.data)
        self.assertFalse(res.data.get("is_ml_prediction"))
        self.assertEqual(res.data.get("source"), "knowledge_base")
        self.assertIn("Immediate", res.data["irrigation_need"])


class MarketSyncBulkUpsertTests(TestCase):
    """sync_daily_market_data upserts in bulk: no duplicates, re-runs update prices."""

    def _response(self, records):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"records": records}
        return resp

    def test_bulk_upsert_dedupes_and_updates(self):
        import os
        from unittest.mock import patch
        from krishi_core.models import MarketPrice
        from krishi_core.services.market_sync import sync_daily_market_data

        rec = {"state": "Punjab", "district": "Ludhiana", "market": "Khanna", "commodity": "Wheat",
               "variety": "Dara", "arrival_date": "18/11/2026", "min_price": "2300", "max_price": "2500",
               "modal_price": "2400"}
        other = dict(rec, commodity="Mustard", modal_price="5600")
        dup = dict(rec, modal_price="2450")   # same key as rec inside one batch

        with patch.dict(os.environ, {"DATAGOV_API_KEY": "test-key"}), \
             patch("krishi_core.services.market_sync.requests.get",
                   return_value=self._response([rec, other, dup])):
            self.assertEqual(sync_daily_market_data(), 3)
        self.assertEqual(MarketPrice.objects.count(), 2)
        self.assertEqual(MarketPrice.objects.get(commodity="Wheat").modal_price, 2450)

        updated = dict(rec, modal_price="2600")
        with patch.dict(os.environ, {"DATAGOV_API_KEY": "test-key"}), \
             patch("krishi_core.services.market_sync.requests.get",
                   return_value=self._response([updated])):
            sync_daily_market_data()
        self.assertEqual(MarketPrice.objects.count(), 2)
        self.assertEqual(MarketPrice.objects.get(commodity="Wheat").modal_price, 2600)
