#! /usr/bin/env bash

OWN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


DOCKER_TAG=${1:-"latest"}  # 1st arg or 'latest'


# TODO: get rid of --privileged and --network=host
docker run -it --rm --entrypoint bash \
    -p 8001:8001 --privileged \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume /tmp:/tmp \
    "dockerhub.aws.aprioriinvestments.com:5000/testlooper:${DOCKER_TAG}"
