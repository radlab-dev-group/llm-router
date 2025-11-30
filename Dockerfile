FROM python:3.13.9-slim-trixie

ARG version=prod
ARG GIT_REF=main
ENV ENABLE_LLM_API=true
ENV ENABLE_LLM_WEB=false

LABEL authors="RadLab"
LABEL version=$version

ENV LLM_PROXY_API_MINIMUM=1

RUN apt-get update && apt-get upgrade -y && apt-get install -y supervisor htop curl htop jq git vim cron gettext && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/

RUN git clone https://github.com/radlab-dev-group/llm-router.git && \
    cd /srv/llm-router && \
    git checkout ${GIT_REF}

WORKDIR /srv/llm-router

RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir .
RUN pip3 install --no-cache-dir .[api]

COPY entrypoint.sh entrypoint.sh
RUN chmod +x run-rest-api.sh && chmod +x entrypoint.sh

ENTRYPOINT ["/srv/llm-router/entrypoint.sh"]