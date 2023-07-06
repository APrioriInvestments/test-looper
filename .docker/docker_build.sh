#! /usr/bin/env bash
BUILD_ARG_VALUE=${1:-}  # Retrieve the value from the first script argument, if present
OWN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

DOCKER_TAG=${1:-"latest"}  # 1st arg or 'latest'

DOCKER_BUILD_CMD="docker build "$OWN_DIR/build-context/" \
    --tag "dockerhub.aws.aprioriinvestments.com:5000/testlooper:${DOCKER_TAG}""

if [ -n "$BUILD_ARG_VALUE" ]; then
    DOCKER_BUILD_CMD=$DOCKER_BUILD_CMD" --build-arg TL_BRANCH=$BUILD_ARG_VALUE"
fi

eval $DOCKER_BUILD_CMD
