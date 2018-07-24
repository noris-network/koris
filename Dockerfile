FROM alpine:3.5

RUN apk update

RUN apk add alpine-sdk python3-dev linux-headers py-cryptography

COPY requirements.txt requirements_dev.txt ./

RUN pip3 install -r requirements.txt
RUN pip3 install -r requirements_dev.txt
RUN rm requirements.txt requirements_dev.txt
