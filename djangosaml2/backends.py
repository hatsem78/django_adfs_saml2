# Copyright (C) 2010-2012 Yaco Sistemas (http://www.yaco.es)
# Copyright (C) 2009 Lorenzo Gil Sanchez <lorenzo.gil.sanchez@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#            http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from typing import Any, Optional, Tuple
import warnings
from .signals import post_authenticated

from django.apps import apps
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import (ImproperlyConfigured,
                                    MultipleObjectsReturned)

from .signals import post_authenticated
from django.contrib.auth import get_user_model

logger = logging.getLogger('djangosaml2')


def set_attribute(obj: Any, attr: str, new_value: Any) -> bool:
    """ Set an attribute of an object to a specific value, if it wasn't that already.
        Return True if the attribute was changed and False otherwise.
    """
    if not hasattr(obj, attr):
        setattr(obj, attr, new_value)
        return True
    if new_value != getattr(obj, attr):
        setattr(obj, attr, new_value)
        return True
    return False


class AdfsSaml2BaseBackend(ModelBackend):

    def create_user(self, claims):
        """
        Create the user if it doesn't exist yet

        Args:
            claims (dict): claims from the access token

        Returns:
            django.contrib.auth.models.User: A Django user
        """
        # Create the user
        username_claim = settings.USERNAME_CLAIM
        usermodel = get_user_model()
        userdata = {usermodel.USERNAME_FIELD: claims[username_claim]}

        try:
            user = usermodel.objects.get(**userdata)
        except usermodel.DoesNotExist:
            if settings.CREATE_NEW_USERS:
                user = usermodel.objects.create(**userdata)
                logger.debug("User '%s' has been created.", claims[username_claim])
            else:
                logger.debug("User '%s' doesn't exist and creating users is disabled.", claims[username_claim])
                raise PermissionDenied
        if not user.password:
            user.set_unusable_password()
        return user

    def update_user_attributes(self, user, claims):
        """
        Updates user attributes based on the CLAIM_MAPPING setting.

        Args:
            user (django.contrib.auth.models.User): User model instance
            claims (dict): claims from the access token
        """
        

        #required_fields = [field.name for field in user._meta.fields if field.blank is False]
        required_fields = ['email', 'name', 'last_name']
        logger.debug("claims '%s'.", claims)
        logger.debug("user._meta.fields '%s'.", user._meta.fields)
        logger.debug("mappings '%s'.", required_fields)
        for field, claim in settings.CLAIM_MAPPING.items():
            if hasattr(user, field):
                if claim in claims:
                    setattr(user, field, claims[claim])
                    logger.debug("Attribute '%s' for user '%s' was set to '%s'.", field, user, claims[claim])
                else:
                    if field in required_fields:
                        msg = "Claim not found in access token: '{}'. Check ADFS claims mapping."
                        raise ImproperlyConfigured(msg.format(claim))
                    else:
                        logger.warning("Claim '%s' for user field '%s' was not found in "
                                       "the access token for user '%s'. "
                                       "Field is not required and will be left empty", claim, field, user)
            else:
                msg = "User model has no field named '{}'. Check ADFS claims mapping."
                raise ImproperlyConfigured(msg.format(field))


class Saml2Backend(AdfsSaml2BaseBackend):

    # ############################################
    # Internal logic, not meant to be overwritten
    # ############################################

    def authenticate(self, request, session_info=None, attribute_mapping=None, create_unknown_user=True, **kwargs):
        
        logger.debug('attributes: %s', attribute_mapping)
        user = self.create_user(attribute_mapping)
        self.update_user_attributes(user, attribute_mapping)
        # self.update_user_attributes(user, attribute_mapping)
        # self.update_user_groups(user, claims)
        # self.update_user_flags(user, claims)

        logger.debug("User %s authenticated via SSO.", user)
        logger.debug('Sending the post_authenticated signal')
        
        post_authenticated.send_robust(
            sender=self,
            user=user,
            attribute_mapping=attribute_mapping,
            session_info=session_info
        )

        user.full_clean()
        user.save()
        return user


def get_saml_user_model():
    warnings.warn("_set_attribute() is deprecated, look at the Saml2Backend on how to subclass it", DeprecationWarning)
    return Saml2Backend()._user_model
