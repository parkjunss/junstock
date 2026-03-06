from django.db import models

# Create your models here.
class BlockedEmails(models.Model):
    email = models.EmailField(unique=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class BlockedDomains(models.Model):
    """특정 도메인 전체를 차단합니다."""
    domain = models.CharField(max_length=255, unique=True, help_text="차단할 도메인을 입력하세요 (예: example.com).")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "차단된 도메인"
        verbose_name_plural = "차단된 도메인 목록"

    def __str__(self):
        return self.domain