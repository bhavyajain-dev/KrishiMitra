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
        # Deterministic: no live Gemini call (its wording varies run to run),
        # so the built-in agronomic advisory engine answers.
        with patch("krishi_core.views.gemini_generate", return_value=(None, None)):
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


class ImportMarketCsvTests(TestCase):
    """import_market_csv loads a data.gov.in CSV download (x0020 headers)."""

    def test_imports_datagov_csv(self):
        import os
        import tempfile
        from django.core.management import call_command
        from krishi_core.models import MarketPrice

        rows = (
            "State,District,Market,Commodity,Variety,Grade,Arrival_Date,"
            "Min_x0020_Price,Max_x0020_Price,Modal_x0020_Price\n"
            "Punjab,Ludhiana,Khanna,Wheat,Dara,FAQ,18/11/2026,2300,2500,2400\n"
            "Gujarat,Anand,Anand APMC,Cotton,Other,FAQ,18/11/2026,6800,7200,7000\n"
            "Punjab,Ludhiana,Khanna,Wheat,Dara,FAQ,18/11/2026,2300,2550,2450\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(rows)
            path = f.name
        try:
            call_command("import_market_csv", path)
        finally:
            os.unlink(path)
        self.assertEqual(MarketPrice.objects.count(), 2)
        self.assertEqual(MarketPrice.objects.get(commodity="Wheat").modal_price, 2450)
        self.assertEqual(MarketPrice.objects.get(commodity="Cotton").state, "Gujarat")


class DataOwnershipAndValidationTests(TestCase):
    """Users can only touch their own farms; bad input gets a clean 400."""

    def setUp(self):
        from rest_framework_simplejwt.tokens import AccessToken
        self.a = User.objects.create_user(username="a@example.test", email="a@example.test", phone="9000000001", password="TestPass123!x")
        self.b = User.objects.create_user(username="b@example.test", email="b@example.test", phone="9000000002", password="TestPass123!x")
        self.A, self.B = APIClient(), APIClient()
        self.A.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.a)}")
        self.B.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.b)}")
        self.farm = self.A.post("/api/farms", {"name": "A farm", "areaAcres": 5}, format="json").data["id"]
        self.b_farm = self.B.post("/api/farms", {"name": "B farm", "areaAcres": 2}, format="json").data["id"]

    def test_cannot_attach_records_to_another_users_farm(self):
        cases = {
            "/api/expenses": {"label": "Seed", "category": "seeds", "amountRs": 100},
            "/api/crop-plans": {"cropName": "Wheat", "season": "rabi", "sowingDate": "2026-11-20", "expectedHarvestDate": "2027-03-20"},
            "/api/recommendations": {"season": "rabi", "cropOptions": []},
            "/api/alerts": {"category": "weather", "title": "Rain", "message": "Heavy rain"},
        }
        for path, payload in cases.items():
            self.assertEqual(self.B.post(path, {**payload, "farm": self.farm}, format="json").status_code, 400, path)
            self.assertEqual(self.A.post(path, {**payload, "farm": self.farm}, format="json").status_code, 201, path)

    def test_cannot_move_expense_to_another_users_farm(self):
        exp = self.B.post("/api/expenses", {"farm": self.b_farm, "label": "x", "category": "seeds", "amountRs": 1}, format="json").data["id"]
        self.assertEqual(self.B.patch(f"/api/expenses/{exp}", {"farm": self.farm}, format="json").status_code, 400)

    def test_expense_crop_plan_must_match_farm(self):
        plan = self.A.post("/api/crop-plans", {"farm": self.farm, "cropName": "Wheat", "season": "rabi",
                           "sowingDate": "2026-11-20", "expectedHarvestDate": "2027-03-20"}, format="json").data["id"]
        other = self.A.post("/api/farms", {"name": "A2", "areaAcres": 1}, format="json").data["id"]
        res = self.A.post("/api/expenses", {"farm": other, "cropPlan": plan, "label": "x", "category": "seeds", "amountRs": 1}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_farm_rejects_impossible_values(self):
        for bad in ({"areaAcres": -5}, {"areaAcres": 0}, {"areaAcres": "nan"}, {"ph": 25}, {"ph": 2},
                    {"nitrogen": -10}, {"phosphorus": 301}, {"name": "   "}, {"location": {"lat": 100, "lon": 1}}):
            res = self.A.post("/api/farms", {"name": "F", "areaAcres": 5, **bad}, format="json")
            self.assertEqual(res.status_code, 400, bad)
        ok = self.A.post("/api/farms", {"name": "F", "areaAcres": 5, "ph": 6.5, "nitrogen": 0, "waterResources": "Canal"}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.data["waterResources"], ["Canal"])

    def test_crop_plan_harvest_must_follow_sowing(self):
        res = self.A.post("/api/crop-plans", {"farm": self.farm, "cropName": "Wheat", "season": "rabi",
                          "sowingDate": "2026-11-20", "expectedHarvestDate": "2026-10-01"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_users_endpoint_is_read_only(self):
        self.assertEqual(self.A.patch(f"/api/users/{self.a.id}", {"isVerified": True}, format="json").status_code, 405)
        self.assertEqual(self.A.post("/api/users", {"username": "x"}, format="json").status_code, 405)

    def test_chat_plan_mode_ignores_other_users_farm(self):
        with patch("krishi_core.views.Farm.objects.filter", wraps=__import__("krishi_core").models.Farm.objects.filter) as spy:
            self.B.post("/api/chat", {"message": "Crop: Wheat, Season: Rabi", "forceJson": True,
                                      "farmId": self.farm, "sessionId": "x"}, format="json")
        for call in spy.call_args_list:
            if "id" in call.kwargs:
                self.assertEqual(call.kwargs.get("owner"), self.b)


class ProfileAndInputSafetyTests(TestCase):
    def setUp(self):
        from rest_framework_simplejwt.tokens import AccessToken
        self.a = User.objects.create_user(username="a@example.test", email="a@example.test", phone="9000000001", password="TestPass123!x", first_name="A")
        User.objects.create_user(username="b@example.test", email="b@example.test", phone="9000000002", password="TestPass123!x")
        self.A = APIClient()
        self.A.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.a)}")

    def test_duplicate_phone_is_clean_400(self):
        res = self.A.patch("/api/auth/profile", {"phone": "9000000002"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already used", res.data["message"])

    def test_phone_is_normalised(self):
        self.assertEqual(self.A.patch("/api/auth/profile", {"phone": "+91 98765 43210"}, format="json").status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.phone, "9876543210")
        self.assertEqual(self.A.patch("/api/auth/profile", {"phone": "123"}, format="json").status_code, 400)

    def test_email_change_is_refused_clearly(self):
        res = self.A.patch("/api/auth/profile", {"email": "b@example.test"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.A.patch("/api/auth/profile", {"email": "a@example.test", "firstName": "Asha"}, format="json").status_code, 200)

    def test_profile_rejects_bad_choices_and_blank_name(self):
        for bad in ({"firstName": ""}, {"language": "xx"}, {"farmingMode": "chaos"}, {"firstName": "x" * 200}):
            self.assertEqual(self.A.patch("/api/auth/profile", bad, format="json").status_code, 400, bad)

    def test_change_password_uses_full_policy(self):
        weak = self.A.post("/api/auth/change-password", {"oldPassword": "TestPass123!x", "newPassword": "123456"}, format="json")
        self.assertEqual(weak.status_code, 400)
        ok = self.A.post("/api/auth/change-password", {"oldPassword": "TestPass123!x", "newPassword": "NewPass456!y"}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_market_limit_junk_does_not_crash(self):
        for q in ("abc", "-5", "0", "999999", ""):
            self.assertEqual(APIClient().get(f"/api/market/prices?limit={q}").status_code, 200, q)

    def test_bad_token_does_not_block_public_endpoints(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer null")
        self.assertEqual(c.get("/api/market/locations").status_code, 200)
        self.assertEqual(c.get("/api/health").status_code, 200)
        self.assertEqual(c.get("/api/farms").status_code, 401)

    def test_non_object_json_and_wrong_types_are_400(self):
        c = APIClient()
        self.assertEqual(c.post("/api/auth/login", [], format="json").status_code, 400)
        self.assertEqual(c.post("/api/auth/login", {"email": ["x"], "password": "y"}, format="json").status_code, 400)
        self.assertEqual(self.A.post("/api/chat", {"message": "a" * 8001}, format="json").status_code, 400)

    def test_weather_cache_write_needs_login_and_valid_data(self):
        self.assertEqual(APIClient().post("/api/weather/cache", {"locationKey": "pune", "data": {}}, format="json").status_code, 401)
        self.assertEqual(self.A.post("/api/weather/cache", {"locationKey": "pune", "lat": "abc", "data": {}}, format="json").status_code, 400)
        good = {"current": {"temp": 24}, "daily": [{"hi": 30, "lo": 18}], "hourly": []}
        self.assertEqual(self.A.post("/api/weather/cache", {"locationKey": "pune", "lat": 18.5, "lon": 73.8, "data": good}, format="json").status_code, 200)
        raw = {"current": {"temperature": 24}, "daily_forecast": [], "hourly_forecast": []}
        self.assertEqual(self.A.post("/api/weather/cache", {"locationKey": "pune", "data": raw}, format="json").status_code, 400)


class GoogleOnlyAccountLoginTests(TestCase):
    def test_password_login_on_google_account_explains_google(self):
        u = User.objects.create(username="g@example.test", email="g@example.test", phone="g_123", googleId="123", isVerified=True)
        u.set_unusable_password()
        u.save()
        res = APIClient().post("/api/auth/login", {"email": "g@example.test", "password": "Whatever123!"}, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertTrue(res.data.get("googleOnly"))
        self.assertIn("Google", res.data["message"])


class MarketStateNameTests(TestCase):
    def setUp(self):
        from krishi_core.models import MarketPrice
        for st, dist, mk in [("Keralam", "Ernakulam", "Aluva"), ("Punjab", "Ludhiana", "Khanna"), ("NCT of Delhi", "Delhi", "Azadpur")]:
            MarketPrice.objects.create(state=st, district=dist, market=mk, commodity="Banana", arrival_date="17/11/2026", modal_price=2000)

    def test_states_use_one_display_name(self):
        res = APIClient().get("/api/market/locations")
        self.assertEqual(res.data["states"], ["Delhi", "Kerala", "Punjab"])

    def test_filter_by_common_spelling_finds_data_spelling(self):
        res = APIClient().get("/api/market/prices?state=Kerala")
        self.assertEqual(len(res.data["records"]), 1)
        self.assertEqual(len(APIClient().get("/api/market/history?state=Delhi").data["records"]), 1)

    def test_market_yards_listed_for_district(self):
        res = APIClient().get("/api/market/locations?state=Kerala&district=Ernakulam")
        self.assertEqual(res.data["districts"], ["Ernakulam"])
        self.assertEqual(res.data["markets"], ["Aluva"])


class GoogleAccessTokenLoginTests(TestCase):
    """Site-styled Google button: popup access token verified with Google."""

    def _resp(self, status, data):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = status
        r.json.return_value = data
        return r

    def _post(self, tokeninfo, userinfo=None):
        from django.test import override_settings
        with override_settings(GOOGLE_CLIENT_ID="our-client.apps.googleusercontent.com"), \
             patch("krishi_core.views.requests.post", return_value=tokeninfo), \
             patch("krishi_core.views.requests.get", return_value=userinfo or self._resp(200, {})):
            return APIClient().post("/api/auth/google", {"accessToken": "ya29.test"}, format="json")

    def test_token_for_our_app_logs_in_and_creates_account(self):
        res = self._post(
            self._resp(200, {"aud": "our-client.apps.googleusercontent.com", "sub": "g-1",
                             "email": "farmer@example.test", "email_verified": "true"}),
            self._resp(200, {"sub": "g-1", "given_name": "Asha", "family_name": "Patil"}),
        )
        self.assertEqual(res.status_code, 201 if res.status_code == 201 else 200)
        self.assertIn("token", res.data)
        u = User.objects.get(email="farmer@example.test")
        self.assertEqual((u.googleId, u.first_name), ("g-1", "Asha"))
        self.assertFalse(u.has_usable_password())

    def test_token_issued_to_another_app_is_rejected(self):
        res = self._post(self._resp(200, {"aud": "someone-else", "azp": "someone-else", "sub": "g-1",
                                          "email": "farmer@example.test", "email_verified": "true"}))
        self.assertEqual(res.status_code, 401)
        self.assertFalse(User.objects.filter(email="farmer@example.test").exists())

    def test_expired_token_is_rejected(self):
        self.assertEqual(self._post(self._resp(400, {"error": "invalid_token"})).status_code, 401)

    def test_unverified_google_email_is_rejected(self):
        res = self._post(self._resp(200, {"aud": "our-client.apps.googleusercontent.com", "sub": "g-2",
                                          "email": "x@example.test", "email_verified": "false"}))
        self.assertEqual(res.status_code, 400)


class SyncPlanAreaAndReplaceTests(TestCase):
    def setUp(self):
        from rest_framework_simplejwt.tokens import AccessToken
        self.u = User.objects.create_user(username="p@example.test", email="p@example.test", phone="9000000031", password="TestPass123!x")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.u)}")
        self.farm = self.c.post("/api/farms", {"name": "F", "areaAcres": 3.5}, format="json").data["id"]
        self.plan = {"cropPlan": {"cropName": "Fennel", "season": "Rabi 2026–27", "sowingDate": "2026-11-18",
                                  "expectedHarvestDate": "2027-04-17", "milestones": [{"name": "Sow"}]}}

    def test_area_is_saved(self):
        from krishi_core.models import CropPlan
        res = self.c.post("/api/chat/sync-plan", {"farmId": self.farm, "syncData": self.plan, "areaAcres": 2.5}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(CropPlan.objects.get(farm_id=self.farm).areaAcres, 2.5)

    def test_replace_retires_old_plan_and_keep_does_not(self):
        from krishi_core.models import CropPlan
        self.c.post("/api/chat/sync-plan", {"farmId": self.farm, "syncData": self.plan, "areaAcres": 1}, format="json")
        self.c.post("/api/chat/sync-plan", {"farmId": self.farm, "syncData": self.plan, "areaAcres": 1, "replace": False}, format="json")
        self.assertEqual(CropPlan.objects.filter(farm_id=self.farm, status="active").count(), 2)
        self.c.post("/api/chat/sync-plan", {"farmId": self.farm, "syncData": self.plan, "areaAcres": 1, "replace": True}, format="json")
        self.assertEqual(CropPlan.objects.filter(farm_id=self.farm, status="active").count(), 1)


class FarmFilterTests(TestCase):
    def test_expenses_list_filters_by_farm(self):
        from rest_framework_simplejwt.tokens import AccessToken
        u = User.objects.create_user(username="f@example.test", email="f@example.test", phone="9000000041", password="TestPass123!x")
        c = APIClient(); c.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(u)}")
        f1 = c.post("/api/farms", {"name": "A", "areaAcres": 1}, format="json").data["id"]
        f2 = c.post("/api/farms", {"name": "B", "areaAcres": 1}, format="json").data["id"]
        for f in (f1, f2):
            c.post("/api/expenses", {"farm": f, "label": "x", "category": "seeds", "amountRs": 10}, format="json")
        self.assertEqual(len(c.get(f"/api/expenses?farm={f1}").data), 1)
        self.assertEqual(len(c.get("/api/expenses").data), 2)
        self.assertEqual(len(c.get("/api/expenses?farm=abc").data), 0)
        exp = c.get(f"/api/expenses?farm={f1}").data[0]["id"]
        self.assertEqual(c.delete(f"/api/expenses/{exp}").status_code, 204)


class ChatContextTests(TestCase):
    """AI Mitra gets the farmer's own data, the conversation and any photo."""

    def setUp(self):
        from rest_framework_simplejwt.tokens import AccessToken
        self.u = User.objects.create_user(username="c@example.test", email="c@example.test", phone="9000000051", password="TestPass123!x")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.u)}")
        self.farm = self.c.post("/api/farms", {"name": "Nashik Plot", "areaAcres": 3.5, "soilType": "black", "ph": 7.8,
                                               "location": {"address": "Nashik", "city": "Nashik", "state": "Maharashtra",
                                                            "lat": 20.0, "lon": 73.8}}, format="json").data["id"]
        self.c.post("/api/chat/sync-plan", {"farmId": self.farm, "areaAcres": 2.5, "syncData": {"cropPlan": {
            "cropName": "Fennel", "season": "Rabi 2026–27", "sowingDate": "2026-11-18",
            "expectedHarvestDate": "2027-04-17", "milestones": []}}}, format="json")

    def _chat(self, payload):
        captured = {}

        def fake_generate(prompt, **kw):
            captured["prompt"], captured["image"] = prompt, kw.get("image")
            return "Advice.", "test-model"

        with patch("krishi_core.views.gemini_generate", side_effect=fake_generate):
            res = self.c.post("/api/chat", payload, format="json")
            body = b"".join(res.streaming_content).decode() if hasattr(res, "streaming_content") else ""
        return res, body, captured

    def test_prompt_includes_farm_plan_and_history(self):
        self._chat({"message": "What should I do this week?", "sessionId": "s1", "farmId": self.farm})
        res, body, cap = self._chat({"message": "And next week?", "sessionId": "s1", "farmId": self.farm,
                                     "weatherSnapshot": {"temp": 24, "rainChance": 10}})
        self.assertEqual(res.status_code, 200)
        p = cap["prompt"]
        for expected in ("Nashik Plot", "Fennel", "18 Nov 2026", "pH 7.8", "What should I do this week?", "temperature 24°C"):
            self.assertIn(expected, p)

    def test_photo_only_message_is_sent_to_gemini(self):
        res, body, cap = self._chat({"message": "", "sessionId": "s2", "imageBase64": "data:image/jpeg;base64,/9j/AAAA"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(cap["image"], ("image/jpeg", "/9j/AAAA"))
        self.assertIn("Advice.", body)

    def test_bad_photo_is_rejected(self):
        res, _, _ = self._chat({"message": "hi", "imageBase64": "data:text/html;base64,PHNjcmlwdD4="})
        self.assertEqual(res.status_code, 400)

    def test_other_users_farm_is_not_used(self):
        from rest_framework_simplejwt.tokens import AccessToken
        other = User.objects.create_user(username="o@example.test", email="o@example.test", phone="9000000052", password="TestPass123!x")
        c2 = APIClient(); c2.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(other)}")
        captured = {}
        with patch("krishi_core.views.gemini_generate", side_effect=lambda p, **k: (captured.setdefault("p", p), "ok")[1:] and ("ok", "m")):
            res = c2.post("/api/chat", {"message": "hi", "farmId": self.farm}, format="json")
            b"".join(res.streaming_content)
        self.assertNotIn("Nashik Plot", captured["p"])
        self.assertIn("has not added a farm", captured["p"])


class QuietConsoleResponsesTests(TestCase):
    """Expected situations answer 200 so browsers don't log red errors."""

    def test_weather_handoff_is_200_with_fallback_url(self):
        with patch("krishi_core.services.openmeteo_service.OpenMeteoService.get_forecast", return_value=None):
            res = APIClient().get("/api/weather?latitude=20.0&longitude=73.8")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["needsBrowserFetch"])
        self.assertTrue(res.data["fallbackUrl"].startswith("https://api.open-meteo.com/"))

    def test_missing_weather_cache_is_200_empty(self):
        res = APIClient().get("/api/weather/cache/nowhere")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["data"])



class WeatherCacheFormatTests(TestCase):
    def test_wrong_format_entry_is_a_miss_not_a_crash(self):
        from krishi_core.models import WeatherCache
        WeatherCache.objects.create(locationKey="surat-gujarat", cityName="Surat",
                                    data={"current": {"temperature": 24}, "daily_forecast": [], "hourly_forecast": []})
        res = APIClient().get("/api/weather/cache/surat-gujarat")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["data"])


class CropPlanGeneratorTests(TestCase):
    """The Crop Plan page's "Generate Plan" uses /api/chat with forceJson and
    must get a JSON plan back (not the streamed chat reply)."""

    def test_force_json_returns_crop_plan(self):
        from rest_framework_simplejwt.tokens import AccessToken
        u = User.objects.create_user(username="g@example.test", email="g@example.test", phone="9000000061", password="TestPass123!x")
        c = APIClient(); c.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(u)}")
        farm = c.post("/api/farms", {"name": "F", "areaAcres": 2, "ph": 7, "nitrogen": 250}, format="json").data["id"]
        with patch("krishi_core.views.gemini_generate", return_value=(None, None)):
            res = c.post("/api/chat", {
                "message": "@cropPlan Generate a crop plan. Crop: Castor, Season: Rabi 2026–27, Area: 1 acres, Irrigation: Rainfed.",
                "sessionId": "s-plan", "farmId": farm, "forceJson": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/json")
        plan = res.data["result"]["cropPlan"]
        self.assertEqual(plan["cropName"], "Castor")
        self.assertTrue(plan["milestones"])
        self.assertTrue(res.data["result"]["tasks"])


class CropPlanSoilCorrectionDateTests(TestCase):
    def test_soil_correction_is_before_sowing(self):
        from rest_framework_simplejwt.tokens import AccessToken
        u = User.objects.create_user(username="h@example.test", email="h@example.test", phone="9000000071", password="TestPass123!x")
        c = APIClient(); c.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(u)}")
        farm = c.post("/api/farms", {"name": "F", "areaAcres": 1, "ph": 7, "nitrogen": 250}, format="json").data["id"]
        fake_ai = {"fixes": "Add P and K.", "fertilizer_recommendation": "SSP", "add_as_task": True,
                   "task_title": "Soil Correction", "task_description": "Apply SSP"}
        with patch("krishi_core.services.ai_engine.llm_service.llm_service.generate_response", return_value=fake_ai):
            res = c.post("/api/chat", {"message": "@cropPlan Generate a crop plan. Crop: Banana, Season: Rabi, Area: 1 acres.",
                                       "farmId": farm, "forceJson": True}, format="json")
        plan = res.data["result"]["cropPlan"]
        corr = next(m for m in plan["milestones"] if m["stage"] == "Pre-sowing Soil Correction")
        self.assertLess(corr["plannedDate"], plan["sowingDate"])


class NoEmbeddingModelInRequestsTests(TestCase):
    """Requests must not depend on the neural embedding model (it can take
    minutes to load on the free server and hung recommendations)."""

    def test_reason_for_bracketed_crop_names(self):
        from krishi_core.views_ml import SoilRecommendView
        r = SoilRecommendView._rag_reason(None, "Rice (Paddy)", 6.5)
        self.assertNotIn("suits your soil's pH", r)  # got the crop's own profile reason

    def test_unknown_location_recommendation_is_fast_and_never_embeds(self):
        import time
        with patch("chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2.__call__", side_effect=AssertionError("embedding used")):
            t = time.time()
            res = APIClient().post("/api/soil_recommend", {"ph": 6.5, "nitrogen": 300, "season": "rabi", "areaAcres": 2,
                                                         "latitude": None, "longitude": None, "state": None,
                                                         "address": "zzqx nowhere"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["recommendations"])
        self.assertLess(time.time() - t, 30)

    def test_kb_search_collection_filter_and_retrieve(self):
        from krishi_core.services.kb_search import search
        hits = search("potato late blight treatment", collections=("disease_treatments_kb",), limit=2, with_meta=True)
        self.assertTrue(all(col == "disease_treatments_kb" for _t, col, _m in hits))
        res = APIClient().post("/api/retrieve", {"query": "wheat irrigation", "n_results": 3}, format="json")
        self.assertEqual(res.status_code, 200)


class SeasonAndCropNameTests(TestCase):
    """Recommendations must only offer crops sown in the chosen season, with
    readable names and a fertilizer plan for bracketed names."""

    def _recommend(self, season):
        with patch("krishi_core.services.ai_engine.llm_service.llm_service.generate_response", return_value={"error": "offline in tests"}):
            return APIClient().post("/api/soil_recommend", {
                "ph": 6.5, "nitrogen": 300, "season": season, "areaAcres": 2,
                "latitude": None, "longitude": None, "state": None, "address": "zzqx nowhere",
            }, format="json")

    def test_rabi_offers_no_kharif_crops(self):
        from krishi_core.utils import CROPS
        kharif = {c["name"] for c in CROPS if c["season"] == "kharif"}
        res = self._recommend("rabi")
        self.assertEqual(res.status_code, 200)
        names = {r["cropName"] for r in res.data["recommendations"]}
        self.assertTrue(names)
        self.assertFalse(names & kharif, f"Kharif crops offered in Rabi: {names & kharif}")

    def test_season_with_no_listed_crops_still_answers(self):
        res = self._recommend("zaid")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["recommendations"])

    def test_bracketed_crop_gets_fertilizer_plan(self):
        res = self._recommend("rabi")
        chana = next(r for r in res.data["recommendations"] if r["cropName"].startswith("Chickpea"))
        fert = chana.get("suggestedFertilizer")
        self.assertFalse(isinstance(fert, str) and fert.startswith("N/A"), fert)

    def test_pretty_crop_names(self):
        from krishi_core.services.crop_profile import pretty_crop_name, crop_reason
        self.assertEqual(pretty_crop_name("ChickPea"), "Chickpea")
        self.assertEqual(pretty_crop_name("MungBean"), "Mung bean")
        self.assertEqual(pretty_crop_name("Rice (Paddy)"), "Rice (Paddy)")
        reason = crop_reason("chickpea", 6.5)
        if reason:
            self.assertNotIn("ChickPea", reason)
