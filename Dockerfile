FROM python:3.10-slim
RUN apt-get update && \
    apt-get -y install git
# TODO: will need to setup git/ssh creds for private repos
WORKDIR /code
ENV REPODIR=$WORKDIR/repo
ENV PYTHONPATH=$WORKDIR
COPY setup.py setup.py 
COPY requirements.txt requirements.txt
RUN pip3 install -e .
EXPOSE 8000
COPY . .
# TODO: the repo to clone should be a CLI arg or something like that
RUN git clone https://github.com/APrioriInvestments/test-looper $REPODIR
RUN cd $REPODIR/test_looper
RUN git checkout daniel-starter
RUN echo 'hello'
ENV TEST_LOOPER_ROOT=$pwd
CMD ["python3", "/code/main.py"]