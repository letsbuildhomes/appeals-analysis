# Everything runs through uv; nothing touches the system Python or pip.
UV      ?= uv
RUN     := $(UV) run
PORT    ?= 8800
WORKERS ?= 24
MODEL   ?= fake
LIMIT   ?= 10
DOCKETS ?=
TAG     ?=
RUN_ID  ?=

.PHONY: help setup doctor test lint ingest crawl dockets graph run runs delete-runs serve score

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
	$(RUN) ruff check appeals tests

ingest:          ## download new PDFs from known listings, extract text, assign dockets
	$(RUN) appeals ingest

crawl:           ## crawl the live listing, then ingest
	$(RUN) appeals ingest --crawl

dockets:         ## list recent dockets
	$(RUN) appeals dockets

graph:           ## build and validate the extraction graph, write data/graph.json
	$(RUN) appeals graph

run:             ## run the graph: make run MODEL=fake|live LIMIT=10 or DOCKETS="a,b" WORKERS=24 TAG=scratch
	$(RUN) appeals run --model $(MODEL) --workers $(WORKERS) $(if $(DOCKETS),--dockets "$(DOCKETS)",--limit $(LIMIT)) $(if $(TAG),--tag "$(TAG)")

runs:            ## list runs: make runs [TAG=scratch]
	$(RUN) appeals runs $(if $(TAG),--tag "$(TAG)")

delete-runs:     ## delete runs and results no other run uses: make delete-runs RUN_ID=<id> or TAG=scratch
	$(RUN) appeals delete-runs $(if $(RUN_ID),"$(RUN_ID)") $(if $(TAG),--tag "$(TAG)")

score:           ## compare a run with the reference answers: make score RUN_ID=<id>
	$(RUN) appeals score $(RUN_ID)

serve:           ## serve the dashboard on 0.0.0.0:$(PORT)
	$(RUN) appeals serve --port $(PORT)
