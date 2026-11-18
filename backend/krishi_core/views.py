import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.db import transaction, IntegrityError
import requests
import pandas as pd
from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, action, throttle_classes
# pyrefly: ignore [missing-import]
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from .models import (
    User, Farm, CropPlan, MarketPrice, 
    Recommendation, Alert, Expense, Notification,
    WeatherCache, ChatMessage, PasswordResetOTP
)
from .serializers import (
    UserSerializer, FarmSerializer, CropPlanSerializer,
    MarketPriceSerializer, 
    RecommendationSerializer, AlertSerializer,
    ExpenseSerializer, NotificationSerializer,
    WeatherCacheSerializer, ChatMessageSerializer
)
from . import ml_loader
from .services.geocoding import _GEOCODE_CACHE, INDIAN_AGRI_CITIES, geocode_lookup  # noqa: F401
from .services.ai_engine.gemini_client import gemini_generate
from .services.market_sync import maybe_refresh_in_background
from .throttles import AIRateThrottle

logger = logging.getLogger(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────

def _text(value):
    """A request value as stripped text. Numbers become text; lists, objects
    and other non-text values become '' (so they fail validation cleanly
    instead of crashing with a 500)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ''



def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


class IsOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user


class OwnerViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

# ─── Auth Views ─────────────────────────────────────────────────────────


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_register(request):
    """Register a new user. Supports both passwordless (via verificationToken) and legacy (password + otp). Returns { token, user }."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
    from django.core.cache import cache
    from .models import AuthOTP
    from .validators import validate_email_syntax

    data = request.data
    raw_email = _text(data.get('email')).lower()
    phone = _text(data.get('phone'))
    password = data.get('password', '')
    first_name = _text(data.get('firstName'))
    last_name = _text(data.get('lastName'))
    name = _text(data.get('name'))
    if name and not first_name:
        parts = name.split(' ', 1)
        first_name = parts[0]
        if len(parts) > 1 and not last_name:
            last_name = parts[1]

    verification_token = data.get('verificationToken')
    otp_code = _text(data.get('otp'))

    if not raw_email:
        return Response({'message': 'Email is required.'}, status=400)

    try:
        email = validate_email_syntax(raw_email)
    except ValidationError as e:
        return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    # 1. Verification via signed token (OTP-first passwordless registration)
    if verification_token:
        signer = TimestampSigner()
        try:
            unsigned_email = signer.unsign(verification_token, max_age=900)
            if unsigned_email.lower() != email:
                return Response({'message': 'Verification token does not match email.'}, status=400)
        except SignatureExpired:
            return Response({'message': 'Verification token has expired. Please verify your email again.'}, status=400)
        except BadSignature:
            return Response({'message': 'Invalid verification token.'}, status=400)

    # 2. Legacy verification via OTP record in AuthOTP
    elif otp_code:
        otp_record = AuthOTP.objects.filter(email=email, purpose='register').last()
        if not otp_record or not otp_record.is_valid():
            return Response({'message': 'OTP has expired or does not exist.'}, status=400)

        attempt_cache_key = f"otp_attempts_auth_{otp_record.id}"
        attempts = cache.get(attempt_cache_key, 0)
        if attempts >= 5:
            otp_record.delete()
            cache.delete(attempt_cache_key)
            return Response({
                'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
            }, status=400)

        if otp_record.otp != otp_code:
            attempts += 1
            remaining = 5 - attempts
            if remaining <= 0:
                otp_record.delete()
                cache.delete(attempt_cache_key)
                return Response({
                    'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
                }, status=400)
            cache.set(attempt_cache_key, attempts, timeout=900)
            return Response({
                'message': f'Invalid OTP. You have {remaining} attempt{"s" if remaining > 1 else ""} remaining.'
            }, status=400)

        cache.delete(attempt_cache_key)
        otp_record.delete()
    else:
        return Response({'message': 'Verification token or OTP is required for registration.'}, status=400)

    # Check password only if password was provided or if legacy mode without token
    if password:
        try:
            validate_password(password)
        except ValidationError as e:
            return Response({'message': 'Password does not meet requirements: ' + '; '.join(e.messages), 'errors': list(e.messages)}, status=400)

    if User.objects.filter(email__iexact=email).exists():
        return Response({'message': 'An account with this email already exists.'}, status=400)

    if len(first_name) > 150 or len(last_name) > 150:
        return Response({'message': 'Name is too long (max 150 characters).'}, status=400)
    if phone:
        cleaned_phone = _clean_phone(phone)
        if not cleaned_phone:
            return Response({'message': 'Enter a valid 10-digit Indian mobile number.'}, status=400)
        phone = cleaned_phone
    if phone and User.objects.filter(phone=phone).exists():
        return Response({'message': 'Phone number already registered.'}, status=400)
    role = data.get('role') or 'farmer'
    if role not in ('farmer', 'advisor'):
        return Response({'message': 'Role must be farmer or advisor.'}, status=400)
    farming_mode = data.get('farmingMode') or 'moderate'
    if farming_mode not in _FARMING_MODES:
        return Response({'message': 'Farming mode must be organic, moderate or flexible.'}, status=400)

    if not phone:
        phone = f"u_{uuid.uuid4().hex[:16]}"

    raw_loc = data.get('location', {})
    loc_dict = raw_loc if isinstance(raw_loc, dict) else {'address': str(raw_loc)} if raw_loc else {}

    user = User.objects.create(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        role=role,
        location=loc_dict,
        farmingMode=farming_mode,
        isVerified=True,
    )

    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()

    token = get_tokens_for_user(user)
    serializer = UserSerializer(user)
    return Response({'token': token, 'user': serializer.data}, status=201)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_login(request):
    """Login with email or username + password. Returns { token, user }."""
    identifier = _text(request.data.get('email') or request.data.get('username')).lower()
    password = request.data.get('password', '')

    if not identifier or not password:
        return Response({'message': 'Email and password are required.'}, status=400)

    user_obj = User.objects.filter(email=identifier).first() or User.objects.filter(username=identifier).first()
    if not user_obj:
        return Response({
            'message': 'No account found with this email. Please sign up to create an account.',
            'accountNotFound': True
        }, status=401)

    user = authenticate(request, username=user_obj.username, password=password)
    if not user:
        return Response({'message': 'Incorrect password. Please try again or reset your password.'}, status=401)

    if not user.isVerified:
        return Response({
            'message': 'Your account email is not verified. Please verify your email before logging in.',
            'requiresVerification': True,
            'email': user.email
        }, status=403)

    token = get_tokens_for_user(user)
    serializer = UserSerializer(user)
    return Response({'token': token, 'user': serializer.data})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_google(request):
    """
    Authenticate, register, or reconcile a user via Google OAuth ID Token (Signed JWT Credential).
    Validates token cryptographically against Google's public certificates.
    Uses Google 'sub' as the permanent federated identity.
    Automatically links verified Google identity to existing user account with matching email.
    """
    credential = request.data.get('credential') or request.data.get('idToken') or request.data.get('token')

    if not credential:
        return Response({'message': 'Google credential is required.'}, status=400)

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or os.getenv('GOOGLE_CLIENT_ID', '')
    if not client_id:
        return Response({'message': 'Google authentication is not configured on the server.'}, status=500)

    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id
        )
    except ValueError as e:
        logger.error("Google ID token verification failed: %s", e)
        return Response({'message': 'Invalid or expired Google credential.'}, status=401)
    except Exception as e:
        logger.error("Google auth exception: %s", e, exc_info=True)
        return Response({'message': 'Google authentication service is temporarily unavailable. Please try again or sign in with your email and password.'}, status=500)

    # 1. Verify Issuer
    issuer = idinfo.get('iss')
    if issuer not in ['accounts.google.com', 'https://accounts.google.com']:
        return Response({'message': f'Invalid token issuer: {issuer}'}, status=401)

    # 2. Extract Google Claims
    google_id = idinfo.get('sub')
    email = (idinfo.get('email') or '').strip().lower()
    email_verified = idinfo.get('email_verified', False)
    first_name = idinfo.get('given_name') or (idinfo.get('name', '').split(' ')[0] if idinfo.get('name') else '')
    last_name = idinfo.get('family_name') or ''
    avatar_url = idinfo.get('picture') or ''

    if not google_id or not email:
        return Response({'message': 'Google identity or email missing from token.'}, status=400)

    if not email_verified:
        return Response({'message': 'Your Google account email is not verified by Google.'}, status=400)

    # 3. Check if user already exists with this Google sub identity
    user = User.objects.filter(googleId=google_id).first()

    if user:
        # Cross-account check: Does this Google identity match the verified email in the token?
        if user.email.lower() != email:
            logger.warning(
                "Google authentication rejected: token email does not match linked user %s.",
                user.id
            )
            return Response({
                'message': 'This Google account is already linked to a different KrishiMitra account.'
            }, status=409)

        if not user.isVerified:
            user.isVerified = True
            user.save(update_fields=['isVerified'])
        if avatar_url and not user.avatarUrl:
            user.avatarUrl = avatar_url
            user.save(update_fields=['avatarUrl'])
        token = get_tokens_for_user(user)
        serializer = UserSerializer(user)
        return Response({'token': token, 'user': serializer.data}, status=200)

    # 4. Check if an account already exists with this verified email, or provision new user
    # Wrapped in transaction.atomic() to ensure database integrity during concurrent writes
    try:
        with transaction.atomic():
            existing_user_by_email = User.objects.filter(email=email).first()

            if existing_user_by_email:
                # Security check: require existing local account to be verified
                if not existing_user_by_email.isVerified:
                    return Response({
                        'message': 'An unverified KrishiMitra account with this email already exists. Please sign in with your email and password to verify your account first.'
                    }, status=403)

                # Security check: account must not be linked to a different Google identity
                if existing_user_by_email.googleId and existing_user_by_email.googleId != google_id:
                    return Response({
                        'message': 'This KrishiMitra account is already linked to a different Google account.'
                    }, status=409)

                # Reconcile Google sub identity with existing verified account
                existing_user_by_email.googleId = google_id
                if not existing_user_by_email.first_name and first_name:
                    existing_user_by_email.first_name = first_name
                if not existing_user_by_email.last_name and last_name:
                    existing_user_by_email.last_name = last_name
                if avatar_url and not existing_user_by_email.avatarUrl:
                    existing_user_by_email.avatarUrl = avatar_url
                existing_user_by_email.save()

                token = get_tokens_for_user(existing_user_by_email)
                serializer = UserSerializer(existing_user_by_email)
                return Response({'token': token, 'user': serializer.data}, status=200)

            # 5. New Google User -> Provision account without password
            # Store explicit unassigned/federated placeholder conforming to max_length=20 and uniqueness
            placeholder_phone = f"g_{google_id[:16]}"
            while User.objects.filter(phone=placeholder_phone).exists():
                placeholder_phone = f"g_{uuid.uuid4().hex[:16]}"

            new_user = User.objects.create(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=placeholder_phone,
                googleId=google_id,
                avatarUrl=avatar_url,
                role='farmer',
                farmingMode='moderate',
                isVerified=True,
            )
            new_user.set_unusable_password()
            new_user.save()

            token = get_tokens_for_user(new_user)
            serializer = UserSerializer(new_user)
            return Response({'token': token, 'user': serializer.data}, status=200)

    except IntegrityError:
        logger.warning(
            "Database IntegrityError during Google sign-in; re-evaluating user records."
        )
        # Re-read relevant user records after atomic rollback
        user_by_google = User.objects.filter(googleId=google_id).first()
        user_by_email = User.objects.filter(email=email).first()

        # 1. The same Google identity is already linked to an account
        if user_by_google:
            # Linked to the same account: allow authentication only after confirming correct verified identity
            if user_by_google.email.lower() == email:
                if not user_by_google.isVerified:
                    return Response({
                        'message': 'An unverified KrishiMitra account with this email already exists. Please sign in with your email and password to verify your account first.'
                    }, status=403)
                token = get_tokens_for_user(user_by_google)
                serializer = UserSerializer(user_by_google)
                return Response({'token': token, 'user': serializer.data}, status=200)
            else:
                # The Google identity is linked to a different account: reject without modifying either account
                logger.warning(
                    "Google authentication conflict: identity is already linked to user %s; rejecting request.",
                    user_by_google.id
                )
                return Response({
                    'message': 'This Google account is already linked to a different KrishiMitra account.'
                }, status=409)

        # 2. Check if the local account with this email is already linked to a different Google identity
        if user_by_email and user_by_email.googleId and user_by_email.googleId != google_id:
            return Response({
                'message': 'This KrishiMitra account is already linked to a different Google account.'
            }, status=409)

        # 3. Ambiguous email / Google identity conflict remains
        logger.error(
            "Unresolvable database conflict during Google authentication."
        )
        return Response({
            'message': 'An account conflict was encountered during Google sign-in. Please try again.'
        }, status=409)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def auth_me(request):
    """Get logged-in user profile."""
    serializer = UserSerializer(request.user)
    # Frontend expects { user: {...} }
    return Response({'user': serializer.data})


