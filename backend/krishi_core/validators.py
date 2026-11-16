import re
from django.core.exceptions import ValidationError
from django.core.validators import validate_email as django_validate_email

# Email syntax regex: requires local part, @, domain with at least one dot, and a valid TLD of at least 2 alpha characters
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$')


def validate_email_syntax(email: str) -> str:
    """
    Validates that the email address is syntactically well-formed,
    includes a proper domain with a top-level domain (TLD), and
    satisfies Django's standard email validation rules.
    Raises ValidationError if invalid. Returns cleaned email.
    """
    if not email or not isinstance(email, str):
        raise ValidationError("Email address is required.")

    cleaned = email.strip().lower()
    if len(cleaned) > 254:
        raise ValidationError("Email address cannot exceed 254 characters.")

    if not EMAIL_REGEX.match(cleaned):
        raise ValidationError("Please enter a valid email address (e.g., name@example.com).")

    try:
        django_validate_email(cleaned)
    except ValidationError:
        raise ValidationError("Please enter a valid email address (e.g., name@example.com).")

    return cleaned


class ComplexityPasswordValidator:
    """
    Password complexity validator requiring:
    - Between 8 and 128 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one digit (0-9)
    - At least one special character
    - Rejects easily guessable common patterns
    """
    SPECIAL_CHAR_REGEX = re.compile(r'[!@#$%^&*(),.?":{}|<>\-_+=\[\]\\/\'~`;]')
    COMMON_WORDS = {
        'password', 'password123', 'admin', 'admin123', 'qwerty', '123456',
        '12345678', 'welcome', 'welcome123', 'letmein', 'krishimitra'
    }

    def validate(self, password, user=None):
        if not password or len(password) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        if len(password) > 128:
            raise ValidationError("Password cannot exceed 128 characters.")
        if not re.search(r'[A-Z]', password):
            raise ValidationError("Password must contain at least one uppercase letter (A-Z).")
        if not re.search(r'[a-z]', password):
            raise ValidationError("Password must contain at least one lowercase letter (a-z).")
        if not re.search(r'[0-9]', password):
            raise ValidationError("Password must contain at least one digit (0-9).")
        if not self.SPECIAL_CHAR_REGEX.search(password):
            raise ValidationError("Password must contain at least one special character (e.g., !@#$%^&*).")

        lower = password.lower()
        base = re.sub(r'[\d!@#$%^&*(),.?":{}|<>\-_+=\[\]\\/\'~`;]+$', '', lower)
        if lower in self.COMMON_WORDS or base in self.COMMON_WORDS:
            raise ValidationError("Password is too common or easily guessable. Please choose a more unique password.")

    def get_help_text(self):
        return (
            "Your password must be between 8 and 128 characters long and contain at least one uppercase letter, "
            "one lowercase letter, one digit, and one special character."
        )
