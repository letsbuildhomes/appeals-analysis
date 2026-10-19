# Everything runs through uv; nothing touches the system Python or pip.
UV      ?= uv
RUN     := $(UV) run
PORT    ?= 8800
WORKERS ?= 24
MODEL   ?= fake
LIMIT   ?= 10
DOCKETS ?=
TAG     ?=
FRESH   ?=
RUN_ID  ?=
RELEASE ?=
SITE_HOST ?= 0.0.0.0
SITE_PORT ?= 8000
URL     ?= http://192.168.88.3:$(SITE_PORT)/appeals/mcp

.PHONY: help setup doctor test lint ingest crawl dockets graph run runs delete-runs prune-results serve score \
	release releases publish delete-releases site mcp-check

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

setup:           ## install dependencies and check tools
	$(UV) sync
	$(RUN) appeals doctor

doctor:          ## check Poppler, Tesseract and API keys
	$(RUN) appeals doctor

test:            ## run the tests
	$(RUN) pytest -q

lint:            ## check the code with ruff
	$(RUN) ruff check appeals tests scripts

ingest:          ## download new PDFs from known listings, extract text, assign dockets
	$(RUN) appeals ingest

crawl:           ## crawl the live listing, then ingest
	$(RUN) appeals ingest --crawl

dockets:         ## list recent dockets
	$(RUN) appeals dockets

graph:           ## build and validate the extraction graph, write data/graph.json
	$(RUN) appeals graph

run:             ## run the graph: make run MODEL=fake|live LIMIT=10 or DOCKETS="a,b" WORKERS=24 TAG=scratch [FRESH=1] [STOP=scan|<step>]
	$(RUN) appeals run --model $(MODEL) --workers $(WORKERS) $(if $(DOCKETS),--dockets "$(DOCKETS)",--limit $(LIMIT)) $(if $(TAG),--tag "$(TAG)") $(if $(FRESH),--fresh-steps) $(if $(STOP),--stop-after "$(STOP)")

runs:            ## list runs: make runs [TAG=scratch]
	$(RUN) appeals runs $(if $(TAG),--tag "$(TAG)")

delete-runs:     ## delete runs (their stored results are kept for reuse): make delete-runs RUN_ID=<id> or TAG=scratch
	$(RUN) appeals delete-runs $(if $(RUN_ID),"$(RUN_ID)") $(if $(TAG),--tag "$(TAG)")

prune-results:   ## delete stored results no run uses (asks first; they cost money to make again)
	$(RUN) appeals prune-results

score:           ## compare a run with the reference answers: make score RUN_ID=<id>
	$(RUN) appeals score $(RUN_ID)

serve:           ## serve the dashboard on 0.0.0.0:$(PORT); restarts itself when the code changes
	$(RUN) appeals serve --port $(PORT)

release:         ## build a release from a finished run: make release RUN_ID=<id> [VERSION=v0.0.2] [TAG=preview]
	$(RUN) appeals release $(RUN_ID) $(if $(VERSION),--version "$(VERSION)") $(if $(TAG),--tag "$(TAG)")

releases:        ## list releases, marking the current one: make releases [TAG=test]
	$(RUN) appeals releases $(if $(TAG),--tag "$(TAG)")

publish:         ## make a release the one the site and MCP server serve: make publish RELEASE=<id>
	$(RUN) appeals publish $(RELEASE)

delete-releases: ## delete releases for good: make delete-releases RELEASE=<id> or TAG=test (never the current one)
	$(RUN) appeals delete-releases $(if $(RELEASE),"$(RELEASE)") $(if $(TAG),--tag "$(TAG)")

# deploy/appeals-site.service keeps it running as a systemd user service, with
# SITE_HOST and SITE_PORT from .site-env (such as the VPN address).
site:            ## serve the public site and MCP server: make site SITE_HOST=0.0.0.0 SITE_PORT=8000 [PUBLIC_URL=http://192.168.88.3:8000]
	$(RUN) appeals site --host $(SITE_HOST) --port $(SITE_PORT) $(if $(PUBLIC_URL),--public-url "$(PUBLIC_URL)")

mcp-check:       ## check a running MCP endpoint: make mcp-check URL=http://host:port/appeals/mcp
	$(RUN) appeals mcp-check $(URL)
