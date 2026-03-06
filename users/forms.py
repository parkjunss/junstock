# users/forms.py

from django import forms
from django.core.exceptions import ValidationError
from allauth.account.forms import SignupForm, LoginForm
from .models import BlockedEmails, BlockedDomains

def email_is_blocked(email):
    """
    주어진 이메일이 차단되었는지 확인합니다.
    1. 정확히 일치하는 이메일 주소가 BlockedEmails에 있는지 확인합니다.
    2. 이메일의 도메인 부분이 BlockedDomains에 있는지 확인합니다.
    """
    # 1. 개별 이메일 차단 확인 (대소문자 무시)
    if BlockedEmails.objects.filter(email__iexact=email).exists():
        return True

    # 2. 도메인 차단 확인
    try:
        # 이메일 주소에서 '@'를 기준으로 도메인 부분만 추출
        domain = email.split('@')[1]
        if BlockedDomains.objects.filter(domain__iexact=domain).exists():
            return True
    except IndexError:
        # '@'가 없는 등 비정상적인 이메일 형식일 경우,
        # Django의 기본 EmailValidator가 처리하도록 그냥 넘어갑니다.
        pass

    return False

# CustomSignupForm과 CustomLoginForm은 이전과 동일하게 유지됩니다.
# email_is_blocked 함수만 수정하면 됩니다.

class CustomSignupForm(SignupForm):
    def clean_email(self):
        email = super().clean_email()
        if email_is_blocked(email):
            raise ValidationError("이 이메일 주소는 가입이 제한되었습니다.", code='blocked_email')
        return email

class CustomLoginForm(LoginForm):
    def clean_login(self):
        login = super().clean_login()
        if '@' in login:
            if email_is_blocked(login):
                raise ValidationError("이 이메일 주소는 로그인이 제한되었습니다.", code='blocked_email')
        return login