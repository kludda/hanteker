.PHONY: build
build: clear
	cargo build --release

.PHONY: fmt
fmt:
	cargo fmt

.PHONY: clippy
clippy: clear
	cargo clippy

.PHONY: clear
clear:
	@i=0; while [ $$i -lt 100 ]; do echo ""; i=$$((i+1)); done
