# Copyright (C) 2010-2013 Yaco Sistemas (http://www.yaco.es)
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

import base64
from xml.etree import ElementTree
from xml.etree.ElementTree import XMLParser
import logging

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponseBadRequest  # 40x
from django.http import HttpResponseRedirect  # 30x
from django.http import HttpResponseServerError  # 50x
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django.utils.decorators import method_decorator

from saml2 import BINDING_HTTP_REDIRECT, BINDING_HTTP_POST
from saml2.client_base import LogoutError
from saml2.metadata import entity_descriptor
from saml2.ident import code, decode
from saml2.s_utils import UnsupportedBinding
from saml2.response import (
    StatusError, StatusAuthnFailed, SignatureError, StatusRequestDenied,
    UnsolicitedResponse, StatusNoAuthnContext,
)
from saml2.mdstore import SourceNotFound
from saml2.sigver import MissingKey
from saml2.samlp import AuthnRequest
from saml2.validate import ResponseLifetimeExceed, ToEarly
from saml2.xmldsig import (  # support for SHA1 is required by spec
    SIG_RSA_SHA1, SIG_RSA_SHA256)

from .cache import IdentityCache, OutstandingQueriesCache, StateCache
from .conf import get_config
from .exceptions import IdPConfigurationMissing
from .overrides import Saml2Client
from .utils import (available_idps, fail_acs_response, get_custom_setting,
                    get_idp_sso_supported_bindings, get_location,
                    validate_referral_url)

try:
    from django.contrib.auth.views import LogoutView
    django_logout = LogoutView.as_view()
except ImportError:
    from django.contrib.auth.views import logout as django_logout



logger = logging.getLogger('djangosaml2')


def _set_subject_id(session, subject_id):
    session['_saml2_subject_id'] = subject_id


def _get_subject_id(session):
    try:
        return session['_saml2_subject_id']
    except KeyError:
        return None