_LANGUAGES = {code for code, _ in User._meta.get_field('language').choices}
_FARMING_MODES = {code for code, _ in User._meta.get_field('farmingMode').choices}


def _clean_phone(raw):
    """Indian mobile number as 10 digits, or None when invalid."""
    import re
    digits = re.sub(r'[\s\-()]', '', str(raw or ''))
    if digits.startswith('+91'):
        digits = digits[3:]
    elif digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    return digits if re.fullmatch(r'[6-9]\d{9}', digits) else None


@api_view(['PATCH', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def auth_update_profile(request):
    """Update the logged-in user's profile. Unknown values get a clear 400."""
    user = request.user
    data = request.data
    if not isinstance(data, dict):
        return Response({'message': 'Send the profile as a JSON object.'}, status=400)

    def bad(msg):
        return Response({'message': msg}, status=400)

    if 'email' in data and _text(data.get('email')).lower() != (user.email or '').lower():
        return bad('Email cannot be changed here. It is your login ID.')

    if 'firstName' in data:
        first = _text(data.get('firstName'))
        if not first:
            return bad('First name cannot be empty.')
        if len(first) > 150:
            return bad('First name is too long (max 150 characters).')
        user.first_name = first
    if 'lastName' in data:
        last = _text(data.get('lastName'))
        if len(last) > 150:
            return bad('Last name is too long (max 150 characters).')
        user.last_name = last
    if 'phone' in data:
        phone = _clean_phone(data.get('phone'))
        if not phone:
            return bad('Enter a valid 10-digit Indian mobile number.')
        if User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
            return bad('This phone number is already used by another account.')
        user.phone = phone
    if 'language' in data:
        if data['language'] not in _LANGUAGES:
            return bad('Unsupported language.')
        user.language = data['language']
    if 'farmingMode' in data:
        if data['farmingMode'] not in _FARMING_MODES:
            return bad('Farming mode must be organic, moderate or flexible.')
        user.farmingMode = data['farmingMode']
    if 'avatarUrl' in data:
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError as DjangoValidationError
        url = _text(data.get('avatarUrl'))
        if url:
            try:
                URLValidator(schemes=['https', 'http'])(url)
            except DjangoValidationError:
                return bad('Avatar must be a valid image URL.')
            if len(url) > 200:
                return bad('Avatar URL is too long.')
        user.avatarUrl = url
    if 'location' in data:
        loc = data['location']
        if isinstance(loc, dict):
            new_loc = loc
        elif isinstance(loc, str) and loc.strip():
            new_loc = {'address': loc.strip()}
        elif loc is None or loc == '':
            new_loc = {}
        else:
            return bad('Location must be an address or an object.')
        if len(json.dumps(new_loc, default=str)) > 5000:
            return bad('Location is too large.')
        user.location = new_loc
    if 'settings' in data:
        if not isinstance(data['settings'], dict) or len(json.dumps(data['settings'], default=str)) > 20000:
            return bad('Settings must be an object.')
        user.settings = data['settings']

    try:
        user.save()
    except IntegrityError:
        return bad('This phone number is already used by another account.')
    serializer = UserSerializer(user)
    return Response({'user': serializer.data})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def auth_change_password(request):
    """Change the logged-in user's password."""
    user = request.user
    old_password = request.data.get('oldPassword')
    new_password = request.data.get('newPassword')

    if not isinstance(old_password, str) or not user.check_password(old_password):
        return Response({'message': 'Incorrect current password.'}, status=400)

    if not isinstance(new_password, str) or not new_password:
        return Response({'message': 'New password is required.'}, status=400)
    if new_password == old_password:
        return Response({'message': 'New password must be different from the current one.'}, status=400)
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as e:
        return Response({'message': ' '.join(e.messages), 'errors': list(e.messages)}, status=400)

    user.set_password(new_password)
    user.save()
    
    # Optional: Keep user logged in after password change by re-issuing token, or let frontend handle it
    return Response({'message': 'Password changed successfully.'})


def get_client_ip(request):
    """Safely extract the client IP address from the request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_request_otp(request):
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta
    import random
    from django.core.cache import cache
    from django.core.exceptions import ValidationError
    from .models import AuthOTP
    from .validators import validate_email_syntax

    raw_email = _text(request.data.get('email')).lower()
    purpose = request.data.get('purpose') or 'login'
    if purpose not in ['login', 'register']:
        return Response({'message': 'A valid purpose (login or register) is required.'}, status=400)

    if not raw_email:
        return Response({'message': 'Email is required.'}, status=400)

    try:
        email = validate_email_syntax(raw_email)
    except ValidationError as e:
        return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    # Clean up any globally expired AuthOTPs
    AuthOTP.objects.filter(expires_at__lt=timezone.now()).delete()

    # Rate limiting: max 10 OTP requests per hour per IP/email
    client_ip = get_client_ip(request)
    req_rate_key = f"otp_req_rate_{client_ip}_{email}"
    req_count = cache.get(req_rate_key, 0)
    if req_count >= 10:
        return Response({
            'message': 'Too many OTP requests. Please wait before requesting another code.'
        }, status=429)

    # Cooldown check: 60 seconds
    existing_otp = AuthOTP.objects.filter(email=email, purpose=purpose).order_by('-created_at').first()
    if existing_otp:
        elapsed = (timezone.now() - existing_otp.created_at).total_seconds()
        if elapsed < 60:
            remaining = int(60 - elapsed)
            return Response({
                'message': f'Please wait {remaining} seconds before requesting a new OTP.',
                'retryAfter': remaining
            }, status=429)

    otp_code = str(random.randint(100000, 999999))
    
    AuthOTP.objects.filter(email=email, purpose=purpose).delete()
    AuthOTP.objects.create(
        email=email,
        purpose=purpose,
        otp=otp_code,
        expires_at=timezone.now() + timedelta(minutes=15)
    )
    cache.set(req_rate_key, req_count + 1, timeout=3600)
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
        <div style="background-color: #10b981; padding: 24px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 24px;">KrishiMitra</h1>
        </div>
        <div style="padding: 32px 24px; background-color: #ffffff;">
            <h2 style="color: #111827; font-size: 20px; margin-top: 0;">Verify your email address</h2>
            <p style="color: #4b5563; font-size: 16px; line-height: 1.5;">
                Hello, <br/><br/>
                Please use the following One-Time Password (OTP) to verify your email address and securely access your KrishiMitra account.
            </p>
            <div style="background-color: #f3f4f6; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
                <span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #111827;">{otp_code}</span>
            </div>
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 0;">
                This code will expire in 15 minutes. If you did not request this, please ignore this email.
            </p>
        </div>
        <div style="background-color: #f9fafb; padding: 16px 24px; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="color: #9ca3af; font-size: 12px; margin: 0;">
                &copy; {timezone.now().year} KrishiMitra. All rights reserved.<br/>
                Empowering farmers with AI-driven insights.
            </p>
        </div>
    </div>
    """
    
    from .services.email_service import email_service
    success, _ = email_service.send_email(
        to_email=email,
        subject='KrishiMitra - Your Verification Code',
        html_content=html_content,
        text_content=f'Your verification OTP is: {otp_code}. It will expire in 15 minutes.'
    )
    if not success:
        return Response({'message': 'Failed to send email. Check email service configuration.'}, status=500)
        
    return Response({'message': 'OTP sent successfully.'})

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_verify_otp(request):
    from django.core.signing import TimestampSigner
    from django.core.cache import cache
    from django.core.exceptions import ValidationError
    from .models import AuthOTP
    from .validators import validate_email_syntax
    
    raw_email = _text(request.data.get('email')).lower()
    otp_code = _text(request.data.get('otp'))
    purpose = request.data.get('purpose')
    if purpose and purpose not in ['login', 'register']:
        return Response({'message': 'A valid purpose (login or register) is required.'}, status=400)
    
    if not raw_email or not otp_code:
        return Response({'message': 'Email and OTP are required'}, status=400)

    try:
        email = validate_email_syntax(raw_email)
    except ValidationError as e:
        return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    # Rate limiting: max 30 verification calls per 5 minutes per IP
    client_ip = get_client_ip(request)
    verify_rate_key = f"otp_verify_rate_{client_ip}"
    verify_count = cache.get(verify_rate_key, 0)
    if verify_count >= 30:
        return Response({
            'message': 'Too many verification attempts. Please wait a few minutes before trying again.'
        }, status=429)
    cache.set(verify_rate_key, verify_count + 1, timeout=300)
        
    otp_query = {'email': email}
    if purpose:
        otp_query['purpose'] = purpose
    otp_record = AuthOTP.objects.filter(**otp_query).order_by('-created_at').first()
    
    if not otp_record or not otp_record.is_valid():
        return Response({'message': 'OTP has expired or does not exist.'}, status=400)

    attempt_cache_key = f"otp_attempts_auth_{otp_record.id}"
    attempts = cache.get(attempt_cache_key, 0)
    if attempts >= 5:
        otp_record.delete()
        cache.delete(attempt_cache_key)
        return Response({
            'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
        }, status=400)
        
    if otp_record.otp != otp_code:
        attempts += 1
        remaining = 5 - attempts
        if remaining <= 0:
            otp_record.delete()
            cache.delete(attempt_cache_key)
            return Response({
                'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
            }, status=400)
        cache.set(attempt_cache_key, attempts, timeout=900)
        return Response({
            'message': f'Invalid OTP. You have {remaining} attempt{"s" if remaining > 1 else ""} remaining.'
        }, status=400)
        
    cache.delete(attempt_cache_key)
    otp_record.delete()
    
    user = User.objects.filter(email=email).first()
    if not user:
        signer = TimestampSigner()
        verification_token = signer.sign(email)
        return Response({
            'verified': True,
            'email': email,
            'requiresRegistration': True,
            'verificationToken': verification_token,
            'message': 'Email verified. Please complete your registration.'
        })
        
    user.isVerified = True
    user.save()
    refresh = RefreshToken.for_user(user)
    return Response({
        'token': str(refresh.access_token),
        'user': UserSerializer(user).data,
        'isNewUser': False
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_check_exists(request):
    from django.core.exceptions import ValidationError
    from .validators import validate_email_syntax

    identifier = _text(request.data.get('email') or request.data.get('username')).lower()
    phone = _text(request.data.get('phone'))
    
    if not identifier and not phone:
        return Response({'message': 'Email, username, or phone is required.'}, status=400)

    if identifier and '@' in identifier:
        try:
            identifier = validate_email_syntax(identifier)
        except ValidationError as e:
            return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    user_by_identifier = (User.objects.filter(email=identifier).first() or User.objects.filter(username=identifier).first()) if identifier else None
    phone = _clean_phone(phone) or phone
    user_by_phone = User.objects.filter(phone=phone).first() if phone else None
    user = user_by_identifier or user_by_phone
    exists = bool(user)

    return Response({
        'exists': exists,
        'email': user.email if user else identifier,
        'hasPassword': bool(user and user.has_usable_password()) if exists else False,
        'isVerified': bool(user and user.isVerified) if exists else False,
        'message': 'Account exists' if exists else 'Available'
    }, status=200)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_forgot_password(request):
    from django.core.mail import send_mail
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta
    import random
    from django.db import transaction
    from django.core.cache import cache
    from django.core.exceptions import ValidationError
    from .validators import validate_email_syntax
    
    raw_email = _text(request.data.get('email')).lower()
    if not raw_email:
        return Response({'message': 'Email is required.'}, status=400)

    try:
        email = validate_email_syntax(raw_email)
    except ValidationError as e:
        return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    # Clean up globally expired PasswordResetOTPs
    PasswordResetOTP.objects.filter(expires_at__lt=timezone.now()).delete()

    # Rate limiting: max 10 requests per hour per IP/email
    client_ip = get_client_ip(request)
    req_rate_key = f"otp_reset_req_rate_{client_ip}_{email}"
    req_count = cache.get(req_rate_key, 0)
    if req_count >= 10:
        return Response({
            'message': 'Too many password reset requests. Please wait before requesting another code.'
        }, status=429)

    users = list(User.objects.filter(email__iexact=email).order_by('id'))
    
    if users:
        # Cooldown check: 60 seconds across all matching user accounts
        existing_otp = (
            PasswordResetOTP.objects.filter(user__in=users)
            .order_by('-created_at', '-id')
            .first()
        )
        if existing_otp:
            elapsed = (timezone.now() - existing_otp.created_at).total_seconds()
            if elapsed < 60:
                remaining = int(60 - elapsed)
                return Response({
                    'message': f'Please wait {remaining} seconds before requesting a new password reset code.',
                    'retryAfter': remaining
                }, status=429)

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        
        # Save OTP to DB in an atomic transaction:
        # Invalidate and delete ALL existing reset OTPs for this account to guarantee previous OTPs are superseded
        with transaction.atomic():
            PasswordResetOTP.objects.filter(user__in=users).delete()
            PasswordResetOTP.objects.create(
                user=users[0],
                otp=otp_code,
                expires_at=timezone.now() + timedelta(minutes=15)
            )
        cache.set(req_rate_key, req_count + 1, timeout=3600)
        
        # Send email
        html_content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
                <div style="background-color: #10b981; padding: 24px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">KrishiMitra</h1>
                </div>
                <div style="padding: 32px 24px; background-color: #ffffff;">
                    <h2 style="color: #111827; font-size: 20px; margin-top: 0;">Password Reset Request</h2>
                    <p style="color: #4b5563; font-size: 16px; line-height: 1.5;">
                        Hello, <br/><br/>
                        We received a request to reset your KrishiMitra password. Use the following One-Time Password (OTP) to proceed.
                    </p>
                    <div style="background-color: #f3f4f6; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
                        <span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #111827;">{otp_code}</span>
                    </div>
                    <p style="color: #6b7280; font-size: 14px; margin-bottom: 0;">
                        This code will expire in 15 minutes. If you did not request this, please safely ignore this email.
                    </p>
                </div>
            </div>
            """
            
        from .services.email_service import email_service
        success, _ = email_service.send_email(
            to_email=email,
            subject='KrishiMitra - Password Reset OTP',
            html_content=html_content,
            text_content=f'Your password reset OTP is: {otp_code}. It will expire in 15 minutes.'
        )
        if not success:
            return Response({'message': 'Failed to send email. Check email service configuration.'}, status=500)
            
    return Response({'message': 'If an account exists with this email, a password reset OTP has been sent.'})

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_reset_password(request):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.utils.crypto import constant_time_compare
    from django.db import transaction
    from django.core.cache import cache
    from .validators import validate_email_syntax

    raw_email = _text(request.data.get('email')).lower()
    otp_code = _text(request.data.get('otp'))
    new_password = request.data.get('newPassword', '')
    
    if not raw_email or not otp_code or not new_password:
        return Response({'message': 'Email, OTP, and new password are required.'}, status=400)

    try:
        email = validate_email_syntax(raw_email)
    except ValidationError as e:
        return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    # Rate limiting: max 30 verification calls per 5 minutes per IP
    client_ip = get_client_ip(request)
    verify_rate_key = f"otp_reset_verify_rate_{client_ip}"
    verify_count = cache.get(verify_rate_key, 0)
    if verify_count >= 30:
        return Response({
            'message': 'Too many verification attempts. Please wait a few minutes before trying again.'
        }, status=429)
    cache.set(verify_rate_key, verify_count + 1, timeout=300)

    users = list(User.objects.filter(email__iexact=email).order_by('id'))
    if not users:
        return Response({'message': 'Invalid request.'}, status=400)

    user = users[0]

    with transaction.atomic():
        # Retrieve the latest issued OTP for this user with row locking
        otp_record = (
            PasswordResetOTP.objects.select_for_update()
            .filter(user__in=users)
            .order_by('-created_at', '-id')
            .first()
        )
        
        if not otp_record or not otp_record.is_valid():
            # Invalidate any stale/expired OTPs immediately
            PasswordResetOTP.objects.filter(user__in=users).delete()
            return Response({'message': 'Verification code has expired or does not exist. Please request a new code.'}, status=400)

        attempt_cache_key = f"otp_attempts_reset_{otp_record.id}"
        attempts = cache.get(attempt_cache_key, 0)
        if attempts >= 5:
            PasswordResetOTP.objects.filter(user__in=users).delete()
            cache.delete(attempt_cache_key)
            return Response({
                'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
            }, status=400)

        if not constant_time_compare(otp_record.otp, otp_code):
            attempts += 1
            remaining = 5 - attempts
            if remaining <= 0:
                PasswordResetOTP.objects.filter(user__in=users).delete()
                cache.delete(attempt_cache_key)
                return Response({
                    'message': 'Maximum verification attempts exceeded. This OTP has been invalidated. Please request a new code.'
                }, status=400)
            cache.set(attempt_cache_key, attempts, timeout=900)
            return Response({
                'message': f'Invalid OTP. You have {remaining} attempt{"s" if remaining > 1 else ""} remaining.'
            }, status=400)

        cache.delete(attempt_cache_key)

        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            return Response({
                'message': 'Password does not meet requirements: ' + '; '.join(e.messages),
                'errors': list(e.messages)
            }, status=400)

        for u in users:
            u.set_password(new_password)
            u.save()
        
        # Atomic single-use: purge all password reset OTPs for this user immediately upon successful reset
        PasswordResetOTP.objects.filter(user__in=users).delete()
    
    return Response({'message': 'Password has been reset successfully. You can now login.'})

# ─── CRUD ViewSets ──────────────────────────────────────────────────────


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(id=self.request.user.id)


class FarmViewSet(OwnerViewSet):
    queryset = Farm.objects.all()
    serializer_class = FarmSerializer

    _GEO_FIELDS = ("city", "district", "state", "lat", "lon")

    def _resolved_location(self, serializer, previous=None):
        """Ensure a saved farm carries real coordinates + state.

        The crop-recommendation model, weather and climate lookups all need
        lat/lon. The frontend used to geocode in the browser after saving, so a
        failed lookup (or an edit that re-sent only the address) left farms
        without coordinates. Resolve them here instead. Never overwrites values
        the client sent; returns None when nothing needs changing.
        """
        if "location" not in serializer.validated_data:
            return None
        loc = dict(serializer.validated_data.get("location") or {})
        if loc.get("lat") is not None and loc.get("lon") is not None:
            return None
        address = (loc.get("address") or "").strip()
        if not address:
            return None

        prev = previous or {}
        if (prev.get("address") or "").strip().lower() == address.lower() \
                and prev.get("lat") is not None and prev.get("lon") is not None:
            # Address unchanged on edit: keep the coordinates we already had.
            for k in self._GEO_FIELDS:
                if not loc.get(k) and prev.get(k) not in (None, ""):
                    loc[k] = prev[k]
            return loc

        try:
            geo = geocode_lookup(address, limit=1)
        except Exception:
            logger.warning("Farm geocoding failed for %r", address, exc_info=True)
            geo = None
        if not geo:
            return None
        for k in self._GEO_FIELDS:
            if not loc.get(k) and geo.get(k) not in (None, ""):
                loc[k] = geo[k]
        return loc

    def perform_create(self, serializer):
        loc = self._resolved_location(serializer)
        extra = {"location": loc} if loc is not None else {}
        serializer.save(owner=self.request.user, **extra)

    def perform_update(self, serializer):
        loc = self._resolved_location(serializer, previous=serializer.instance.location)
        extra = {"location": loc} if loc is not None else {}
        serializer.save(**extra)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        # Frontend expects a plain array for /api/farms
        return Response(serializer.data)


class CropPlanViewSet(OwnerViewSet):
    queryset = CropPlan.objects.all()
    serializer_class = CropPlanSerializer

    def get_queryset(self):
        if not self.request.user or self.request.user.is_anonymous:
            qs = CropPlan.objects.none()
        else:
            qs = super().get_queryset()
        farm_id = self.request.query_params.get('farm')
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        return qs

    def perform_create(self, serializer):
        plan = serializer.save(owner=self.request.user)
        # Note: We now only generate crop plan timelines via /api/recommendations 
        # and do not pre-generate daily schedules automatically here.

    @action(detail=True, methods=['post'], url_path='start-daily-schedule')
    def start_daily_schedule(self, request, pk=None):
        plan = self.get_object()
        raw_percent = request.data.get('startPercent')
        if raw_percent is None:
            return Response({'message': 'startPercent is required.'}, status=400)
        try:
            start_percent = float(raw_percent)
        except (ValueError, TypeError):
            return Response({'message': 'startPercent must be a valid number between 0 and 100.'}, status=400)

        if start_percent < 0 or start_percent > 100:
            return Response({'message': 'startPercent must be between 0 and 100.'}, status=400)

        # Derive duration in days
        if plan.sowingDate and plan.expectedHarvestDate:
            duration_days = max(1, (plan.expectedHarvestDate.date() - plan.sowingDate.date()).days)
        else:
            duration_days = 100

        start_day = int(round((start_percent / 100.0) * duration_days))

        # Base date for calculating task calendar dates
        base_date = plan.sowingDate if plan.sowingDate else timezone.now()

        # Generate daily tasks from 02_crop_task_calendar.csv
        tasks_csv = os.path.join(settings.BASE_DIR, 'krishi_core', 'data', '02_crop_task_calendar.csv')
        generated_tasks = []
        try:
            df_tasks = pd.read_csv(tasks_csv)
            crop_name = (plan.cropName or '').strip().lower()
            crop_tasks = df_tasks[df_tasks['crop_name'].str.lower() == crop_name]
            if crop_tasks.empty and crop_name:
                crop_tasks = df_tasks[df_tasks['crop_name'].str.lower().str.contains(crop_name.split()[0])]
            
            if not crop_tasks.empty:
                eligible_tasks = crop_tasks if start_percent == 0 else crop_tasks[crop_tasks['day_from_sowing_start'] >= start_day]
                for _, row in eligible_tasks.iterrows():
                    d_start = int(row['day_from_sowing_start'])
                    task_date = (base_date + timedelta(days=d_start)).strftime("%Y-%m-%d")
                    generated_tasks.append({
                        "_id": f"t-{uuid.uuid4().hex[:8]}",
                        "title": str(row['task']),
                        "date": task_date,
                        "category": str(row['task_category']).lower().replace(' ', '_'),
                        "priority": str(row['priority']).lower(),
                        "description": str(row['description']),
                        "stage": str(row['stage']),
                        "status": "pending"
                    })
        except Exception as e:
            logger.error(f"Error loading tasks calendar: {e}")

        # Update plan's seasonProgressPct and persist generated tasks
        plan.seasonProgressPct = start_percent
        plan.tasks = generated_tasks
        plan.save()

        return Response({
            'startDay': start_day,
            'durationDays': duration_days,
            'tasksGenerated': len(generated_tasks)
        })

    @action(detail=True, methods=['post'], url_path='drop')
    def drop_plan(self, request, pk=None):
        plan = self.get_object()
        plan.delete()
        return Response({'message': 'Plan dropped', 'tasksRemoved': 0})



    @action(detail=False,
            methods=['get'],
            url_path='supported-crops',
            permission_classes=[permissions.AllowAny])
    def supported_crops(self, request):
        try:
            csv_path = os.path.join(
                os.path.dirname(__file__),
                'data',
                '01_crop_profile.csv')
            df = pd.read_csv(csv_path)
            crops = df['crop_name'].dropna().unique().tolist()
            return Response(sorted(crops))
        except Exception:
            # Fallback
            return Response(['Wheat', 'Cotton', 'Soybean',
                            'Groundnut', 'Onion', 'Tomato'])

    @action(detail=False,
            methods=['get'],
            url_path='companion-suggestions',
            permission_classes=[permissions.AllowAny])
    def companion_suggestions(self, request):
        crop = request.query_params.get('crop', '').strip().lower()
        
        # Intercropping Compatibility Matrix
        matrix = {
            'wheat': ['Mustard', 'Chickpea', 'Linseed'],
            'cotton': ['Pigeon Pea', 'Cowpea', 'Soybean'],
            'soybean': ['Maize', 'Pigeon Pea', 'Sorghum'],
            'groundnut': ['Sunflower', 'Pearl Millet'],
            'tomato': ['Marigold', 'Basil', 'Onion'],
            'onion': ['Tomato', 'Cabbage', 'Carrot'],
            'maize': ['Soybean', 'Cowpea', 'Pumpkin']
        }
        
        if crop in matrix:
            return Response(matrix[crop])
        
        # Fallback to generic beneficial cover crops for unmapped crops
        return Response(['Clover', 'Alfalfa', 'Cowpea'])

def _safe_limit(raw, default, maximum):
    """Parse a ?limit= value; junk falls back to the default instead of a 500."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, value))


class MarketPriceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MarketPrice.objects.all()
    serializer_class = MarketPriceSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = MarketPrice.objects.all()
        state = self.request.query_params.get('state')
        district = self.request.query_params.get('district')
        market_q = self.request.query_params.get('market')
        commodity = self.request.query_params.get('commodity')
        limit = _safe_limit(self.request.query_params.get('limit'), default=200, maximum=1000)
        if state:
            qs = qs.filter(state__iexact=state)
        if district:
            qs = qs.filter(district__iexact=district)
        if market_q:
            qs = qs.filter(market__iexact=market_q)
        if commodity:
            qs = qs.filter(commodity__icontains=commodity)
        return qs[:limit]

    def list(self, request, *args, **kwargs):
        refreshing = maybe_refresh_in_background()
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        last = MarketPrice.objects.order_by('-fetchedAt').first()
        return Response({
            'source': 'database',
            'records': serializer.data,
            'lastUpdated': last.fetchedAt if last else None,
            'needsRefresh': refreshing,
        })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def market_locations(request):
    """Return distinct states and commodities for dropdowns."""
    maybe_refresh_in_background()
    state_filter = request.query_params.get('state')
    qs = MarketPrice.objects.all()
    if state_filter:
        qs = qs.filter(state__iexact=state_filter)
    states = list(MarketPrice.objects.values_list(
        'state', flat=True).distinct().order_by('state'))
    commodities = list(
        qs.values_list(
            'commodity',
            flat=True).distinct().order_by('commodity'))
    districts = []
    if state_filter:
        districts = list(
            qs.values_list(
                'district',
                flat=True).distinct().order_by('district'))
    return Response({'states': states,
                     'commodities': commodities,
                     'districts': districts})


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def market_history(request):
    """Return historical market price records filtered by query params."""
    qs = MarketPrice.objects.all()
    commodity = request.query_params.get('commodity')
    state = request.query_params.get('state')
    district = request.query_params.get('district')
    market_q = request.query_params.get('market')

    if commodity:
        qs = qs.filter(commodity__icontains=commodity.strip())
    if state:
        qs = qs.filter(state__iexact=state.strip())
    if district:
        qs = qs.filter(district__iexact=district.strip())
    if market_q:
        qs = qs.filter(market__iexact=market_q.strip())

    qs = qs.order_by('parsedDate', 'arrival_date')

    # Bounded limit: default 200, max ceiling 500
    raw_limit = request.query_params.get('limit')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
            if limit <= 0:
                return Response({'error': 'limit parameter must be a positive integer greater than 0.'}, status=400)
            limit = min(limit, 500)
        except (ValueError, TypeError):
            limit = 200
    else:
        limit = 200

    qs = qs[:limit]
    serializer = MarketPriceSerializer(qs, many=True)
    return Response({'records': serializer.data})


class RecommendationViewSet(OwnerViewSet):
    queryset = Recommendation.objects.all()
    serializer_class = RecommendationSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        farm_id = self.request.query_params.get('farm')
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        return qs


class AlertViewSet(OwnerViewSet):
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer


class ExpenseViewSet(OwnerViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer


class NotificationViewSet(OwnerViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer


class ChatMessageViewSet(OwnerViewSet):
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        session_id = self.request.query_params.get('sessionId')
        if session_id:
            qs = qs.filter(sessionId=session_id)
        return qs.order_by('created_at')


def synthesize_contextual_advisory(user_msg):
    """
    Synthesizes expert agronomic advisory based on ICAR guidelines from provided
    real-time contextual prompts (weather forecast, mandi prices, or crop plans)
    when the external LLM provider (Gemini) is offline or unreachable.
    """
    import re
    msg = user_msg.strip()

    # ── 1. Weather Advisory Context ───────────────────────────────────────────
    if "Current Weather in" in msg or "Weather Advisory" in msg or "Next 5-Day Forecast:" in msg:
        city_match = re.search(r"Current Weather in ([^\n:]+)", msg)
        city = city_match.group(1).strip() if city_match else "your location"

        temp_match = re.search(r"Temperature:\s*([0-9.]+)", msg)
        temp = float(temp_match.group(1)) if temp_match else None

        rain_match = re.search(r"Rain Probability:\s*([0-9.]+)", msg) or re.search(r"Precipitation Chance:\s*([0-9.]+)", msg)
        rain_pct = float(rain_match.group(1)) if rain_match else 0

        wind_match = re.search(r"Wind Speed:\s*([0-9.]+)", msg)
        wind_spd = float(wind_match.group(1)) if wind_match else 10.0

        cond_match = re.search(r"Condition:\s*([^\n]+)", msg)
        condition = cond_match.group(1).strip() if cond_match else "Normal"

        irrigation_advice = (
            "Suspend scheduled irrigation for the next 24–48 hours to avoid field waterlogging, root suffocation, and nutrient leaching."
            if (rain_pct >= 40 or "rain" in condition.lower() or "drizzle" in condition.lower())
            else "Maintain light, regulated irrigation during early morning or late afternoon hours. Avoid midday flood irrigation to minimize evaporative loss and heat shock."
        )

        spray_advice = (
            "Avoid chemical and foliar pesticide spraying today due to high wind drift risk and potential loss of spray coverage."
            if wind_spd > 15
            else (
                "Postpone foliar sprays and top-dressing fertilizers; rainfall within the next 24 hours will wash off active ingredients."
                if rain_pct >= 45
                else "Weather conditions are favorable for foliar nutrient sprays and targeted pesticide applications during calm morning hours (7:00 AM – 10:00 AM)."
            )
        )

        risk_advice = (
            "Ensure field drainage channels and trenches are cleared of debris to facilitate rapid surface runoff during anticipated rainfall."
            if (rain_pct >= 40 or "rain" in condition.lower())
            else (
                "High temperatures may induce heat stress. Consider soil mulching or light misting to preserve root zone moisture."
                if (temp and temp >= 35)
                else "Stable meteorological window observed. Continue routine crop monitoring and maintain scheduled weeding and intercultural operations."
            )
        )

        return (
            f"### Hyperlocal Weather & Agronomic Advisory — {city}\n\n"
            f"**Current Snapshot:** {condition}{f', {temp}°C' if temp else ''}, Wind: {wind_spd} km/h, Rain Probability: {rain_pct}%\n\n"
            f"#### 1. Irrigation Recommendation\n{irrigation_advice}\n\n"
            f"#### 2. Spraying & Fertilizer Suitability\n{spray_advice}\n\n"
            f"#### 3. Crop Protection & 3–5 Day Advisory\n{risk_advice}\n\n"
            f"*Generated by KrishiMitra Agronomic Intelligence Engine based on ICAR field advisory guidelines.*"
        )

    # ── 2. Market Prices Context ──────────────────────────────────────────────
    if "Current Mandi Data (Agmarknet" in msg or "Commodity Filter:" in msg or "Modal Price" in msg:
        lines = [line.strip() for line in msg.split("\n") if line.strip().startswith("- ")]
        loc_match = re.search(r"Location:\s*([^\n]+)", msg)
        location = loc_match.group(1).strip() if loc_match else "Reporting APMC Mandis"
        comm_match = re.search(r"Commodity Filter:\s*([^\n]+)", msg)
        commodity = comm_match.group(1).strip() if comm_match else "Agricultural Produce"

        prices = []
        for line in lines:
            p_match = re.search(r"Modal Price\s*₹?([0-9,]+)", line)
            if p_match:
                try:
                    prices.append(float(p_match.group(1).replace(",", "")))
                except ValueError:
                    pass

        avg_price = round(sum(prices) / len(prices)) if prices else None
        max_price = round(max(prices)) if prices else None
        min_price = round(min(prices)) if prices else None
        spread = (max_price - min_price) if (max_price and min_price) else 0

        spread_note = (
            f"Notable mandi price spread of ₹{spread}/Qtl observed across reporting yards (Low: ₹{min_price}/Qtl, High: ₹{max_price}/Qtl). "
            f"Average modal rate stands at ₹{avg_price}/Qtl."
            if spread > 0
            else f"Reported modal rate stands at ₹{avg_price or 'N/A'}/Qtl across active yards."
        )

        return (
            f"### Mandi Market Price Analysis — {commodity} ({location})\n\n"
            f"#### 1. Price Distribution & Spread\n"
            f"{spread_note}\n\n"
            f"#### 2. Practical Selling Considerations for Farmers\n"
            f"- **Immediate Dispatch vs Holding:** If current modal rates cover your production cost plus targeted margin, consider partial selling (40–60% of stock) to lock in profits while mitigating downside price volatility.\n"
            f"- **Logistics & Transportation Tradeoff:** Transporting produce to higher-paying mandis is only profitable if the price differential exceeds freight, handling, and loading costs (typically ₹30–₹60/Qtl).\n"
            f"- **Quality Differentiation:** Ensure proper cleaning, grading, and moisture reduction (< 12% for grains) before entering the mandi yard to qualify for top-tier modal bidding.\n\n"
            f"#### 3. Market Snapshot Notice\n"
            f"*This analysis reflects verified daily mandi arrivals from Data.gov.in (Agmarknet). Multi-week historical records should be monitored before committing to extended long-term commercial holding.*"
        )

    # ── 3. Crop Plan Context ──────────────────────────────────────────────────
    if "Crop Plan:" in msg or ("Crop:" in msg and "Growth Stage:" in msg):
        crop_match = re.search(r"Crop:\s*([^\n,]+)", msg)
        crop = crop_match.group(1).strip() if crop_match else "Standing Crop"
        stage_match = re.search(r"Current Growth Stage:\s*([^\n·(]+)", msg)
        stage = stage_match.group(1).strip() if stage_match else "Active Vegetative"

        return (
            f"### Crop Management Review — {crop} ({stage})\n\n"
            f"#### 1. Nutrition & Irrigation at {stage}\n"
            f"- Ensure adequate root-zone moisture during this critical growth transition. Water stress at {stage.lower()} directly limits final yield potential.\n"
            f"- Apply scheduled top-dressing fertilizers in split doses according to soil test recommendations. Avoid excessive nitrogen which promotes succulent foliage vulnerable to sucking pests.\n\n"
            f"#### 2. Disease & Pest Surveillance\n"
            f"- Scout the undersides of leaves and crown zones twice weekly for early signs of fungal leaf spots, stem rot, or insect pest infestation.\n"
            f"- Install yellow/blue sticky traps (10–12 per acre) and pheromone traps for cost-effective pest monitoring before chemical intervention.\n\n"
            f"#### 3. Upcoming Agronomic Tasks\n"
            f"- Plan intercultural weeding or light hoeing to maintain soil aeration and suppress weed competition.\n"
            f"- Prepare inputs and equipment in advance for the upcoming growth milestone.\n\n"
            f"*Synthesized from KrishiMitra Agronomic Timeline & ICAR Package of Practices.*"
        )

    # ── 4. General Crop Irrigation Guidance (ICAR Guidelines) ─────────────────
    if re.search(r"\b(irrigate|irrigation|water|watering)\b", msg, re.I) and re.search(r"\b(wheat|gehu|gehun)\b", msg, re.I):
        is_harvest_q = bool(re.search(r"\b(harvest|harvesting|cutting|mature|maturity|stop|final)\b", msg, re.I))
        if is_harvest_q:
            return (
                "### Wheat Irrigation Advisory — Harvesting Stage\n\n"
                "**Critical Harvest Instruction:**\n"
                "- **Stop all irrigation completely 10–15 days before harvest.**\n\n"
                "**Why this matters:**\n"
                "- Facilitates uniform drying and hardening of grains.\n"
                "- Prevents crop lodging (falling over) caused by wet soil and late winds.\n"
                "- Avoids fungal grain blackening and reduces moisture content for safe storage (< 12%).\n\n"
                "*Based on ICAR wheat package of practices.*"
            )
        else:
            return (
                "### Wheat Irrigation Schedule & Critical Growth Stages\n\n"
                "To achieve optimum wheat yield, irrigation should be scheduled according to the **6 critical physiological growth stages** (recommended by ICAR):\n\n"
                "1. **Crown Root Initiation (CRI Stage) — 20 to 25 Days After Sowing (DAS):**\n"
                "   - **Most Critical Irrigation:** If you only have water for one irrigation, apply it here. Delaying this irrigation permanently limits root development and reduces tillering by 20–30%.\n\n"
                "2. **Tillering Stage — 40 to 45 DAS:**\n"
                "   - Promotes vigorous secondary tiller formation and leaf canopy development.\n\n"
                "3. **Late Jointing Stage — 60 to 65 DAS:**\n"
                "   - Supports rapid stem elongation and spikelet initiation inside the boot.\n\n"
                "4. **Flowering / Heading Stage — 80 to 85 DAS:**\n"
                "   - Critical reproductive window: moisture stress during flowering causes floret sterility and fewer grains per earhead.\n\n"
                "5. **Milk Stage — 100 to 105 DAS:**\n"
                "   - Essential for rapid starch accumulation and grain filling.\n\n"
                "6. **Dough Stage — 115 to 120 DAS:**\n"
                "   - Final light watering to maximize grain test weight. Avoid heavy watering during windy days to prevent lodging.\n\n"
                "⚠️ **Pre-Harvest Precaution:**\n"
                "- **Stop irrigation completely 10–15 days before harvesting** to allow the crop to ripen uniformly and avoid combine harvester issues.\n\n"
                "*Note: If your wheat crop is currently standing, let me know your sowing date or current growth stage for a customized daily watering plan.*"
            )

    return None


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_stream(request):
    """Streams a chat response from Google Gemini, with knowledge-base fallbacks."""
    raw_msg = request.data.get('message')
    if raw_msg is None or not isinstance(raw_msg, str) or not raw_msg.strip():
        return Response({'error': 'A non-empty "message" string is required.'}, status=400)
    user_msg = raw_msg.strip()
    if len(user_msg) > 8000:
        return Response({'error': 'Message is too long. Please keep it under 8000 characters.'}, status=400)
    session_id = request.data.get('sessionId') or 'default'
    if not isinstance(session_id, str) or len(session_id) > 100:
        return Response({'error': 'Invalid sessionId.'}, status=400)
    force_json = request.data.get('forceJson', False)
    field_id = request.data.get('field_id', None)

    # Retrieve RAG context from ChromaDB if available
    rag_context = ""
    chroma_client = ml_loader.state.get("chroma_client")
    if chroma_client:
        try:
            import re
            all_collections = chroma_client.list_collections()
            pooled_results = []
            main_col = ml_loader.state.get("collection")
            ef = main_col._embedding_function if main_col else None

            # Detect known crops in user query
            known_crops = [
                'wheat', 'rice', 'pigeonpea', 'cotton', 'soybean', 'maize',
                'mustard', 'tomato', 'potato', 'chilli', 'onion', 'groundnut',
                'sugarcane', 'bajra', 'barley', 'chickpea', 'fennel', 'guar',
                'mungbean', 'sesame', 'sunflower', 'turmeric', 'uradbean', 'banana'
            ]
            detected_crop = None
            for c in known_crops:
                if re.search(r'\b' + c + r'\b', user_msg, re.I):
                    detected_crop = c.capitalize()
                    break

            is_stage_specific = bool(re.search(
                r'\b(harvest|harvesting|cutting|sow|sowing|seed|emergence|germination|flowering|flower|pod|grain|dough|milking|milk|cri|crown)\b',
                user_msg,
                re.I
            ))

            for col_meta in all_collections:
                col_name = col_meta.name if hasattr(
                    col_meta, "name") else col_meta
                col = chroma_client.get_collection(
                    col_name, embedding_function=ef)
                if col.count() == 0:
                    continue

                if col_name == "timeline_kb" and detected_crop:
                    # Crop-aware retrieval from timeline_kb
                    try:
                        crop_data = col.get(where={'crop': detected_crop})
                        if crop_data and crop_data.get("documents"):
                            docs = crop_data["documents"]
                            metas = crop_data["metadatas"]
                            if not is_stage_specific:
                                # General crop inquiry: sort chronologically so early/vegetative/flowering precede harvest
                                sorted_pairs = sorted(
                                    zip(metas, docs),
                                    key=lambda x: x[0].get('stage_day_start', 0)
                                )
                                for m, d in sorted_pairs:
                                    pooled_results.append((d, 0.40))
                            else:
                                # Stage-specific query: run semantic ranking on this crop
                                qres = col.query(
                                    query_texts=[user_msg],
                                    where={'crop': detected_crop},
                                    n_results=min(col.count(), 6)
                                )
                                if qres.get("documents") and len(qres["documents"]) > 0:
                                    for idx, d in enumerate(qres["documents"][0]):
                                        dist = qres["distances"][0][idx] if qres.get("distances") else 0.5
                                        pooled_results.append((d, dist))
                    except Exception:
                        pass
                else:
                    res = col.query(
                        query_texts=[user_msg], n_results=min(
                            col.count(), 3))
                    if res.get("documents") and len(res["documents"]) > 0:
                        docs = res["documents"][0]
                        dists = res.get("distances", [[]])[0] if res.get("distances") else []
                        for idx, doc in enumerate(docs):
                            dist = dists[idx] if idx < len(dists) else 1.0
                            pooled_results.append((doc, dist))

            if pooled_results:
                pooled_results.sort(key=lambda x: x[1])
                # Deduplicate documents while preserving optimal order
                seen = set()
                unique_docs = []
                for doc, dist in pooled_results:
                    if dist <= 1.05 and doc not in seen:
                        seen.add(doc)
                        unique_docs.append(doc)
                if unique_docs:
                    rag_context = "\n\nContext from Knowledge Base:\n" + \
                        "\n---\n".join(unique_docs[:6])
        except Exception:
            pass



    farm_id = request.data.get('farmId')

    from datetime import datetime
    datetime.now().strftime("%Y-%m-%d")

    if force_json:
        import re
        import os
        import pandas as pd
        from datetime import datetime, timedelta

        crop_match = re.search(r"Crop:\s*([^,]+)", user_msg, re.IGNORECASE)
        season_match = re.search(r"Season:\s*([^,]+)", user_msg, re.IGNORECASE)

        req_crop = crop_match.group(1).strip(
        ).capitalize() if crop_match else "Soybean"
        req_season = season_match.group(
            1).strip() if season_match else "Kharif"

        sowing_date_obj = datetime.now()
        sowing_date_str = sowing_date_obj.strftime("%Y-%m-%d")

        data_dir = os.path.join(settings.BASE_DIR, "krishi_core", "data")
        tasks_csv = os.path.join(data_dir, "02_crop_task_calendar.csv")
        fert_csv = os.path.join(data_dir, "06_crop_fertilizer_plan.csv")
        profile_csv = os.path.join(data_dir, "01_crop_profile.csv")

        milestones = []
        tasks = []
        irrigation_cycles = []
        fertilizer_events = []
        harvest_date_obj = sowing_date_obj + timedelta(days=100)  # Default

        try:
            # 1. Load data
            df_tasks = pd.read_csv(tasks_csv)
            df_fert = pd.read_csv(fert_csv)
            df_prof = pd.read_csv(profile_csv)

            # Filter for crop
            crop_tasks = df_tasks[df_tasks['crop_name'].str.lower(
            ) == req_crop.lower()]
            crop_fert = df_fert[df_fert['crop_name'].str.lower()
                                == req_crop.lower()]
            crop_prof = df_prof[df_prof['crop_name'].str.lower()
                                == req_crop.lower()]

            if not crop_prof.empty:
                harvest_days = crop_prof.iloc[0].get('harvest_days', 100)
                harvest_date_obj = sowing_date_obj + \
                    timedelta(days=int(harvest_days))

            if not crop_tasks.empty:
                # Group by stage to create milestones
                stages = crop_tasks['stage'].unique()
                for stage in stages:
                    stage_tasks = crop_tasks[crop_tasks['stage'] == stage]
                    start_day = stage_tasks['day_from_sowing_start'].min()
                    end_day = stage_tasks['day_from_sowing_end'].max()
                    start_date = sowing_date_obj + \
                        timedelta(days=int(start_day))

                    milestones.append({
                        "stage": stage,
                        "plannedDate": start_date.strftime("%Y-%m-%d"),
                        "description": f"Expected duration around {int(end_day - start_day)} days."
                    })

                # Create detailed tasks
                for _, row in crop_tasks.iterrows():
                    start_day = int(row['day_from_sowing_start'])
                    task_date = sowing_date_obj + timedelta(days=start_day)

                    tasks.append({
                        "title": row['task'],
                        "date": task_date.strftime("%Y-%m-%d"),
                        "category": row['task_category'].lower().replace(' ', '_'),
                        "priority": row['priority'].lower(),
                        "description": row['description']
                    })

                    if "irrigat" in row['task_category'].lower(
                    ) or "irrigat" in row['task'].lower():
                        irrigation_cycles.append({
                            "day": start_day,
                            "method": "As per profile",
                            "duration": row['description']
                        })

            if not crop_fert.empty:
                # Inject basic fertilizer doses as tasks
                for _, row in crop_fert.iterrows():
                    stage = row['stage'].lower()
                    # Determine approx day
                    day_offset = 0
                    if "basal" in stage:
                        day_offset = 0
                    elif "top-dress 1" in stage:
                        day_offset = 30
                    elif "top-dress 2" in stage:
                        day_offset = 60

                    task_date = sowing_date_obj + timedelta(days=day_offset)

                    tasks.append({
                        "title": f"Apply Fertilizer ({row['stage']})",
                        "date": task_date.strftime("%Y-%m-%d"),
                        "category": "fertilizer",
                        "priority": "high",
                        "description": f"{row['products_and_dose']} - {row['purpose']}"
                    })
                    fertilizer_events.append({
                        "day": day_offset,
                        "type": "Specific",
                        "amount": row['products_and_dose']
                    })
                    
            # 2. Add AI-driven Soil Fixes & Smart Fertilizer Suggestions
            try:
                from .services.ai_engine.llm_service import llm_service
                
                farm = Farm.objects.filter(id=farm_id, owner=request.user).first() if str(farm_id or '').isdigit() else None
                if farm and (farm.ph or farm.nitrogen or farm.ec):
                    ideal_soil_text = crop_prof.iloc[0]['soil_type'] if not crop_prof.empty else "well drained, neutral pH"
                    
                    prompt = f"""
You are an expert agronomist. 
We are creating a crop plan for {req_crop}. The ideal soil condition for this crop is: {ideal_soil_text}.
The user's farm soil test report shows:
pH: {farm.ph or 'Unknown'}
Nitrogen: {farm.nitrogen or 'Unknown'} kg/ha
Phosphorus: {farm.phosphorus or 'Unknown'} kg/ha
Potassium: {farm.potassium or 'Unknown'} kg/ha
Organic Carbon: {farm.organicCarbon or 'Unknown'} %
EC: {farm.ec or 'Unknown'} dS/m

Output ONLY a raw JSON object with this exact schema:
{{
  "fixes": "A short, actionable paragraph explaining exactly what needs to be fixed to reach ideal conditions for {req_crop}.",
  "fertilizer_recommendation": "A specific fertilizer suggestion based on the deficiencies.",
  "add_as_task": true,
  "task_title": "Soil Correction & Pre-sowing Fertilization",
  "task_description": "Short summary of the fertilizer action required."
}}
"""
                    ai_response = llm_service.generate_response(prompt)
                    if isinstance(ai_response, dict) and not "error" in ai_response:
                        milestones.insert(0, {
                            "stage": "Pre-sowing Soil Correction",
                            "plannedDate": sowing_date_str,
                            "description": ai_response.get("fixes", "Adjust soil nutrients before sowing.")
                        })
                        fertilizer_events.append({
                            "day": 0,
                            "type": "Custom AI Recommendation",
                            "amount": ai_response.get("fertilizer_recommendation", "Apply standard NPK basal dose.")
                        })
                        if ai_response.get("add_as_task"):
                            tasks.append({
                                "title": ai_response.get("task_title", "Soil Correction"),
                                "date": sowing_date_str,
                                "category": "fertilizer",
                                "priority": "high",
                                "description": ai_response.get("task_description", "Apply recommended fertilizers to correct soil profile.")
                            })
            except Exception as e:
                print(f"Error calling LLM for soil fixes: {e}")

        except Exception as e:
            print(f"Error parsing pandas plan: {e}")

        result = {
            "cropPlan": {
                "cropName": req_crop,
                "season": req_season,
                "sowingDate": sowing_date_str,
                "expectedHarvestDate": harvest_date_obj.strftime("%Y-%m-%d"),
                "milestones": milestones,
                "irrigationCycles": irrigation_cycles,
                "fertilizerEvents": fertilizer_events
            },
            "tasks": tasks
        }
        return Response({"result": result})

    # Save user message
    ChatMessage.objects.create(
        owner=request.user,
        sessionId=session_id,
        role='user',
        content=user_msg
    )

    def generate():
        system_prompt = (
            "You are KrishiMitra AI, a helpful, expert agricultural assistant for Indian farmers.\n"
            "STYLE & CONVERSATIONAL GUIDELINES:\n"
            "1. Answer concisely, practically, and respectfully.\n"
            "2. DO NOT repeat your introduction ('Namaste! I am KrishiMitra, your expert agricultural assistant...') on every reply. Jump directly into the answer or advisory.\n"
            "3. If the user gives a greeting (such as 'hi', 'hello', 'namaste', 'kem cho'), respond with a warm, brief greeting and ask how you can help their farm today.\n"
            "4. If the user asks a casual or non-agricultural question, respond politely and naturally while maintaining an agricultural domain readiness.\n"
            "5. For farming queries, give structured, practical advice grounded in verified agricultural science (ICAR guidelines).\n\n"
            "CRITICAL AGRONOMIC REASONING RULES:\n"
            "1. When the user asks a general agricultural question (such as 'What is the best time to irrigate wheat?' or general fertilizer timing) without specifying a growth stage, provide direct, comprehensive guidance covering the critical physiological growth stages (for example, for wheat: Crown Root Initiation (CRI) at 20–25 days, Tillering at 40–45 days, Late Jointing at 60–65 days, Flowering at 80–85 days, Milking at 100–105 days, and Dough stage at 115–120 days).\n"
            "2. Do NOT assume the crop is at the harvesting stage unless the user explicitly establishes that stage or the active crop plan specifies it.\n"
            "3. Stage-specific instructions (such as stopping irrigation 10–15 days before harvest) must only be mentioned in the context of the final maturity/harvesting stage, never as the primary or sole answer to a general irrigation question.\n"
            "4. If the crop stage is unknown and materially affects the answer, present the overall schedule first, explain that the current stage matters, and invite the user to share their sowing date or current crop stage.\n\n"
        )
        if rag_context:
            system_prompt += (
                "Refer to the following verified documents from the KrishiMitra knowledge base when answering:\n"
                f"{rag_context}\n\n"
            )
        system_prompt += (
            "When the user's question includes real-time context (such as live weather conditions, APMC mandi prices, crop growth stages, or soil data), "
            "synthesize your recommendations directly from that contextual data. Answer concisely with clear headings and bullet points.\n\n"
        )

        prompt_text = f"{system_prompt}User Question: {user_msg}\nAnswer concisely:"

        full_response = ""
        provider_used = None

        # ── Tier 1: Google Gemini ─────────────────────────────────────────────
        text_resp, gemini_model = gemini_generate(prompt_text, timeout=(4.0, 30.0))
        if text_resp:
            provider_used = f"gemini:{gemini_model}"
            full_response = text_resp
            chunk_size = 48
            for i in range(0, len(text_resp), chunk_size):
                yield f"data: {json.dumps({'chunk': text_resp[i:i+chunk_size]})}\n\n"

        # ── Tier 2: Contextual Agronomic Intelligence Engine ───────────────────
        if not provider_used:
            contextual_advisory = synthesize_contextual_advisory(user_msg)
            if contextual_advisory:
                provider_used = "agronomic_engine"
                full_response = contextual_advisory
                chunk_size = 64
                for i in range(0, len(contextual_advisory), chunk_size):
                    yield f"data: {json.dumps({'chunk': contextual_advisory[i:i+chunk_size]})}\n\n"

        # ── Tier 3: Direct ChromaDB Knowledge Base Fallback ───────────────────
        if not provider_used:
            if rag_context and rag_context.strip():
                provider_used = "chroma_direct"
                header = "### Verified Knowledge Base Information\n\n*(AI model currently offline or rate-limited — displaying verified agronomic records from KrishiMitra Knowledge Base)*\n\n"
                body = header + rag_context.strip()
                full_response = body
                chunk_size = 64
                for i in range(0, len(body), chunk_size):
                    yield f"data: {json.dumps({'chunk': body[i:i+chunk_size]})}\n\n"
            else:
                # ── Tier 4: Explicit Error Signaling (Service Unavailable) ────
                provider_used = "none"
                error_msg = (
                    "The AI service is currently unavailable (offline, rate-limited, or unconfigured). "
                    "Please check your network or try again shortly."
                )
                yield f"data: {json.dumps({'error': error_msg})}\n\n"

        yield "data: [DONE]\n\n"

        # Save AI response
        if full_response and provider_used != "none":
            try:
                ChatMessage.objects.create(
                    owner=request.user,
                    sessionId=session_id,
                    role='assistant',
                    content=full_response,
                    contextSnapshot={"provider": provider_used}
                )
            except Exception:
                pass

    response = StreamingHttpResponse(
        generate(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def chat_sync_plan(request):
    """Saves a generated crop plan or schedule from the AI."""
    sync_data = request.data.get('syncData') or {}
    farm_id = request.data.get('farmId')
    if not isinstance(sync_data, dict):
        return Response({'message': 'syncData must be an object.'}, status=400)

    try:
        farm = Farm.objects.get(id=int(farm_id), owner=request.user)
    except (Farm.DoesNotExist, TypeError, ValueError):
        return Response({'message': 'Farm not found.'}, status=404)

    tasks_generated = 0
    plan_obj = None

    import uuid
    plan_data = sync_data.get('cropPlan')
    if plan_data:
        if not isinstance(plan_data, dict):
            return Response({'message': 'cropPlan must be an object.'}, status=400)
        # Match MongoDB structure for milestones
        milestones = plan_data.get('milestones') or []
        if not isinstance(milestones, list) or not all(isinstance(m, dict) for m in milestones):
            return Response({'message': 'milestones must be a list of objects.'}, status=400)
        for m in milestones:
            m['_id'] = m.get('_id', str(uuid.uuid4()))
            m['status'] = m.get('status', 'pending')
            m['notes'] = m.get('notes', '')

        serializer = CropPlanSerializer(data={
            'farm': farm.id,
            'cropName': plan_data.get('cropName') or 'Unknown Crop',
            'season': plan_data.get('season') or 'Unknown',
            'sowingDate': plan_data.get('sowingDate') or '2025-01-01',
            'expectedHarvestDate': plan_data.get('expectedHarvestDate') or '2025-06-01',
            'milestones': milestones,
            'irrigationCycles': plan_data.get('irrigationCycles') or [],
            'fertilizerEvents': plan_data.get('fertilizerEvents') or [],
            'estimatedCost': plan_data.get('estimatedCost') or 0,
            'targetYieldKg': plan_data.get('targetYieldKg') or 0,
            'status': 'active',
        }, context={'request': request})
        if not serializer.is_valid():
            return Response({'message': 'Invalid crop plan.', 'errors': serializer.errors}, status=400)
        plan_obj = serializer.save(owner=request.user)

    return Response({'success': True})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def soil_reports(request):
    # Compatibility endpoint for frontend, scoped to authenticated user
    return Response([])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def chat_sessions(request):
    """
    Returns all previous chat sessions belonging exclusively to the authenticated user.
    Each session is labeled with its first user question as the title,
    an assistant message preview, update timestamp, and message count.
    """
    messages = ChatMessage.objects.filter(owner=request.user).order_by('created_at')
    sessions_map = {}
    for msg in messages:
        sid = msg.sessionId
        if not sid:
            continue
        if sid not in sessions_map:
            sessions_map[sid] = {
                'sessionId': sid,
                'title': '',
                'preview': '',
                'updated_at': msg.created_at,
                'created_at': msg.created_at,
                'message_count': 0
            }
        sessions_map[sid]['message_count'] += 1
        sessions_map[sid]['updated_at'] = msg.created_at

        # First user message provides the conversation title
        if msg.role == 'user' and not sessions_map[sid]['title']:
            clean_title = msg.content.strip().replace('\n', ' ')
            if len(clean_title) > 60:
                clean_title = clean_title[:57] + '...'
            sessions_map[sid]['title'] = clean_title
        elif not sessions_map[sid]['preview'] and msg.role == 'assistant':
            clean_prev = msg.content.strip().replace('\n', ' ')
            if clean_prev.startswith('### '):
                clean_prev = clean_prev[4:]
            sessions_map[sid]['preview'] = clean_prev[:80] + '...' if len(clean_prev) > 80 else clean_prev

    session_list = sorted(sessions_map.values(), key=lambda s: s['updated_at'], reverse=True)
    for s in session_list:
        if not s['title']:
            clean_sid = s['sessionId']
            for prefix in ('task-weather-', 'task-market-', 'task-crop-plan-', 'task-feature-', 'session-', 'chat-'):
                if clean_sid.startswith(prefix):
                    clean_sid = clean_sid[len(prefix):]
                    break
            s['title'] = clean_sid.replace('-', ' ').title() or "Agricultural Chat"

    return Response(session_list)


@api_view(['GET', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def chat_history(request, sid):
    """
    GET: Retrieves the complete ordered conversation history for the given session ID,
         scoped strictly to the authenticated user.
    DELETE: Deletes the specified conversation belonging to the authenticated user.
    """
    if request.method == 'DELETE':
        deleted_count, _ = ChatMessage.objects.filter(
            owner=request.user,
            sessionId=sid
        ).delete()
        return Response({
            'success': True,
            'deleted': deleted_count,
            'sessionId': sid
        })

    messages = ChatMessage.objects.filter(
        owner=request.user,
        sessionId=sid).order_by('created_at')
    data = []
    for m in messages:
        data.append({
            'id': str(m.id),
            'role': m.role,
            'content': m.content,
            'text': m.content,
            'timestamp': m.created_at
        })
    return Response(data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def weather_cache_get(request, key):
    from django.utils import timezone
    try:
        cache = WeatherCache.objects.get(locationKey=key)
        dt = getattr(cache, 'fetchedAt', None) or getattr(cache, 'updated_at', timezone.now())
        age_seconds = (timezone.now() - dt).total_seconds() if dt else 0
        age_minutes = max(0, int(age_seconds // 60))
        source = 'cache' if age_minutes < 60 else 'stale'
        data = WeatherCacheSerializer(cache).data
        data['source'] = source
        data['ageMinutes'] = age_minutes
        data['cachedAt'] = dt.isoformat() if dt else None
        return Response(data)
    except WeatherCache.DoesNotExist:
        return Response({'message': 'Not found'}, status=404)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def weather_cache_set(request):
    from django.utils import timezone
    import math
    key = request.data.get('locationKey')
    if not key or not isinstance(key, str) or len(key) > 255:
        return Response({'error': 'locationKey required (max 255 characters)'}, status=400)
    payload = request.data.get('data', {})
    if not isinstance(payload, dict) or len(json.dumps(payload, default=str)) > 300000:
        return Response({'error': 'data must be a weather object'}, status=400)
    coords = {}
    for name, bound in (('lat', 90), ('lon', 180)):
        raw = request.data.get(name)
        if raw in (None, ''):
            coords[name] = None
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return Response({'error': f'{name} must be a number'}, status=400)
        if not math.isfinite(value) or abs(value) > bound:
            return Response({'error': f'{name} is out of range'}, status=400)
        coords[name] = value
    city = str(request.data.get('cityName') or '')[:255]

    cache, created = WeatherCache.objects.update_or_create(
        locationKey=key,
        defaults={
            'cityName': city,
            'lat': coords['lat'],
            'lon': coords['lon'],
            'data': payload
        }
    )
    cache.fetchedAt = timezone.now()
    cache.save()
    return Response(WeatherCacheSerializer(cache).data)



@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def geocode(request):
    """
    Backend geocoding endpoint: queries Nominatim (restricted to India) and merges
    with high-confidence Indian agricultural centers. Deduplicates identical city/state
    pairs and ranks best prefix matches first.
    Returns:
    { query, address, display_name, city, district, state, lat, lon, results: [...] }
    """
    q = request.query_params.get('q', '').strip() or request.query_params.get('query', '').strip()
    if not q:
        return Response({'error': 'Query parameter q is required', 'results': []}, status=400)
    if len(q) > 200:
        return Response({'error': 'Query is too long (max 200 characters)', 'results': []}, status=400)
    
    try:
        limit = int(request.query_params.get('limit', 5))
    except ValueError:
        limit = 5
    limit = max(1, min(10, limit))
    
    
    out = geocode_lookup(q, limit)
    if out is None:
        return Response({'error': f'No locations found for "{q}"', 'results': []}, status=404)
    return Response(out)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def geocode_reverse(request):
    """
    Backend reverse geocoding endpoint: takes lat and lon, returns normalized address info.
    """
    lat_str = request.query_params.get('lat')
    lon_str = request.query_params.get('lon')
    if not lat_str or not lon_str:
        return Response({'error': 'lat and lon query parameters are required'}, status=400)
    
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return Response({'error': 'Invalid lat or lon parameter'}, status=400)
    import math
    if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > 90 or abs(lon) > 180:
        return Response({'error': 'lat must be within ±90 and lon within ±180'}, status=400)
        
    cache_key = f"rev:{lat:.4f}:{lon:.4f}"
    if cache_key in _GEOCODE_CACHE:
        return Response(_GEOCODE_CACHE[cache_key])
        
    headers = {
        'User-Agent': 'KrishiMitra-App/1.0 (agronomy-dev@krishimitra.org)',
        'Accept': 'application/json'
    }
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&addressdetails=1"
    try:
        resp = requests.get(url, headers=headers, timeout=(4.0, 15.0))
        if resp.status_code != 200:
            return Response({'error': f'Reverse geocoding service returned status {resp.status_code}'}, status=502)
        try:
            data = resp.json()
        except Exception:
            return Response({'error': 'Reverse geocoding service returned invalid response format'}, status=502)
            
        addr = data.get('address', {})
        city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('suburb') or addr.get('county') or ''
        state = addr.get('state') or ''
        district = addr.get('state_district') or addr.get('county') or ''
        disp = data.get('display_name', '')
        
        parts = [city, state] if city and state else [disp.split(',')[0].strip(), state] if state else [disp]
        clean_addr = ', '.join([p for p in parts if p])
        
        out = {
            'query': clean_addr,
            'address': clean_addr or disp,
            'display_name': disp,
            'city': city,
            'district': district,
            'state': state,
            'lat': lat,
            'lon': lon,
            'raw_address': addr,
        }
        _GEOCODE_CACHE[cache_key] = out
        return Response(out)
    except Exception:
        logger.warning("Reverse geocoding failed", exc_info=True)
        return Response({'error': 'Reverse geocoding is unavailable right now. Please type your location.'}, status=502)




