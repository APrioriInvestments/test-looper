# The GIT class provides methods for interacting
# with GIT, github and related utilities

import requests
from requests.auth import HTTPBasicAuth


class GIT:
    def __init__(self, user=None, token=None):
        self.user = user
        self.token = token
        self.authenticated = False


    def authenticate(self):
        "I test credentials and set self.authenticated accordingly"
        return false
