# Changelog

## [0.15.3](https://github.com/lazynet/lazy-harness/compare/v0.15.2...v0.15.3) (2026-05-04)


### Refactors

* **knowledge:** make session classify rules configurable (ADR-028) ([#58](https://github.com/lazynet/lazy-harness/issues/58)) ([e20e504](https://github.com/lazynet/lazy-harness/commit/e20e504dc71b1b3e8164778307534b033e0ac173))


### Documentation

* **readme:** describe full five-layer memory stack with engram, qmd, graphify ([0983355](https://github.com/lazynet/lazy-harness/commit/0983355d5d806d71317c5fe7357c3d5af4680e61))
* **readme:** fix qmd upstream url (tobi/qmd, not lazynet/qmd) ([3064897](https://github.com/lazynet/lazy-harness/commit/30648978babfd1c07fd665ea9a4f1e182987b4b4))
* **readme:** redesign for value-first structure and richer feature surface ([da2421e](https://github.com/lazynet/lazy-harness/commit/da2421ef0827c6f7171d9bfab083b4459969034c))

## [0.15.2](https://github.com/lazynet/lazy-harness/compare/v0.15.1...v0.15.2) (2026-05-04)


### Bug Fixes

* write MCP servers to .claude.json and remove graphify from MCP flow ([#55](https://github.com/lazynet/lazy-harness/issues/55)) ([b9f5c36](https://github.com/lazynet/lazy-harness/commit/b9f5c361e6c51fed47734214152f18049143cd48))

## [0.15.1](https://github.com/lazynet/lazy-harness/compare/v0.15.0...v0.15.1) (2026-05-03)


### Documentation

* ADR-027 memory stack overview (five-layer model) ([#52](https://github.com/lazynet/lazy-harness/issues/52)) ([02b81fd](https://github.com/lazynet/lazy-harness/commit/02b81fd2c136bc8f87afe8b1cbf79d85fc9f1a7e))

## [0.15.0](https://github.com/lazynet/lazy-harness/compare/v0.14.0...v0.15.0) (2026-05-03)


### Features

* lh config wizards for memory + knowledge (ADR-026, closes ADR-018) ([#50](https://github.com/lazynet/lazy-harness/issues/50)) ([ced21b0](https://github.com/lazynet/lazy-harness/commit/ced21b00d555c99fb8f67ed87a4554c733ae6106))

## [0.14.0](https://github.com/lazynet/lazy-harness/compare/v0.13.0...v0.14.0) (2026-05-03)


### Features

* lh doctor Features section for triple stack (ADR-025) ([#48](https://github.com/lazynet/lazy-harness/issues/48)) ([c6f8e29](https://github.com/lazynet/lazy-harness/commit/c6f8e294737894fe247f1ea7d29e6c86ad16410b))

## [0.13.0](https://github.com/lazynet/lazy-harness/compare/v0.12.0...v0.13.0) (2026-05-03)


### Features

* Graphify as optional code-structure index (ADR-023) ([#46](https://github.com/lazynet/lazy-harness/issues/46)) ([50460d1](https://github.com/lazynet/lazy-harness/commit/50460d1fd857ccfb80245ce555761bda44af82d8))

## [0.12.0](https://github.com/lazynet/lazy-harness/compare/v0.11.0...v0.12.0) (2026-05-03)


### Features

* Engram as optional episodic memory backend (ADR-022) ([#44](https://github.com/lazynet/lazy-harness/issues/44)) ([3bce0fb](https://github.com/lazynet/lazy-harness/commit/3bce0fb946c79c19c240aa0691fbe7797466658b))

## [0.11.0](https://github.com/lazynet/lazy-harness/compare/v0.10.1...v0.11.0) (2026-05-03)


### Features

* MCP server orchestration via lh deploy (ADR-024) ([#42](https://github.com/lazynet/lazy-harness/issues/42)) ([9140b99](https://github.com/lazynet/lazy-harness/commit/9140b99da8f09b40878aa7972eb9f64f7c393fca))

## [0.10.1](https://github.com/lazynet/lazy-harness/compare/v0.10.0...v0.10.1) (2026-05-03)


### Bug Fixes

* **compound-loop:** accept last-prompt as interactive session marker ([#40](https://github.com/lazynet/lazy-harness/issues/40)) ([dfd6b2e](https://github.com/lazynet/lazy-harness/commit/dfd6b2ee8d432b2aac288fdabf136b998c1a2530))

## [0.10.0](https://github.com/lazynet/lazy-harness/compare/v0.9.1...v0.10.0) (2026-05-03)


### Features

* async response grading via the compound-loop worker ([#38](https://github.com/lazynet/lazy-harness/issues/38)) ([5f16c40](https://github.com/lazynet/lazy-harness/commit/5f16c40c77bcc5898af93e870dfe94f2d2665486))

## [0.9.1](https://github.com/lazynet/lazy-harness/compare/v0.9.0...v0.9.1) (2026-04-26)


### Bug Fixes

* **monitoring:** add claude-opus-4-7 pricing and surface unknown models ([#36](https://github.com/lazynet/lazy-harness/issues/36)) ([606f4e1](https://github.com/lazynet/lazy-harness/commit/606f4e19b650d4257c6582a67b9bbe91260a1d4c))

## [0.9.0](https://github.com/lazynet/lazy-harness/compare/v0.8.3...v0.9.0) (2026-04-23)


### Features

* **hooks:** add post-compact built-in re-injecting pre-compact summary ([#34](https://github.com/lazynet/lazy-harness/issues/34)) ([64fff7e](https://github.com/lazynet/lazy-harness/commit/64fff7ede03054ce7dbc840390c9c3c4c0401849))


### Documentation

* **hooks:** document post-compact built-in ([a88dbe9](https://github.com/lazynet/lazy-harness/commit/a88dbe99f5417ea9df46a8099ab6412ac11333ff))

## [0.8.3](https://github.com/lazynet/lazy-harness/compare/v0.8.2...v0.8.3) (2026-04-20)


### Bug Fixes

* **release-please:** gate sync-lock on open release PR, not on action output ([#32](https://github.com/lazynet/lazy-harness/issues/32)) ([19f51c7](https://github.com/lazynet/lazy-harness/commit/19f51c7058d3639c152537d668c19aea7c2844d6))

## [0.8.2](https://github.com/lazynet/lazy-harness/compare/v0.8.1...v0.8.2) (2026-04-20)


### Documentation

* **workflow:** add documentation short-path policy ([#29](https://github.com/lazynet/lazy-harness/issues/29)) ([d4c8ad4](https://github.com/lazynet/lazy-harness/commit/d4c8ad4e9747a3fd03acc1e862d2ce8a0aa69222))

## [0.8.1](https://github.com/lazynet/lazy-harness/compare/v0.8.0...v0.8.1) (2026-04-17)


### Documentation

* **backlog:** add deploy hook-defaults merge item (Opción A) ([#27](https://github.com/lazynet/lazy-harness/issues/27)) ([c70dc19](https://github.com/lazynet/lazy-harness/commit/c70dc193f57634a0e1897588f6765736c77e98e3))

## [0.8.0](https://github.com/lazynet/lazy-harness/compare/v0.7.0...v0.8.0) (2026-04-17)


### Features

* security hooks cluster (PreToolUse blocker + PostToolUse ruff format) ([#25](https://github.com/lazynet/lazy-harness/issues/25)) ([c4d35b7](https://github.com/lazynet/lazy-harness/commit/c4d35b7315ca23bec49b999420ff25d67dba0f8c))


### Documentation

* **backlog:** refresh priorities + expand PreToolUse scope ([#24](https://github.com/lazynet/lazy-harness/issues/24)) ([b5b3835](https://github.com/lazynet/lazy-harness/commit/b5b38351c2a90addb15ac226f3db48aa4cd32392))

## [0.7.0](https://github.com/lazynet/lazy-harness/compare/v0.6.4...v0.7.0) (2026-04-16)


### Features

* force final compound-loop at session end ([#22](https://github.com/lazynet/lazy-harness/issues/22)) ([6f344fc](https://github.com/lazynet/lazy-harness/commit/6f344fcdfb76c72f2c5db60a760debb278db8c39))

## [0.6.4](https://github.com/lazynet/lazy-harness/compare/v0.6.3...v0.6.4) (2026-04-15)


### Bug Fixes

* restore green pre-commit gate on main ([#20](https://github.com/lazynet/lazy-harness/issues/20)) ([4a5b1f2](https://github.com/lazynet/lazy-harness/commit/4a5b1f25fe28f7e91c1696bdecba4e66c6bc5d4f))

## [0.6.3](https://github.com/lazynet/lazy-harness/compare/v0.6.2...v0.6.3) (2026-04-15)


### Bug Fixes

* harden cross-session handoff loop against stale data ([#18](https://github.com/lazynet/lazy-harness/issues/18)) ([22d7896](https://github.com/lazynet/lazy-harness/commit/22d7896b584c662a45b4a7eac32b1065e90bfef2))

## [0.6.2](https://github.com/lazynet/lazy-harness/compare/v0.6.1...v0.6.2) (2026-04-15)


### Documentation

* **community:** add LICENSE, CONTRIBUTING, and GitHub issue/PR templates ([#16](https://github.com/lazynet/lazy-harness/issues/16)) ([0ffa995](https://github.com/lazynet/lazy-harness/commit/0ffa99581d402714a8f26a0e628f947bf47aacca))

## [0.6.1](https://github.com/lazynet/lazy-harness/compare/v0.6.0...v0.6.1) (2026-04-15)


### Bug Fixes

* accept last-prompt as interactive marker in session export ([#15](https://github.com/lazynet/lazy-harness/issues/15)) ([0b9f2c6](https://github.com/lazynet/lazy-harness/commit/0b9f2c6df71b042dd070663cace7926dcf16b608))


### Documentation

* **adrs:** add structured Status field and audit index ([#11](https://github.com/lazynet/lazy-harness/issues/11)) ([92d8bb3](https://github.com/lazynet/lazy-harness/commit/92d8bb37fc76e9e8875002c5c043ff9d0b8eeabb))
* **governance:** segment CLAUDE.md into rules + workflow docs + slash commands ([#12](https://github.com/lazynet/lazy-harness/issues/12)) ([d6e9747](https://github.com/lazynet/lazy-harness/commit/d6e97473aef031ef8e557ee9471f76b7d6f7f942))
* **roadmap:** introduce public roadmap, move backlog internal, fix orphan spec ([#13](https://github.com/lazynet/lazy-harness/issues/13)) ([1d94243](https://github.com/lazynet/lazy-harness/commit/1d94243909b91ba8624fd470513161c2cd54f180))

## [0.6.0](https://github.com/lazynet/lazy-harness/compare/v0.5.1...v0.6.0) (2026-04-15)


### Features

* **metrics:** plugin system + metrics_sink vertical slice ([#8](https://github.com/lazynet/lazy-harness/issues/8)) ([474c826](https://github.com/lazynet/lazy-harness/commit/474c826196146c55021a3df67212cb304f25887b))


### Documentation

* **adrs:** add ADR-018 — feature discoverability via doctor + config ([#9](https://github.com/lazynet/lazy-harness/issues/9)) ([8278c6c](https://github.com/lazynet/lazy-harness/commit/8278c6c5aa43b0b9e5dc0f62c59d691bf1250f8b))

## [0.5.1](https://github.com/lazynet/lazy-harness/compare/v0.5.0...v0.5.1) (2026-04-13)


### Bug Fixes

* metrics session counter + per-profile breakdown ([#5](https://github.com/lazynet/lazy-harness/issues/5)) ([3242351](https://github.com/lazynet/lazy-harness/commit/32423510aa14a59940cca5569f296ee5acaaca27))

## [0.5.0](https://github.com/lazynet/lazy-harness/compare/v0.4.0...v0.5.0) (2026-04-13)


### Features

* add hooks config to Config dataclass ([fa28b66](https://github.com/lazynet/lazy-harness/commit/fa28b66c00fe73f074c7d7031ac8994ef06e4cbb))
* agent adapter protocol + Claude Code adapter ([5547cb9](https://github.com/lazynet/lazy-harness/commit/5547cb92ffb7794e1185ca738750efaa05633281))
* CLI skeleton with click (lh command) ([c21513d](https://github.com/lazynet/lazy-harness/commit/c21513da6ccb68f5063595a15c95a7c4198ea801))
* **cli:** lh migrate command with dry-run gate and rollback ([8cfb2e8](https://github.com/lazynet/lazy-harness/commit/8cfb2e8c2633419b68e1cf2469b20b1afbef88ab))
* **cli:** lh selftest command ([d8777d5](https://github.com/lazynet/lazy-harness/commit/d8777d5e23e993f657bfa22bb1a395d628c91431))
* cross-platform path resolution module ([1abc77a](https://github.com/lazynet/lazy-harness/commit/1abc77a860acbc86608c47dc7bc048f9422f6713))
* **hooks:** phase 3.5 — port hooks to builtins + lh hook CLI ([ff69d00](https://github.com/lazynet/lazy-harness/commit/ff69d0058977e67a21aa588f0e50ee6f93fc60d5))
* **init:** existing-setup detection guard ([7947f33](https://github.com/lazynet/lazy-harness/commit/7947f333dacf7ff502f3de620c3afc269e898eec))
* initial repo scaffold with pyproject.toml ([3043ef8](https://github.com/lazynet/lazy-harness/commit/3043ef8dec8215174f85b927ac900434fecd25d4))
* **init:** lh init wizard with existing-setup guard ([8256ac9](https://github.com/lazynet/lazy-harness/commit/8256ac9b3ca3d5e33dd19cbc59075d526159a0f4))
* **init:** wizard answers and config generation ([f77a4eb](https://github.com/lazynet/lazy-harness/commit/f77a4eb2d515afdea50f860cfedb2ed12f152209))
* **knowledge:** port qmd-context-gen + scheduler jobs + logfile rotation ([4bffbf9](https://github.com/lazynet/lazy-harness/commit/4bffbf92b17de2214ec5712250d0ffad14c88872))
* lh deploy with profile symlinks ([933cb6c](https://github.com/lazynet/lazy-harness/commit/933cb6c2b88ef8af65e2f83915757715f21608b5))
* lh doctor health check ([51b1ea5](https://github.com/lazynet/lazy-harness/commit/51b1ea56960c1f9c5301eabe5a4ec55ff85eedb5))
* lh init wizard (interactive + non-interactive) ([140b8ea](https://github.com/lazynet/lazy-harness/commit/140b8eaad903680f88153f3fd3b6277d60ee86b0))
* lh metrics ingest with mtime-skip upsert pipeline ([#1](https://github.com/lazynet/lazy-harness/issues/1)) ([18e4f13](https://github.com/lazynet/lazy-harness/commit/18e4f139224db43d634dedf3d2ad4cd968d47c1d))
* lh profile list/add/remove ([959528e](https://github.com/lazynet/lazy-harness/commit/959528ea2c66817249f26294ce506741f19e06a1))
* **migrate:** add DetectedState dataclasses ([389429c](https://github.com/lazynet/lazy-harness/commit/389429c3407719a2c23bd2eab479cb65cf06a74b))
* **migrate:** backup step ([fde3cbb](https://github.com/lazynet/lazy-harness/commit/fde3cbb539668f18e2cc3887a5dc9218196c8773))
* **migrate:** config generation step ([6b27324](https://github.com/lazynet/lazy-harness/commit/6b2732472a744b332819658123b82e4401e96e7e))
* **migrate:** detect deployed scripts, launch agents, and qmd ([ffdbff8](https://github.com/lazynet/lazy-harness/commit/ffdbff845f3ec2fae6ef08e05d214840d0b9fba4))
* **migrate:** detect lazy-claudecode multi-profile setup ([8255a0e](https://github.com/lazynet/lazy-harness/commit/8255a0eb3ff34a0bde2f94cc2fca59d54c21f867))
* **migrate:** detect vanilla Claude Code setup ([b88cb89](https://github.com/lazynet/lazy-harness/commit/b88cb893de7da545c0bd64d548af90def226cb0d))
* **migrate:** dry-run gate with TTL marker ([1bd1c9e](https://github.com/lazynet/lazy-harness/commit/1bd1c9e45b922e17e821260f5820b1b74819605c))
* **migrate:** executor with rollback log ([72aecc5](https://github.com/lazynet/lazy-harness/commit/72aecc589f81d937620d80a1bcc6110c2eb71ef8))
* **migrate:** flatten lazy-claudecode symlinks in profile dirs ([2fd6dc8](https://github.com/lazynet/lazy-harness/commit/2fd6dc805bc9e2f62ebadf2eb33ebac15aa55051))
* **migrate:** MigrationPlan and Step protocol ([a439e80](https://github.com/lazynet/lazy-harness/commit/a439e8003913c579c0e248c8aeee6acaee8445c7))
* **migrate:** planner builds MigrationPlan from DetectedState ([2780cea](https://github.com/lazynet/lazy-harness/commit/2780ceaab5d87842804fb95414fc00d220077d66))
* **migrate:** remove deployed scripts step ([8cf4cc8](https://github.com/lazynet/lazy-harness/commit/8cf4cc808a6d5c6970fe737cfbc27908a272c28a))
* **migrate:** top-level detect_state orchestrator ([086fa4d](https://github.com/lazynet/lazy-harness/commit/086fa4dd3c593c23e08392a05d3e99cf14862169))
* profile management (list, add, remove, resolve) ([4f97ebe](https://github.com/lazynet/lazy-harness/commit/4f97ebec16b5f06227509e5bcce018f2ae73c945))
* **profile:** lh profile move — relocate project history between profiles ([0d33b29](https://github.com/lazynet/lazy-harness/commit/0d33b292d131dc07371e3db65310a81562491c6a))
* **run:** lh run launcher + lh profile envrc + agent binary resolution ([bf1cb1d](https://github.com/lazynet/lazy-harness/commit/bf1cb1dab6786ad17ec68bce30bc9f1b99a29bd7))
* **selftest:** cli integrity check ([c95919c](https://github.com/lazynet/lazy-harness/commit/c95919c06970e5a173ccda7acf2a1a5bd87708a4))
* **selftest:** config integrity check ([4bae343](https://github.com/lazynet/lazy-harness/commit/4bae3436238f90885652931d17219afcf7ba232e))
* **selftest:** hooks check ([b4056aa](https://github.com/lazynet/lazy-harness/commit/b4056aaf0c8c73872ee9062eb81240fd3f3158f3))
* **selftest:** knowledge check ([1545c59](https://github.com/lazynet/lazy-harness/commit/1545c590747a177c207f1d993aa9175c6e6d6b39))
* **selftest:** monitoring check ([39827b5](https://github.com/lazynet/lazy-harness/commit/39827b5b3fd80e00c5161f7994d182e04d689467))
* **selftest:** profile health check ([a12f6dc](https://github.com/lazynet/lazy-harness/commit/a12f6dc3fe2db007d98c657e1d9c1cc5185cdc09))
* **selftest:** result types and runner skeleton ([b692c52](https://github.com/lazynet/lazy-harness/commit/b692c522089a60491283ed2f2978e48e10ee7dd6))
* **selftest:** scheduler check ([aaa6d15](https://github.com/lazynet/lazy-harness/commit/aaa6d15e17dae89b3646aa6e7c12fd26ee88e2be))
* **statusline:** port claude-statusline.sh to lh statusline ([5702dad](https://github.com/lazynet/lazy-harness/commit/5702dadbea9994ea2f040644a676ee87117c7f15))
* **status:** port 9 lcc-status views to lh status ([3d1ee31](https://github.com/lazynet/lazy-harness/commit/3d1ee31b034ff68d562f7f788c96746008f09822))
* TOML config loading, validation, and persistence ([c739a30](https://github.com/lazynet/lazy-harness/commit/c739a30dbdd36190d3aa13a86b2505c097728f76))


### Bug Fixes

* dedup ingest by message id, align pricing with ccusage ([#2](https://github.com/lazynet/lazy-harness/issues/2)) ([c35b293](https://github.com/lazynet/lazy-harness/commit/c35b2930bf6c7e09a7a315102d73a4dc60bbf16b))
* lint and format cleanup ([d605cb7](https://github.com/lazynet/lazy-harness/commit/d605cb7c932dbdbe353d9a30bf6c7274ef886a88))
* lint and format cleanup for phase 2 ([b81f0a6](https://github.com/lazynet/lazy-harness/commit/b81f0a642bddc867e7516e5dbe1b0fe61785217b))
* lint and format cleanup for phase 3 ([99dc91e](https://github.com/lazynet/lazy-harness/commit/99dc91e420f24c798a357ff1297bafa63871c8fa))
* **migrate,init:** emit correct [profiles.&lt;name&gt;] TOML format ([bff3566](https://github.com/lazynet/lazy-harness/commit/bff35662caa29fdea19efd849f1b0232b8a8811a))
* **migrate:** detect both com.lazy.* and com.lazynet.* launch agents ([ae5c7dd](https://github.com/lazynet/lazy-harness/commit/ae5c7dd5a33290f11a98b44ab32e0a78b38de1d4))
* **migrate:** include knowledge_paths in has_existing_setup ([7592669](https://github.com/lazynet/lazy-harness/commit/7592669d7ba22e4102e820e809e2ab8005d5e304))


### Documentation

* add backlog tracking file ([7853db5](https://github.com/lazynet/lazy-harness/commit/7853db5ae7cb9f68ff66092d0ca00b211880b7fa))
* add How section, expand architecture ADRs, drop history from nav ([57d411c](https://github.com/lazynet/lazy-harness/commit/57d411c12c95aff783fae5b507ef23f25672abf3))
* adopt strict TDD in CLAUDE.md ([f97ac57](https://github.com/lazynet/lazy-harness/commit/f97ac57b69789f1d6bd3d5c82eeb4572d9b704eb))
* init CLAUDE.md, rewrite README, scrub personal refs from public pages ([efd6806](https://github.com/lazynet/lazy-harness/commit/efd68068889847a644d514ac1c698ab938fc9a0c))
* initial ADRs (001-004, 007) ([12fba73](https://github.com/lazynet/lazy-harness/commit/12fba73193573296220745f16be00903df0a819d))
* migrate 13 legacy ADRs from lazy-claudecode ([85c904b](https://github.com/lazynet/lazy-harness/commit/85c904b1a6837da82815f444467c9fbb11be3b84))
* migrate history (genesis, lessons-learned, specs, plans, workflows) ([15b0991](https://github.com/lazynet/lazy-harness/commit/15b09916635f7e6fd0a32b776a62d750c2835061))
* mkdocs material scaffolding ([51dc0ae](https://github.com/lazynet/lazy-harness/commit/51dc0ae33672b5036632dec4459816b066dfd8f7))
* phase 4 content pages (why, getting-started, reference, architecture) ([4b6fb65](https://github.com/lazynet/lazy-harness/commit/4b6fb65bf0c8b85475ec81dec38d2eb890e52939))
