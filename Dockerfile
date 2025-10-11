FROM python:3.13.7-slim-trixie

ARG version=prod

LABEL authors="RadLab"
LABEL version=$version

# If used build.sh ENV is overwrited by default or set value
ENV branch=main

ENV LLM_PROXY_API_MINIMUM=1

RUN apt-get update && apt-get install -y supervisor htop curl htop jq git vim cron && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/

RUN git clone -b ${branch} https://github.com/radlab-dev-group/llm-proxy-api.git && \
    cd /srv/llm-proxy-api  && \
    cat .git/HEAD > .version && git log -1 | head -1 >> .version && \
    rm -rf .git .gitignore

WORKDIR /srv/llm-proxy-api

RUN pip3 install -r requirements.txt

RUN pip3 install git+https://github.com/radlab-dev-group/ml-utils.git

RUN chmod +x run-rest-api.sh

CMD ["/srv/llm-router/run-rest-api.sh"]