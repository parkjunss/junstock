# users/admin.py

from django.contrib import admin
from .models import BlockedEmails, BlockedDomains

@admin.register(BlockedEmails)
class BlockedEmailsAdmin(admin.ModelAdmin):
    list_display = ('email', 'created')
    search_fields = ('email',)

@admin.register(BlockedDomains)
class BlockedDomainsAdmin(admin.ModelAdmin):
    list_display = ('domain', 'created')
    search_fields = ('domain',)