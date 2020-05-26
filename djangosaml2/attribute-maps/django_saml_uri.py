X500ATTR_OID = 'urn:oid:2.5.4.'
PKCS_9 = 'urn:oid:1.2.840.113549.1.9.1.'
UCL_DIR_PILOT = 'urn:oid:0.9.2342.19200300.100.1.'

MAP = {
    'identifier': 'urn:oasis:names:tc:SAML:2.0:attrname-format:uri',
    'fro': {
        X500ATTR_OID+'3': 'firstname', # cn
        X500ATTR_OID+'4': 'lastname', # sn
        PKCS_9+'1': 'email',
        UCL_DIR_PILOT+'1': 'uid',
    },
    'to': {
        'firstname': X500ATTR_OID+'3',
        'lastname': X500ATTR_OID+'4',
        'email' : PKCS_9+'1',
        'uid': UCL_DIR_PILOT+'1',
    }
}
