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
from rest_framework.decorators import api_view, permission_classes, action
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

logger = logging.getLogger(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────


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
    raw_email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    password = data.get('password', '')
    first_name = (data.get('firstName') or '').strip()
    last_name = (data.get('lastName') or '').strip()
    name = (data.get('name') or '').strip()
    if name and not first_name:
        parts = name.split(' ', 1)
        first_name = parts[0]
        if len(parts) > 1 and not last_name:
            last_name = parts[1]

    verification_token = data.get('verificationToken')
    otp_code = (data.get('otp') or '').strip()

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

    if User.objects.filter(email=email).exists():
        return Response({'message': 'An account with this email already exists.'}, status=400)

    if phone and User.objects.filter(phone=phone).exists():
        return Response({'message': 'Phone number already registered.'}, status=400)

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
        role=data.get('role', 'farmer'),
        location=loc_dict,
        farmingMode=data.get('farmingMode', 'moderate'),
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
    identifier = (request.data.get('email') or request.data.get('username') or '').strip().lower()
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


@api_view(['PATCH', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def auth_update_profile(request):
    """Update the logged-in user's profile."""
    user = request.user
    data = request.data

    if 'firstName' in data:
        user.first_name = data['firstName']
    if 'lastName' in data:
        user.last_name = data['lastName']
    if 'phone' in data:
        user.phone = data['phone']
    if 'language' in data:
        user.language = data['language']
    if 'farmingMode' in data:
        user.farmingMode = data['farmingMode']
    if 'avatarUrl' in data:
        user.avatarUrl = data['avatarUrl']
    if 'location' in data:
        loc = data['location']
        if isinstance(loc, dict):
            user.location = loc
        elif isinstance(loc, str) and loc.strip():
            user.location = {'address': loc.strip()}
        elif loc is None or loc == '':
            user.location = {}
        else:
            user.location = {'address': str(loc)}
    if 'settings' in data:
        user.settings = data['settings']

    user.save()
    serializer = UserSerializer(user)
    return Response({'user': serializer.data})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def auth_change_password(request):
    """Change the logged-in user's password."""
    user = request.user
    old_password = request.data.get('oldPassword')
    new_password = request.data.get('newPassword')

    if not user.check_password(old_password):
        return Response({'message': 'Incorrect current password.'}, status=400)

    if not new_password or len(new_password) < 6:
        return Response({'message': 'New password must be at least 6 characters long.'}, status=400)

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

    raw_email = (request.data.get('email') or '').strip().lower()
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
    
    raw_email = (request.data.get('email') or '').strip().lower()
    otp_code = (request.data.get('otp') or '').strip()
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

    identifier = (request.data.get('email') or request.data.get('username') or '').strip().lower()
    phone = (request.data.get('phone') or '').strip()
    
    if not identifier and not phone:
        return Response({'message': 'Email, username, or phone is required.'}, status=400)

    if identifier and '@' in identifier:
        try:
            identifier = validate_email_syntax(identifier)
        except ValidationError as e:
            return Response({'message': e.message if hasattr(e, 'message') else str(e)}, status=400)

    user_by_identifier = (User.objects.filter(email=identifier).first() or User.objects.filter(username=identifier).first()) if identifier else None
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
    
    raw_email = (request.data.get('email') or '').strip().lower()
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

    raw_email = (request.data.get('email') or '').strip().lower()
    otp_code = (request.data.get('otp') or '').strip()
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


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(id=self.request.user.id)


class FarmViewSet(OwnerViewSet):
    queryset = Farm.objects.all()
    serializer_class = FarmSerializer

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
        limit = int(self.request.query_params.get('limit', 200))
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
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        last = MarketPrice.objects.order_by('-fetchedAt').first()
        return Response({
            'source': 'database',
            'records': serializer.data,
            'lastUpdated': last.fetchedAt if last else None,
            'needsRefresh': False,
        })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def market_locations(request):
    """Return distinct states and commodities for dropdowns."""
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
    when external LLM providers (Ollama / Gemini) are offline or unreachable.
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
def chat_stream(request):
    """Streams a chat response from Ollama (or Gemini if preferred)."""
    raw_msg = request.data.get('message')
    if raw_msg is None or not isinstance(raw_msg, str) or not raw_msg.strip():
        return Response({'error': 'A non-empty "message" string is required.'}, status=400)
    user_msg = raw_msg.strip()
    session_id = request.data.get('sessionId', 'default')
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
                
                farm = Farm.objects.filter(id=farm_id).first() if farm_id else None
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
        ollama_url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        ollama_model = getattr(settings, 'OLLAMA_MODEL', 'llama3.2:1b')

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

        # ── Tier 1: Try Local Ollama ──────────────────────────────────────────
        try:
            payload = {
                "model": ollama_model,
                "prompt": prompt_text,
                "stream": True,
            }
            with requests.post(ollama_url, json=payload, stream=True, timeout=(1.5, 30)) as r:
                if r.status_code == 200:
                    for line in r.iter_lines():
                        if line:
                            decoded = line.decode('utf-8')
                            try:
                                data = json.loads(decoded)
                                chunk = data.get("response", "")
                                if chunk:
                                    provider_used = "ollama"
                                    full_response += chunk
                                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                            except json.JSONDecodeError:
                                pass
        except Exception:
            pass

        # ── Tier 2: Try Cloud Gemini ──────────────────────────────────────────
        if not provider_used:
            gemini_key = getattr(settings, "GEMINI_API_KEY", "")
            if gemini_key:
                try:
                    import time
                    configured_model = getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest")
                    model_candidates = [configured_model]
                    for candidate in [
                        "gemini-flash-lite-latest",
                        "gemini-flash-latest",
                        "gemini-pro-latest",
                        "gemini-2.5-flash-lite",
                        "gemini-2.5-flash",
                        "gemini-1.5-flash",
                    ]:
                        if candidate not in model_candidates:
                            model_candidates.append(candidate)

                    for candidate_model in model_candidates:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent?key={gemini_key}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": prompt_text}]}]
                        }
                        res = None
                        try:
                            res = requests.post(
                                gemini_url,
                                json=gemini_payload,
                                headers={"Content-Type": "application/json"},
                                timeout=(4.0, 30.0)
                            )
                        except Exception:
                            continue

                        if res and res.status_code == 200:
                            candidates = res.json().get("candidates", [])
                            if candidates:
                                text_resp = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                if text_resp:
                                    provider_used = f"gemini:{candidate_model}"
                                    full_response = text_resp
                                    chunk_size = 48
                                    for i in range(0, len(text_resp), chunk_size):
                                        yield f"data: {json.dumps({'chunk': text_resp[i:i+chunk_size]})}\n\n"
                                    break
                except Exception:
                    pass

        # ── Tier 3: Contextual Agronomic Intelligence Engine ───────────────────
        if not provider_used:
            contextual_advisory = synthesize_contextual_advisory(user_msg)
            if contextual_advisory:
                provider_used = "agronomic_engine"
                full_response = contextual_advisory
                chunk_size = 64
                for i in range(0, len(contextual_advisory), chunk_size):
                    yield f"data: {json.dumps({'chunk': contextual_advisory[i:i+chunk_size]})}\n\n"

        # ── Tier 4: Direct ChromaDB Knowledge Base Fallback ───────────────────
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
                # ── Tier 5: Explicit Error Signaling (Service Unavailable) ────
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
    sync_data = request.data.get('syncData', {})
    farm_id = request.data.get('farmId')

    try:
        farm = Farm.objects.get(id=farm_id, owner=request.user)
    except Farm.DoesNotExist:
        return Response({'message': 'Farm not found.'}, status=404)

    tasks_generated = 0
    plan_obj = None

    import uuid
    plan_data = sync_data.get('cropPlan')
    if plan_data:
        # Match MongoDB structure for milestones
        milestones = plan_data.get('milestones', [])
        for m in milestones:
            m['_id'] = m.get('_id', str(uuid.uuid4()))
            m['status'] = m.get('status', 'pending')
            m['notes'] = m.get('notes', '')

        plan_obj = CropPlan.objects.create(
            owner=request.user,
            farm=farm,
            cropName=plan_data.get('cropName', 'Unknown Crop'),
            season=plan_data.get('season', 'Unknown'),
            sowingDate=plan_data.get('sowingDate', '2025-01-01'),
            expectedHarvestDate=plan_data.get('expectedHarvestDate', '2025-06-01'),
            milestones=plan_data.get('milestones', []),
            irrigationCycles=plan_data.get('irrigationCycles', []),
            fertilizerEvents=plan_data.get('fertilizerEvents', []),
            estimatedCost=plan_data.get('estimatedCost', 0) or 0,
            targetYieldKg=plan_data.get('targetYieldKg', 0) or 0,
            status='active'
        )

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
@permission_classes([permissions.AllowAny])
def weather_cache_set(request):
    from django.utils import timezone
    key = request.data.get('locationKey')
    if not key:
        return Response({'error': 'locationKey required'}, status=400)

    cache, created = WeatherCache.objects.update_or_create(
        locationKey=key,
        defaults={
            'cityName': request.data.get('cityName', ''),
            'lat': request.data.get('lat'),
            'lon': request.data.get('lon'),
            'data': request.data.get('data', {})
        }
    )
    cache.fetchedAt = timezone.now()
    cache.save()
    return Response(WeatherCacheSerializer(cache).data)


_GEOCODE_CACHE = {}

INDIAN_AGRI_CITIES = [
    {"city": "Surat", "district": "Surat", "state": "Gujarat", "lat": 21.1702, "lon": 72.8311},
    {"city": "Ahmedabad", "district": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lon": 72.5714},
    {"city": "Rajkot", "district": "Rajkot", "state": "Gujarat", "lat": 22.3039, "lon": 70.8022},
    {"city": "Vadodara", "district": "Vadodara", "state": "Gujarat", "lat": 22.3072, "lon": 73.1812},
    {"city": "Bhavnagar", "district": "Bhavnagar", "state": "Gujarat", "lat": 21.7645, "lon": 72.1519},
    {"city": "Junagadh", "district": "Junagadh", "state": "Gujarat", "lat": 21.5222, "lon": 70.4579},
    {"city": "Jamnagar", "district": "Jamnagar", "state": "Gujarat", "lat": 22.4707, "lon": 70.0577},
    {"city": "Anand", "district": "Anand", "state": "Gujarat", "lat": 22.5645, "lon": 72.9289},
    {"city": "Mehsana", "district": "Mehsana", "state": "Gujarat", "lat": 23.5880, "lon": 72.3693},
    {"city": "Pune", "district": "Pune", "state": "Maharashtra", "lat": 18.5204, "lon": 73.8567},
    {"city": "Nashik", "district": "Nashik", "state": "Maharashtra", "lat": 19.9975, "lon": 73.7898},
    {"city": "Nagpur", "district": "Nagpur", "state": "Maharashtra", "lat": 21.1458, "lon": 79.0882},
    {"city": "Kolhapur", "district": "Kolhapur", "state": "Maharashtra", "lat": 16.7050, "lon": 74.2433},
    {"city": "Solapur", "district": "Solapur", "state": "Maharashtra", "lat": 17.6599, "lon": 75.9064},
    {"city": "Aurangabad", "district": "Chhatrapati Sambhajinagar", "state": "Maharashtra", "lat": 19.8762, "lon": 75.3433},
    {"city": "Amravati", "district": "Amravati", "state": "Maharashtra", "lat": 20.9374, "lon": 77.7796},
    {"city": "Jalgaon", "district": "Jalgaon", "state": "Maharashtra", "lat": 21.0077, "lon": 75.5626},
    {"city": "Indore", "district": "Indore", "state": "Madhya Pradesh", "lat": 22.7196, "lon": 75.8577},
    {"city": "Bhopal", "district": "Bhopal", "state": "Madhya Pradesh", "lat": 23.2599, "lon": 77.4126},
    {"city": "Ujjain", "district": "Ujjain", "state": "Madhya Pradesh", "lat": 23.1765, "lon": 75.7885},
    {"city": "Jabalpur", "district": "Jabalpur", "state": "Madhya Pradesh", "lat": 23.1815, "lon": 79.9864},
    {"city": "Gwalior", "district": "Gwalior", "state": "Madhya Pradesh", "lat": 26.2183, "lon": 78.1828},
    {"city": "Jaipur", "district": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lon": 75.7873},
    {"city": "Jodhpur", "district": "Jodhpur", "state": "Rajasthan", "lat": 26.2389, "lon": 73.0243},
    {"city": "Kota", "district": "Kota", "state": "Rajasthan", "lat": 25.2138, "lon": 75.8648},
    {"city": "Bikaner", "district": "Bikaner", "state": "Rajasthan", "lat": 28.0229, "lon": 73.3119},
    {"city": "Sriganganagar", "district": "Ganganagar", "state": "Rajasthan", "lat": 29.9038, "lon": 73.8772},
    {"city": "Ludhiana", "district": "Ludhiana", "state": "Punjab", "lat": 30.9010, "lon": 75.8573},
    {"city": "Amritsar", "district": "Amritsar", "state": "Punjab", "lat": 31.6340, "lon": 74.8723},
    {"city": "Jalandhar", "district": "Jalandhar", "state": "Punjab", "lat": 31.3260, "lon": 75.5762},
    {"city": "Bathinda", "district": "Bathinda", "state": "Punjab", "lat": 30.2110, "lon": 74.9455},
    {"city": "Patiala", "district": "Patiala", "state": "Punjab", "lat": 30.3398, "lon": 76.3869},
    {"city": "Karnal", "district": "Karnal", "state": "Haryana", "lat": 29.6857, "lon": 76.9905},
    {"city": "Hisar", "district": "Hisar", "state": "Haryana", "lat": 29.1492, "lon": 75.7217},
    {"city": "Rohtak", "district": "Rohtak", "state": "Haryana", "lat": 28.8955, "lon": 76.6066},
    {"city": "Sirsa", "district": "Sirsa", "state": "Haryana", "lat": 29.5349, "lon": 75.0298},
    {"city": "Lucknow", "district": "Lucknow", "state": "Uttar Pradesh", "lat": 26.8467, "lon": 80.9462},
    {"city": "Varanasi", "district": "Varanasi", "state": "Uttar Pradesh", "lat": 25.3176, "lon": 82.9739},
    {"city": "Kanpur", "district": "Kanpur Nagar", "state": "Uttar Pradesh", "lat": 26.4499, "lon": 80.3319},
    {"city": "Agra", "district": "Agra", "state": "Uttar Pradesh", "lat": 27.1767, "lon": 78.0081},
    {"city": "Prayagraj", "district": "Prayagraj", "state": "Uttar Pradesh", "lat": 25.4358, "lon": 81.8463},
    {"city": "Gorakhpur", "district": "Gorakhpur", "state": "Uttar Pradesh", "lat": 26.7606, "lon": 83.3732},
    {"city": "Patna", "district": "Patna", "state": "Bihar", "lat": 25.5941, "lon": 85.1376},
    {"city": "Gaya", "district": "Gaya", "state": "Bihar", "lat": 24.7914, "lon": 85.0002},
    {"city": "Muzaffarpur", "district": "Muzaffarpur", "state": "Bihar", "lat": 26.1209, "lon": 85.3647},
    {"city": "Raipur", "district": "Raipur", "state": "Chhattisgarh", "lat": 21.2514, "lon": 81.6296},
    {"city": "Ranchi", "district": "Ranchi", "state": "Jharkhand", "lat": 23.3441, "lon": 85.3096},
    {"city": "Bhubaneswar", "district": "Khurda", "state": "Odisha", "lat": 20.2961, "lon": 85.8245},
    {"city": "Sambalpur", "district": "Sambalpur", "state": "Odisha", "lat": 21.4669, "lon": 83.9812},
    {"city": "Hyderabad", "district": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lon": 78.4867},
    {"city": "Warangal", "district": "Warangal", "state": "Telangana", "lat": 17.9689, "lon": 79.5941},
    {"city": "Bengaluru", "district": "Bengaluru Urban", "state": "Karnataka", "lat": 12.9716, "lon": 77.5946},
    {"city": "Mysuru", "district": "Mysuru", "state": "Karnataka", "lat": 12.2958, "lon": 76.6394},
    {"city": "Hubballi", "district": "Dharwad", "state": "Karnataka", "lat": 15.3647, "lon": 75.1240},
    {"city": "Belagavi", "district": "Belagavi", "state": "Karnataka", "lat": 15.8497, "lon": 74.4977},
    {"city": "Vijayawada", "district": "NTR", "state": "Andhra Pradesh", "lat": 16.5062, "lon": 80.6480},
    {"city": "Visakhapatnam", "district": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lon": 83.2185},
    {"city": "Guntur", "district": "Guntur", "state": "Andhra Pradesh", "lat": 16.3067, "lon": 80.4365},
    {"city": "Chennai", "district": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lon": 80.2707},
    {"city": "Coimbatore", "district": "Coimbatore", "state": "Tamil Nadu", "lat": 11.0168, "lon": 76.9558},
    {"city": "Madurai", "district": "Madurai", "state": "Tamil Nadu", "lat": 9.9252, "lon": 78.1198},
    {"city": "Salem", "district": "Salem", "state": "Tamil Nadu", "lat": 11.6643, "lon": 78.1460},
    {"city": "Kochi", "district": "Ernakulam", "state": "Kerala", "lat": 9.9312, "lon": 76.2673},
    {"city": "Thiruvananthapuram", "district": "Thiruvananthapuram", "state": "Kerala", "lat": 8.5241, "lon": 76.9366},
    {"city": "Kolkata", "district": "Kolkata", "state": "West Bengal", "lat": 22.5726, "lon": 88.3639},
    {"city": "Siliguri", "district": "Darjeeling", "state": "West Bengal", "lat": 26.7271, "lon": 88.3953},
]

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
    
    try:
        limit = int(request.query_params.get('limit', 5))
    except ValueError:
        limit = 5
    limit = max(1, min(10, limit))
    
    cache_key = f"{q.lower()}:{limit}"
    if cache_key in _GEOCODE_CACHE:
        return Response(_GEOCODE_CACHE[cache_key])
    
    q_lower = q.lower()
    combined_candidates = []
    seen_keys = set()

    # 1. Match local curated agricultural hubs (instant, deduplicated, zero-latency)
    for c in INDIAN_AGRI_CITIES:
        c_name = c["city"].lower()
        if c_name.startswith(q_lower) or q_lower in c_name:
            k = f"{c['city'].lower()}:{c['state'].lower()}"
            if k not in seen_keys:
                seen_keys.add(k)
                has_distinct_district = c.get('district') and c['district'].lower() != c['city'].lower()
                clean_addr = f"{c['city']}, {c['district']}, {c['state']}, India" if has_distinct_district else f"{c['city']}, {c['state']}, India"
                combined_candidates.append({
                    'query': q,
                    'address': clean_addr,
                    'display_name': clean_addr,
                    'city': c['city'],
                    'district': c.get('district', ''),
                    'state': c['state'],
                    'lat': c['lat'],
                    'lon': c['lon'],
                    'place_id': f"local_{c['city'].lower()}",
                    '_score': 0 if c_name == q_lower else 1 if c_name.startswith(q_lower) else 2
                })

    # 2. Query Nominatim restricted to India (&countrycodes=in)
    headers = {
        'User-Agent': 'KrishiMitra-App/1.0 (agronomy-dev@krishimitra.org)',
        'Accept': 'application/json'
    }
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(q)}&addressdetails=1&countrycodes=in&limit=8"
    
    try:
        resp = requests.get(url, headers=headers, timeout=(3.0, 8.0))
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    addr = item.get('address', {})
                    city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('suburb') or addr.get('county') or ''
                    state = addr.get('state') or ''
                    district = addr.get('state_district') or addr.get('county') or ''
                    disp = item.get('display_name') or q

                    if not city:
                        city = disp.split(',')[0].strip()

                    try:
                        lat = float(item.get('lat'))
                        lon = float(item.get('lon'))
                    except (TypeError, ValueError):
                        continue

                    k = f"{city.lower()}:{state.lower()}"
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)

                    parts = [city, district, state, "India"]
                    clean_parts = []
                    for p in parts:
                        if p and p not in clean_parts:
                            clean_parts.append(p)
                    clean_addr = ', '.join(clean_parts)

                    c_lower = city.lower()
                    score = 0 if c_lower == q_lower else 1 if c_lower.startswith(q_lower) else 2

                    combined_candidates.append({
                        'query': q,
                        'address': clean_addr,
                        'display_name': clean_addr,
                        'city': city,
                        'district': district,
                        'state': state,
                        'lat': lat,
                        'lon': lon,
                        'place_id': item.get('place_id'),
                        'raw_address': addr,
                        '_score': score
                    })
    except Exception:
        # Nominatim may be slow or offline; local curated hub matches provide robust fallback
        pass

    # Sort candidates: exact prefix matches first, then shortest names
    combined_candidates.sort(key=lambda x: (x.get('_score', 3), len(x.get('city', ''))))

    # Strip internal score before returning
    for c in combined_candidates:
        c.pop('_score', None)

    results = combined_candidates[:limit]

    # 3. Safe Hierarchical Geocoding (approximate regional/district fallback)
    # If no exact city match was found, inspect comma-separated or tokenized sub-parts
    # (e.g. "Navrangpura, Gujarat" -> tokens: "Navrangpura", "Gujarat").
    # Never substitute an unrelated location; only match if a valid district or state is explicitly present.
    if not results:
        raw_tokens = [t.strip().lower() for t in q.split(',') if t.strip()]
        hierarchical_match = None
        match_level = None

        # 3a. Check if any individual token matches a known city or district
        for tok in raw_tokens:
            for c in INDIAN_AGRI_CITIES:
                if c["city"].lower() == tok or (c.get("district") and c["district"].lower() == tok):
                    hierarchical_match = c
                    match_level = "district_hub"
                    break
            if hierarchical_match:
                break

        # 3b. If still no match, check if any token matches an Indian state
        if not hierarchical_match:
            primary_state_hubs = {
                "gujarat": "ahmedabad", "maharashtra": "pune", "punjab": "ludhiana",
                "rajasthan": "jaipur", "karnataka": "bengaluru", "tamil nadu": "chennai",
                "uttar pradesh": "lucknow", "madhya pradesh": "bhopal", "haryana": "karnal",
                "west bengal": "kolkata", "bihar": "patna", "telangana": "hyderabad",
                "andhra pradesh": "vijayawada", "odisha": "bhubaneswar", "kerala": "kochi",
                "chhattisgarh": "raipur", "jharkhand": "ranchi"
            }
            for tok in raw_tokens:
                preferred_city = primary_state_hubs.get(tok)
                if preferred_city:
                    for c in INDIAN_AGRI_CITIES:
                        if c["city"].lower() == preferred_city:
                            hierarchical_match = c
                            match_level = "regional_hub"
                            break
                if hierarchical_match:
                    break
                # Fallback to any city matching the state
                for c in INDIAN_AGRI_CITIES:
                    if c["state"].lower() == tok:
                        hierarchical_match = c
                        match_level = "regional_hub"
                        break
                if hierarchical_match:
                    break

        if hierarchical_match:
            c = hierarchical_match
            disp = f"{c['city']}, {c['state']} (Regional Center for {q})"
            addr = f"{c['city']}, {c['district']}, {c['state']}, India" if c.get('district') else f"{c['city']}, {c['state']}, India"
            approx_item = {
                'query': q,
                'address': addr,
                'display_name': disp,
                'city': c['city'],
                'district': c.get('district', ''),
                'state': c['state'],
                'lat': c['lat'],
                'lon': c['lon'],
                'place_id': f"regional_{c['city'].lower()}",
                'is_approximate': True,
                'match_level': match_level,
                'original_query': q,
            }
            results = [approx_item]

    if not results:
        return Response({'error': f'No locations found for "{q}"', 'results': []}, status=404)

    first = results[0]
    out = {
        'query': q,
        'address': first['address'],
        'display_name': first['display_name'],
        'city': first['city'],
        'district': first['district'],
        'state': first['state'],
        'lat': first['lat'],
        'lon': first['lon'],
        'is_approximate': first.get('is_approximate', False),
        'match_level': first.get('match_level', 'exact'),
        'original_query': first.get('original_query', q),
        'results': results
    }
    _GEOCODE_CACHE[cache_key] = out
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
    except Exception as e:
        return Response({'error': f'Reverse geocoding request failed: {str(e)}'}, status=500)




