PYTHON ?= python3
WEBSITE_DIR ?= website
IMAGE ?= s3mirror:local

.PHONY: test container-build container-smoke website-install website-dev website-build website-check website-test website-capture readme-hero

test:
	$(PYTHON) -m pytest tests

container-build:
	docker build --pull --tag $(IMAGE) .

container-smoke: container-build
	docker run --rm $(IMAGE) --version

website-install:
	npm --prefix $(WEBSITE_DIR) ci

website-dev:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run dev

website-build:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run build

website-check:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run check

website-test:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run test

website-capture:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run capture

readme-hero:
	uv run scripts/readme/build_readme_hero.py
