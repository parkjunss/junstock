from .models import BlockedEmails

def email_check(email):
    return BlockedEmails.objects.filter(email=email).exists()