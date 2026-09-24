FROM golang:1.26.6-bookworm AS golang
FROM docker:29-cli AS dockercli
FROM node:24-bookworm
COPY --from=golang /usr/local/go /usr/local/go
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
ENV PATH=/usr/local/go/bin:/opt/bin:$PATH GOTOOLCHAIN=local
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv python3-pip libpq-dev libmagic1 postgresql-client rsync jq \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pnpm@10.33.0 \
    && GOBIN=/opt/bin go install -tags postgres github.com/golang-migrate/migrate/v4/cmd/migrate@v4.18.3
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc poppler-utils unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
