FROM python:3.13.9-slim-trixie

ARG version=prod
ENV ENABLE_LLM_API=true
ENV ENABLE_LLM_WEB=false

LABEL authors="RadLab"
LABEL version=$version

ENV LLM_ROUTER_MINIMUM=1

RUN apt-get update && apt-get upgrade -y && apt-get install -y supervisor htop curl htop jq git vim cron gettext && rm -rf /var/lib/apt/lists/*

COPY . /srv/llm-router
WORKDIR /srv/llm-router


ARG USER_ID=5000
ARG GROUP_ID=5000
RUN groupadd -g ${GROUP_ID} llm-router && \
    useradd -m -u ${USER_ID} -g llm-router -d /home/llm-router llm-router && \
    chown -R llm-router:llm-router /srv

RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir .
RUN pip3 install --no-cache-dir .[api]

USER llm-router
WORKDIR /srv/llm-router

RUN cp docker/entrypoint.sh . && chmod +x run-rest-api.sh && chmod +x entrypoint.sh

ENTRYPOINT ["/srv/llm-router/entrypoint.sh"]