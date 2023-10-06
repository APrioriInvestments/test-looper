import os
import subprocess

# extract the commit hash for ODB
with open("requirements.txt") as f:
    requirements = f.read().splitlines()


for line in requirements:
    if line.startswith("object_database"):
        _, odb_repo, odb_commit = line.split("@")
        odb_repo = odb_repo.strip().replace("git+", "")
        break
else:
    raise Exception("Could not find object_database in requirements.txt")

# clone the repo
subprocess.run(["git", "clone", odb_repo, "object_database"])
subprocess.run(["git", "checkout", odb_commit], cwd="object_database")

# npm install it
os.chdir(os.path.join("object_database", "object_database", "web", "content"))
subprocess.run(["npm", "install"])
subprocess.run(["npm", "run", "build"])
