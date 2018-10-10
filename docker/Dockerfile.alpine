FROM alpine:3.8
MAINTAINER Oz Tiram <oz.tiram@gmail.com>

RUN apk update

RUN apk add alpine-sdk python3-dev linux-headers py3-cryptography libffi-dev

COPY requirements.txt requirements_dev.txt ./

RUN pip3 install -r requirements.txt
RUN pip3 install -r requirements_dev.txt
RUN rm requirements.txt requirements_dev.txt
