#!/usr/bin/env bash

pytest -m "not knownfailure" --ignore=tests/_template_repo tests