def login(request,
          config_loader_path=None,
          wayf_template='djangosaml2/wayf.html',
          authorization_error_template='djangosaml2/auth_error.html',
          post_binding_form_template='djangosaml2/post_binding_form.html'):
    """SAML Authorization Request initiator
    This view initiates the SAML2 Authorization handshake
    using the pysaml2 library to create the AuthnRequest.
    It uses the SAML 2.0 Http Redirect protocol binding.
    * post_binding_form_template - path to a template containing HTML form with
    hidden input elements, used to send the SAML message data when HTTP POST
    binding is being used. You can customize this template to include custom
    branding and/or text explaining the automatic redirection process. Please
    see the example template in
    templates/djangosaml2/example_post_binding_form.html
    If set to None or nonexistent template, default form from the saml2 library
    will be rendered.
    """
    logger.debug('Login process started')

    came_from = request.GET.get('next', settings.LOGIN_REDIRECT_URL)
    if not came_from:
        logger.warning('The next parameter exists but is empty')
        came_from = settings.LOGIN_REDIRECT_URL
    came_from = validate_referral_url(request, came_from)

    # if the user is already authenticated that maybe because of two reasons:
    # A) He has this URL in two browser windows and in the other one he
    #    has already initiated the authenticated session.
    # B) He comes from a view that (incorrectly) send him here because
    #    he does not have enough permissions. That view should have shown
    #    an authorization error in the first place.
    # We can only make one thing here and that is configurable with the
    # SAML_IGNORE_AUTHENTICATED_USERS_ON_LOGIN setting. If that setting
    # is True (default value) we will redirect him to the came_from view.
    # Otherwise, we will show an (configurable) authorization error.
    if request.user.is_authenticated:
        redirect_authenticated_user = getattr(settings, 'SAML_IGNORE_AUTHENTICATED_USERS_ON_LOGIN', True)
        if redirect_authenticated_user:
            return HttpResponseRedirect(came_from)
        else:
            logger.debug('User is already logged in')
            return render(request, authorization_error_template, {
                    'came_from': came_from,
                    })

    selected_idp = request.GET.get('idp', None)
    try:
        conf = get_config(config_loader_path, request)
    except SourceNotFound as excp:
        msg = ('Error, IdP EntityID was not found '
               'in metadata: {}')
        logger.exception(msg.format(excp))
        return HttpResponse(msg.format(('Please contact '
                                        'technical support.')),
                            status=500)

    kwargs = {}
    # pysaml needs a string otherwise: "cannot serialize True (type bool)"
    if getattr(conf, '_sp_force_authn', False):
        kwargs['force_authn'] = "true"
    if getattr(conf, '_sp_allow_create', False):
        kwargs['allow_create'] = "true"

    # is a embedded wayf needed?
    idps = available_idps(conf)
    if selected_idp is None and len(idps) > 1:
        logger.debug('A discovery process is needed')
        return render(request, wayf_template, {
                'available_idps': idps.items(),
                'came_from': came_from,
                })
    else:
        # is the first one, otherwise next logger message will print None
        if not idps:
            raise IdPConfigurationMissing(('IdP configuration is missing or '
                                           'its metadata is expired.'))
        if selected_idp is None:
            selected_idp = list(idps.keys())[0]
    
    # choose a binding to try first
    sign_requests = getattr(conf, '_sp_authn_requests_signed', False)
    binding = BINDING_HTTP_POST if sign_requests else BINDING_HTTP_REDIRECT
    logger.debug('Trying binding %s for IDP %s', binding, selected_idp)

    # ensure our selected binding is supported by the IDP
    supported_bindings = get_idp_sso_supported_bindings(selected_idp, config=conf)
    if binding not in supported_bindings:
        logger.debug('Binding %s not in IDP %s supported bindings: %s',
                     binding, selected_idp, supported_bindings)
        if binding == BINDING_HTTP_POST:
            logger.warning('IDP %s does not support %s,  trying %s',
                           selected_idp, binding, BINDING_HTTP_REDIRECT)
            binding = BINDING_HTTP_REDIRECT
        else:
            logger.warning('IDP %s does not support %s,  trying %s',
                           selected_idp, binding, BINDING_HTTP_POST)
            binding = BINDING_HTTP_POST
        # if switched binding still not supported, give up
        if binding not in supported_bindings:
            raise UnsupportedBinding('IDP %s does not support %s or %s',
                                     selected_idp, BINDING_HTTP_POST, BINDING_HTTP_REDIRECT)

    client = Saml2Client(conf)
    http_response = None

    logger.debug('Redirecting user to the IdP via %s binding.', binding)
    if binding == BINDING_HTTP_REDIRECT:
        try:
            nsprefix = get_namespace_prefixes()
            if sign_requests:
                # do not sign the xml itself, instead use the sigalg to
                # generate the signature as a URL param
                sig_alg_option_map = {'sha1': SIG_RSA_SHA1,
                                      'sha256': SIG_RSA_SHA256}
                sig_alg_option = getattr(conf, '_sp_authn_requests_signed_alg', 'sha1')
                kwargs["sigalg"] = sig_alg_option_map[sig_alg_option]
            session_id, result = client.prepare_for_authenticate(
                entityid=selected_idp, relay_state=came_from,
                binding=binding, sign=False, nsprefix=nsprefix,
                **kwargs)
        except TypeError as e:
            logger.error('Unable to know which IdP to use')
            return HttpResponse(str(e))
        else:
            http_response = HttpResponseRedirect(get_location(result))
    elif binding == BINDING_HTTP_POST:
        if post_binding_form_template:
            # get request XML to build our own html based on the template
            try:
                location = client.sso_location(selected_idp, binding)
            except TypeError as e:
                logger.error('Unable to know which IdP to use')
                return HttpResponse(str(e))
            session_id, request_xml = client.create_authn_request(
                location,
                binding=binding,
                **kwargs)
            try:
                if isinstance(request_xml, AuthnRequest):
                    # request_xml will be an instance of AuthnRequest if the message is not signed
                    request_xml = str(request_xml)
                saml_request = base64.b64encode(bytes(request_xml, 'UTF-8')).decode('utf-8')

                http_response = render(request, post_binding_form_template, {
                    'target_url': location,
                    'params': {
                        'SAMLRequest': saml_request,
                        'RelayState': came_from,
                        },
                    })
            except TemplateDoesNotExist:
                pass

        if not http_response:
            # use the html provided by pysaml2 if no template was specified or it didn't exist
            try:
                session_id, result = client.prepare_for_authenticate(
                    entityid=selected_idp, relay_state=came_from,
                    binding=binding)
            except TypeError as e:
                logger.error('Unable to know which IdP to use')
                return HttpResponse(str(e))
            else:
                http_response = HttpResponse(result['data'])
    else:
        raise UnsupportedBinding('Unsupported binding: %s', binding)

    # success, so save the session ID and return our response
    logger.debug('Saving the session_id in the OutstandingQueries cache')
    oq_cache = OutstandingQueriesCache(request.session)
    oq_cache.set(session_id, came_from)
    return http_response


