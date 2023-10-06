# this is the Dockerfile we use to build a container for TestLooper.
# It builds all the necessary dependenices, then we bind-mount TL itself into the container.
FROM ubuntu:22.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python-is-python3  python-dev-is-python3  \
        python3 python3-dbg  python3-pip  python3-venv \
        net-tools  redis  git libtcmalloc-minimal4 \
        nginx  libssl-dev \
        docker.io npm
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



# Install python dependencies
COPY requirements.txt /requirements.txt
COPY run_tl.sh /run_tl.sh
RUN pip install --upgrade pip
RUN pip install werkzeug==2.3.7 # temp
RUN pip install -r /requirements.txt
COPY install_odb.py /install_odb.py
RUN python install_odb.py
RUN pip install /object_database
