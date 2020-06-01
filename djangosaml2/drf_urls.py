"""
These URL patterns are used to override the default Django Rest Framework login page.

It's a bit of a hack, but DRF doesn't support overriding the login URL.
"""
from django.conf.urls import url

from djangosaml2 import views

app_name = "rest_framework"

urlpatterns = [
    url(r'^login$', views.login, name='login'),
]