class AssertionConsumerServiceView(View):
    """
    The IdP will send its response to this view, which will process it using pysaml2 and
    log the user in using whatever SAML authentication backend has been enabled in
    settings.py. The `djangosaml2.backends.Saml2Backend` can be used for this purpose,
    though some implementations may instead register their own subclasses of Saml2Backend.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        """
        This view needs to be CSRF exempt because it is called prior to login.
        """
        return super(AssertionConsumerServiceView, self).dispatch(request, *args, **kwargs)

    @method_decorator(csrf_exempt)
    def post(self,
             request,
             config_loader_path=None,
             attribute_mapping=None,
             create_unknown_user=None):
        """
        SAML Authorization Response endpoint
        """
        
        conf = get_config(config_loader_path, request)
        try:
            xmlstr = request.POST['SAMLResponse']
        except KeyError:
            logger.warning('Missing "SAMLResponse" parameter in POST data.')
            raise SuspiciousOperation
        
        

        decode_xml = base64.b64decode(xmlstr.encode('ascii'))

        parser_xml = ParserXmlCuctom(decode_xml)
        parser_xml.get_decode_xml()
        attribute_mapping = parser_xml.get_resul_property()

        client = Saml2Client(conf, identity_cache=IdentityCache(request.session))

        oq_cache = OutstandingQueriesCache(request.session)
        outstanding_queries = oq_cache.outstanding_queries()


        # authenticate the remote user
        
        logger.debug('Trying to authenticate the user. Session info: %s', '')
        user = auth.authenticate(request=request,
                                 session_info=xmlstr,
                                 attribute_mapping=attribute_mapping,
                                 create_unknown_user=create_unknown_user)
        if user is None:
            logger.warning("Could not authenticate user received in SAML Assertion. Session info: %s", session_info)
            return fail_acs_response(request, exception=PermissionDenied('No user could be authenticated.'))

        auth.login(self.request, user)
        
        _set_subject_id(request.session, attribute_mapping['session_index'])
        logger.debug("User %s authenticated via SSO.", user)

        # self.customize_session(user, session_info)
        return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)

    def build_relay_state(self):
        """
        The relay state is a URL used to redirect the user to the view where they came from.
        """
        default_relay_state = get_custom_setting('ACS_DEFAULT_REDIRECT_URL',
                                                 settings.LOGIN_REDIRECT_URL)
        relay_state = self.request.POST.get('RelayState', '/')
        relay_state = self.customize_relay_state(relay_state)
        if not relay_state:
            logger.warning('The RelayState parameter exists but is empty')
            relay_state = default_relay_state
        return relay_state

    def customize_session(self, user, session_info):
        """
        Subclasses can use this for customized functionality around user sessions.
        """

    def customize_relay_state(self, relay_state):
        """
        Subclasses may override this method to implement custom logic for relay state.
        """
        return relay_state

    def custom_redirect(self, user, relay_state, session_info):
        """
        Subclasses may override this method to implement custom logic for redirect.
        For example, some sites may require user registration if the user has not
        yet been provisioned.
        """
        return None

class MaxDepth:                     # The target object of the parser
    maxDepth = 0
    depth = 0
    tag_name = ''
    atribute_name = ''
    resul_property = {}
    def start(self, tag, attrib):   # Called for each opening tag.
        
        self.tag_name = tag

        if '{urn:oasis:names:tc:SAML:2.0:assertion}AuthnStatement' in tag:
            self.resul_property['session_index'] = attrib['SessionIndex']

        if '{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode' in tag:
            self.resul_property['status_code'] = attrib['Value']
            
        if len(attrib) >= 1 and 'Name' in attrib:
            self.resul_property[attrib['Name']] = ''
            self.atribute_name = attrib['Name']
        self.tag_name = attrib
    
    def end(self, tag): 
        # Called for each closing tag.
        self.depth -= 1
        
    def data(self, data):
        self.resul_property[self.atribute_name] = data
        
    def close(self):    # Called when all data has been parsed.
        return self.maxDepth
   

class ParserXmlCuctom(MaxDepth):
    
    def __init__(self, xml_encode):
        super().__init__()
        parser = XMLParser(target=MaxDepth())
        pepe = parser.feed(xml_encode)
        parser.close()
        print(self.resul_property)
        self.xml_encode = xml_encode
        
    def get_decode_xml(self):
        parser = XMLParser(target=MaxDepth())
        pepe = parser.feed(self.xml_encode)
        parser.close()
        
    def get_resul_property(self):
        return self.resul_property


@login_required
def echo_attributes(request,
                    config_loader_path=None,
                    template='djangosaml2/echo_attributes.html'):
    """Example view that echo the SAML attributes of an user"""
    state = StateCache(request.session)
    conf = get_config(config_loader_path, request)

    client = Saml2Client(conf, state_cache=state,
                         identity_cache=IdentityCache(request.session))
    subject_id = _get_subject_id(request.session)
    try:
        identity = client.users.get_identity(subject_id,
                                             check_not_on_or_after=False)
    except AttributeError:
        return HttpResponse("No active SAML identity found. Are you sure you have logged in via SAML?")

    return render(request, template, {'attributes': identity[0]})


@login_required
def logout(request, config_loader_path=None):
    """SAML Logout Request initiator
    This view initiates the SAML2 Logout request
    using the pysaml2 library to create the LogoutRequest.
    """
    state = StateCache(request.session)
    conf = get_config(config_loader_path, request)

    client = Saml2Client(conf, state_cache=state,
                         identity_cache=IdentityCache(request.session))
    subject_id = _get_subject_id(request.session)
    if subject_id is None:
        logger.warning(
            'The session does not contain the subject id for user %s',
            request.user)

    auth.logout(request)
    state.sync()
    return HttpResponseRedirect('/')


def logout_service(request, *args, **kwargs):
    return do_logout_service(request, request.GET, '/', *args, **kwargs)


@csrf_exempt
def logout_service_post(request, *args, **kwargs):
    return do_logout_service(request, request.POST, BINDING_HTTP_POST, *args, **kwargs)


def do_logout_service(request, data, binding, config_loader_path=None, next_page=None,
                   logout_error_template='djangosaml2/logout_error.html'):
    """SAML Logout Response endpoint
    The IdP will send the logout response to this view,
    which will process it with pysaml2 help and log the user
    out.
    Note that the IdP can request a logout even when
    we didn't initiate the process as a single logout
    request started by another SP.
    """
    logger.debug('Logout service started')
    conf = get_config(config_loader_path, request)

    state = StateCache(request.session)
    client = Saml2Client(conf, state_cache=state,
                         identity_cache=IdentityCache(request.session))

    if 'SAMLResponse' in data:  # we started the logout
        logger.debug('Receiving a logout response from the IdP')
        response = client.parse_logout_request_response(data['SAMLResponse'], binding)
        state.sync()
        return finish_logout(request, response, next_page=next_page)

    elif 'SAMLRequest' in data:  # logout started by the IdP
        logger.debug('Receiving a logout request from the IdP')
        subject_id = _get_subject_id(request.session)
        if subject_id is None:
            logger.warning(
                'The session does not contain the subject id for user %s. Performing local logout',
                request.user)
            auth.logout(request)
            return render(request, logout_error_template, status=403)
        else:
            http_info = client.handle_logout_request(
                data['SAMLRequest'],
                subject_id,
                binding,
                relay_state=data.get('RelayState', ''))
            state.sync()
            auth.logout(request)
            if (
                http_info.get('method', 'GET') == 'POST' and
                'data' in http_info and
                ('Content-type', 'text/html') in http_info.get('headers', [])
            ):
                # need to send back to the IDP a signed POST response with user session
                # return HTML form content to browser with auto form validation
                # to finally send request to the IDP
                return HttpResponse(http_info['data'])
            else:
                return HttpResponseRedirect(get_location(http_info))
    else:
        logger.error('No SAMLResponse or SAMLRequest parameter found')
        raise Http404('No SAMLResponse or SAMLRequest parameter found')


def finish_logout(request, response, next_page=None):
    if response and response.status_ok():
        if next_page is None and hasattr(settings, 'LOGOUT_REDIRECT_URL'):
            next_page = settings.LOGOUT_REDIRECT_URL
        logger.debug('Performing django logout with a next_page of %s',
                     next_page)
        return django_logout(request, next_page=next_page)
    else:
        logger.error('Unknown error during the logout')
        return render(request, "djangosaml2/logout_error.html", {})


def metadata(request, config_loader_path=None, valid_for=None):
    """Returns an XML with the SAML 2.0 metadata for this
    SP as configured in the settings.py file.
    """
    conf = get_config(config_loader_path, request)
    metadata = entity_descriptor(conf)
    return HttpResponse(content=str(metadata).encode('utf-8'),
                        content_type="text/xml; charset=utf8")


def get_namespace_prefixes():
    from saml2 import md, saml, samlp
    try:
        from saml2 import xmlenc
        from saml2 import xmldsig
    except ImportError:
        import xmlenc
        import xmldsig
    return {'saml': saml.NAMESPACE,
            'samlp': samlp.NAMESPACE,
            'md': md.NAMESPACE,
            'ds': xmldsig.NAMESPACE,
            'xenc': xmlenc.NAMESPACE}