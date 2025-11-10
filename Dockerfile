FROM python:3.13.7-slim-trixie

ARG version=prod
ARG GIT_REF=main

LABEL authors="RadLab"
LABEL version=$version

ENV LLM_PROXY_API_MINIMUM=1

RUN apt-get update && apt-get upgrade -y && apt-get install -y supervisor htop curl htop jq git vim cron && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/


RUN git clone https://github.com/radlab-dev-group/llm-router.git && \
    cd /srv/llm-router && \
    git checkout ${GIT_REF} && \
    cat .git/HEAD > .version && git log -1 | head -1 >> .version && \
    rm -rf .git .gitignore

WORKDIR /srv/llm-router

RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

RUN pip3 install git+https://github.com/radlab-dev-group/ml-utils.git

COPY entrypoint.sh /srv/llm-router/entrypoint.sh

RUN chmod +x run-rest-api.sh && chmod +x entrypoint.sh

ENTRYPOINT ["/srv/llm-router/entrypoint.sh"]