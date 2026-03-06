from django.contrib import admin
from django.urls import path, include
from fcm_django.api.rest_framework import FCMDeviceViewSet
from rest_framework import routers
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic import TemplateView

router = routers.DefaultRouter()
router.register(r'devices', FCMDeviceViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('api/', include([
        path('stocks/', include('stocks.urls')),
        path('movies/', include('movies.urls')),
        path('auth/', include('dj_rest_auth.urls')),
        path('auth/registration/', include('dj_rest_auth.registration.urls')),
    ])),
    path('password-reset/', include('django.contrib.auth.urls')),
    path('', include('core.urls')),
    path('movies/', include(('movies.urls', 'movies_web'), namespace='movies_web')),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt',
        content_type='text/plain'
    )),
]

urlpatterns += router.urls

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('__debug__/', include('debug_toolbar.urls')),
    ]