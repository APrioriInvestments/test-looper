# The GIT class provides methods for interacting
# with GIT, github and related utilities

import sys
import requests


class GIT:
    def __init__(self, user=None, token=None, require_auth=False):
        self.user = user
        self.token = token
        self.session = requests.Session()
        self.require_auth = require_auth
        self.authenticated = False

    def authenticate(self):
        "I test credentials and set self.authenticated accordingly"
        self.session.auth = (self.user, self.token)
        # check the credentials are valid
        response = self.session.get('https://api.github.com/users/%s' % self.user)
        if(response.headers['X-RateLimit-Limit'] == '5000'):
            self.authenticated = True
        elif(self.require_auth):
            sys.exit("invalid github credentials")
        else:
            self.authenticated = False
