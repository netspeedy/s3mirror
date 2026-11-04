WEBSITE_DIR ?= website
IMAGE ?= s3mirror:local

.PHONY: container-build container-smoke website-install website-check website-build website-dev readme-hero

container-build:
	docker build --pull --tag $(IMAGE) .

container-smoke: container-build
	docker run --rm $(IMAGE) --version

website-install:
	npm --prefix $(WEBSITE_DIR) install

website-check:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run check

website-build:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run build

website-dev:
	test -d $(WEBSITE_DIR)/node_modules || (printf 'missing website dependencies; run `make website-install`\n' >&2 && exit 1)
	npm --prefix $(WEBSITE_DIR) run dev

readme-hero:
	uv run scripts/readme/build_readme_hero.py
