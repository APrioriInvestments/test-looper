#! /usr/bin/env bash

OWN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

DOCKER_TAG=${1:-"latest"}  # 1st arg or 'latest'

docker build "$OWN_DIR/build-context/" \
    --tag "dockerhub.aws.aprioriinvestments.com:5000/testlooper:${DOCKER_TAG}"
