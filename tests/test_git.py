import json
from os import path
from test_looper.git import GIT


class TestGit:
    @classmethod
    def setup_class(self):
        "Check is git credentials are present"
        cred_file = "./.git_credentials"
        if path.isfile(cred_file):
            print("GIT credentials found")
            credentials = json.load(open(cred_file))
            self.GIT = GIT(user=credentials["user"],
                           token=credentials["token"])
            self.GIT.authenticate()
            if(self.GIT.authenticated):
                print("authenticated")
            else:
                print("crednetials invalid; continuing with lower rate limit")
        else:
            print("No credentials found; continuing")
            self.GIT()

    classmethod
    def teardown_class(self):
        return
