WEBSITE_DIR ?= .github/assets/website

.PHONY: website-install website-check website-build website-dev

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
