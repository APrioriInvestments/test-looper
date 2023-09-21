# this is the Dockerfile we use to build a container for TestLooper
FROM ubuntu:22.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python-is-python3  python-dev-is-python3  \
        python3 python3-dbg  python3-pip  python3-venv \
        net-tools  redis  git libtcmalloc-minimal4 \
        nginx  libssl-dev \
        docker.io

# configure nginx
RUN rm /etc/nginx/sites-enabled/default
COPY  aws-nginx.conf  /etc/nginx/sites-available/aws-nginx.conf
RUN ln -s /etc/nginx/sites-available/aws-nginx.conf /etc/nginx/sites-enabled/aws-nginx.conf

# enable TCMALLOC by default
ENV LD_PRELOAD=/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4

RUN ls -l /lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4

# tcmalloc is version 2.9 in this ubuntu, which
# disables 'agressive decommit' by default. We turn it
# back on since we'd like to release memory back to the OS
# faster than we seem to without it
ENV TCMALLOC_AGGRESSIVE_DECOMMIT=t


ENV OPENBLAS_NUM_THREADS=1

# ensure that python processes have stable hashes. Otherwise, containers that use python
# hashes, like sets, will not have a stable ordering for the same data.
ENV PYTHONHASHSEED=0

ARG TL_BRANCH='will-qol'

# 21.2.3: last known pip version to correctly work for us
# 22.2.2: last version of pip tried that didn't work
RUN python -m pip install pip==21.2.3 pip-tools==6.8.0

# Install python requirements
COPY requirements.lock  /requirements.lock

RUN python -m pip install --requirement /requirements.lock

# Install typed_python and object_database
# note we have to remove the pyproject.toml because the whole setuptools thing is a POS
RUN mkdir /typed_python \
      && cd /typed_python \
      && git clone https://github.com/aprioriinvestments/typed_python.git . \
      && git checkout 55854ea8b926f455a03cdac9562f8b9ed618d441 \
      && rm /typed_python/pyproject.toml \
      && python -m pip install --no-deps --no-index --editable . \
      && make lib


RUN mkdir /object_database \
      && cd /object_database \
      && git clone https://github.com/aprioriinvestments/object_database.git . \
      && git checkout b4b1c973f7c671d1680c641b707a7c0dc6dcd17f \
      && make node-install \
      && make build-js \
      && rm /object_database/pyproject.toml \
      && python -m pip install --no-deps --no-index --editable . \
      && make lib


RUN mkdir /testlooper \
      && cd /testlooper \
      && git clone https://github.com/aprioriinvestments/test-looper.git . \
      && git checkout $TL_BRANCH \
      && echo "h" \
      && python -m pip install --no-deps .


# Define the docker entrypoint
COPY docker_entrypoint.sh  /docker_entrypoint.sh

COPY config.yaml  /config.yaml

RUN chmod +x /docker_entrypoint.sh

ENTRYPOINT ["/docker_entrypoint.sh"]
