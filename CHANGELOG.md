# Changelog

## [0.44.4](https://github.com/lazynet/lazy-harness/compare/v0.44.3...v0.44.4) (2026-08-19)


### Bug Fixes

* merge qmd context blocks whatever scalar style they use ([#196](https://github.com/lazynet/lazy-harness/issues/196)) ([82c788b](https://github.com/lazynet/lazy-harness/commit/82c788bc6eb27ad77ff5e1790f5f036b19053cee))

## [0.44.3](https://github.com/lazynet/lazy-harness/compare/v0.44.2...v0.44.3) (2026-08-18)


### Bug Fixes

* parse the version out of --version instead of taking the last token ([#194](https://github.com/lazynet/lazy-harness/issues/194)) ([baf4b1e](https://github.com/lazynet/lazy-harness/commit/baf4b1e0a9cf0dcc1d0e58a2928cd6269d3824f7))

## [0.44.2](https://github.com/lazynet/lazy-harness/compare/v0.44.1...v0.44.2) (2026-08-18)


### Bug Fixes

* report the pin from config instead of the module constant ([#192](https://github.com/lazynet/lazy-harness/issues/192)) ([f72d725](https://github.com/lazynet/lazy-harness/commit/f72d725a2084e11dd3559927264a5859bfa2ddd6))

## [0.44.1](https://github.com/lazynet/lazy-harness/compare/v0.44.0...v0.44.1) (2026-08-18)


### Bug Fixes

* resolve url.insteadOf shorthands when keying a project ([#190](https://github.com/lazynet/lazy-harness/issues/190)) ([5bf2732](https://github.com/lazynet/lazy-harness/commit/5bf27324607007c0fe579c936c8b5ee4426cf345))

## [0.44.0](https://github.com/lazynet/lazy-harness/compare/v0.43.0...v0.44.0) (2026-08-18)


### Features

* replace cross-profile-check with a legacy memory detector ([#188](https://github.com/lazynet/lazy-harness/issues/188)) ([854c600](https://github.com/lazynet/lazy-harness/commit/854c600d6f2a1e475ac246fc91d071176cfc206f))


### Bug Fixes

* keep the engram cursor on the machine that owns the database ([#187](https://github.com/lazynet/lazy-harness/issues/187)) ([6fef6bc](https://github.com/lazynet/lazy-harness/commit/6fef6bcd5fce16721abfd5987049151e67c85c89))
* let a hook's exit code reach Claude Code ([#186](https://github.com/lazynet/lazy-harness/issues/186)) ([1f601d8](https://github.com/lazynet/lazy-harness/commit/1f601d8a1b776421a24047e4186759b9ddf19fc1))

## [0.43.0](https://github.com/lazynet/lazy-harness/compare/v0.42.1...v0.43.0) (2026-08-18)


### Features

* derive a project identity that survives moving between machines ([4666721](https://github.com/lazynet/lazy-harness/commit/46667216764f0c0b9af8d121e6add97eebf04108))
* migrate project memory to its identity-keyed home ([95ba3e5](https://github.com/lazynet/lazy-harness/commit/95ba3e5af8d1e15db70f904bea537b21732c2a9d))
* overlay per-profile secrets onto the launch environment ([9bdf498](https://github.com/lazynet/lazy-harness/commit/9bdf498371c8e078019c06227c291ec9d2e31f7f))
* resolve a project's memory directory from the knowledge store ([b76b710](https://github.com/lazynet/lazy-harness/commit/b76b710b9209e65e8f4b9111f8c0321f7a8b9ff0))


### Bug Fixes

* read a git config the way git writes it, not the way configparser expects ([871a74a](https://github.com/lazynet/lazy-harness/commit/871a74a8b808169e580cd948176cae4fe7f207d2))
* repair the hook launcher and deploy stable hook commands ([87f3b8b](https://github.com/lazynet/lazy-harness/commit/87f3b8b97aed44ba094eaaf766cfebcb2ca5ec80))
* resolve the memory CLI's project directory the way the hooks do ([42962c9](https://github.com/lazynet/lazy-harness/commit/42962c9747d8fd299b363baaddd27911f4ec4be2))
* use the channels the compact events actually provide ([7e3d22f](https://github.com/lazynet/lazy-harness/commit/7e3d22fa7addb17b4c9b1a384e5d895b0fe71274))


### Refactors

* read memory from both locations while machines migrate ([37847c0](https://github.com/lazynet/lazy-harness/commit/37847c09189e2fed6572a0e9a78f754960deccdc))
* route every hook's memory directory through one resolver ([c152cc4](https://github.com/lazynet/lazy-harness/commit/c152cc43bfdd4916bdc5d58b22d8926f4cca84cd))


### Documentation

* close the linux parity spec against what shipped ([23ae7e2](https://github.com/lazynet/lazy-harness/commit/23ae7e21ec063ac7d9655bfd7c6cf878d226bf86))

## [0.42.1](https://github.com/lazynet/lazy-harness/compare/v0.42.0...v0.42.1) (2026-08-18)


### Bug Fixes

* keep the config section in doctor and migrate hints ([#183](https://github.com/lazynet/lazy-harness/issues/183)) ([a02abb7](https://github.com/lazynet/lazy-harness/commit/a02abb7ccc444027b57898186e35f4950b14b994))


### Refactors

* one capability registry for everything that can be turned on ([#184](https://github.com/lazynet/lazy-harness/issues/184)) ([2968cca](https://github.com/lazynet/lazy-harness/commit/2968ccafd714add3fa74694e6f203faec2a8d6de))
* return renderables from the status views instead of printing ([#181](https://github.com/lazynet/lazy-harness/issues/181)) ([a954afc](https://github.com/lazynet/lazy-harness/commit/a954afcc03c5cc1af4182069c8241da2c38128e8))

## [0.42.0](https://github.com/lazynet/lazy-harness/compare/v0.41.1...v0.42.0) (2026-08-17)


### Features

* detect scheduled jobs installed by a superseded generator ([#179](https://github.com/lazynet/lazy-harness/issues/179)) ([063a409](https://github.com/lazynet/lazy-harness/commit/063a409feb665bf53675f8a0c41bf2f014082abe))

## [0.41.1](https://github.com/lazynet/lazy-harness/compare/v0.41.0...v0.41.1) (2026-08-17)


### Bug Fixes

* build a scheduled job's PATH from the platform, not the environment ([#176](https://github.com/lazynet/lazy-harness/issues/176)) ([83d1ca5](https://github.com/lazynet/lazy-harness/commit/83d1ca5fe65f98585a7d6d00bb282a51e22833f0))
* stop rich from deleting section names in CLI messages ([#177](https://github.com/lazynet/lazy-harness/issues/177)) ([69166a7](https://github.com/lazynet/lazy-harness/commit/69166a7ffbd15cce160a85a9a22b7dee9af686ca))

## [0.41.0](https://github.com/lazynet/lazy-harness/compare/v0.40.2...v0.41.0) (2026-08-17)


### Features

* implement the systemd and cron scheduler backends ([#174](https://github.com/lazynet/lazy-harness/issues/174)) ([fa1fc1b](https://github.com/lazynet/lazy-harness/commit/fa1fc1bae4d93ad2c61e604e91e6c0ee0c22de97))

## [0.40.2](https://github.com/lazynet/lazy-harness/compare/v0.40.1...v0.40.2) (2026-08-17)


### Bug Fixes

* preserve comments, mode and formatting in the config wizards ([#171](https://github.com/lazynet/lazy-harness/issues/171)) ([6b24cc7](https://github.com/lazynet/lazy-harness/commit/6b24cc7e4bfc5a51bc3068d1ffd511e964a9c1f1))
* report scheduler job state honestly and move discovery behind the backend ([#172](https://github.com/lazynet/lazy-harness/issues/172)) ([ee2546e](https://github.com/lazynet/lazy-harness/commit/ee2546e78f85a8bb5203cae2a6ddaeb2de41b62f))


### Documentation

* specs and plans for the Linux parity, capability registry and TUI refactors ([#166](https://github.com/lazynet/lazy-harness/issues/166)) ([c900396](https://github.com/lazynet/lazy-harness/commit/c90039664bb5fc30ec394bbb2a95a25798f7f6de))

## [0.40.1](https://github.com/lazynet/lazy-harness/compare/v0.40.0...v0.40.1) (2026-08-17)


### Bug Fixes

* install launchd jobs on their declared schedule ([#168](https://github.com/lazynet/lazy-harness/issues/168)) ([cb52048](https://github.com/lazynet/lazy-harness/commit/cb52048582be8db5c0653777a57834c75370fb77))

## [0.40.0](https://github.com/lazynet/lazy-harness/compare/v0.39.0...v0.40.0) (2026-08-17)


### Features

* make config writes non-destructive and add a round-trip selftest check ([#167](https://github.com/lazynet/lazy-harness/issues/167)) ([56429ad](https://github.com/lazynet/lazy-harness/commit/56429ad2976250d7662816647aceef5e6c59499e))

## [0.39.0](https://github.com/lazynet/lazy-harness/compare/v0.38.1...v0.39.0) (2026-08-17)


### Features

* **context-inject:** inject a repo map for sessions inside a declared scope ([#164](https://github.com/lazynet/lazy-harness/issues/164)) ([e92a32a](https://github.com/lazynet/lazy-harness/commit/e92a32a0e2ad5d4d92584c2d54d44fb8ef490d38))

## [0.38.1](https://github.com/lazynet/lazy-harness/compare/v0.38.0...v0.38.1) (2026-08-16)


### Bug Fixes

* canonicalise loop-event attribution and verify it against the shipped hooks ([#163](https://github.com/lazynet/lazy-harness/issues/163)) ([5157a87](https://github.com/lazynet/lazy-harness/commit/5157a8703b4fb40084110392013b89228b1487b6))


### Documentation

* add verification gates drained from the loop-engineering session ([#161](https://github.com/lazynet/lazy-harness/issues/161)) ([de3c518](https://github.com/lazynet/lazy-harness/commit/de3c51829bbc48da9977ff3d71cf0c645624221b))

## [0.38.0](https://github.com/lazynet/lazy-harness/compare/v0.37.0...v0.38.0) (2026-08-16)


### Features

* instrument loop events and add opt-in goal-tracking hook ([#160](https://github.com/lazynet/lazy-harness/issues/160)) ([2eab6cc](https://github.com/lazynet/lazy-harness/commit/2eab6cc73cfba32764e2a4c3b6ce55ec3737580b))


### Documentation

* merge drained compound-loop proposals into verification gates ([#159](https://github.com/lazynet/lazy-harness/issues/159)) ([c530d01](https://github.com/lazynet/lazy-harness/commit/c530d01948dfcf99e62f880f2cc2e219aa8924ae))
* **specs:** add cross-repo delegation phase to loop engineering design ([8e4d8db](https://github.com/lazynet/lazy-harness/commit/8e4d8db2ce41981fc3ce7d8a73efbe1c5980ec3d))
* **specs:** add delegate isolation, return policy and rotation ([7bed461](https://github.com/lazynet/lazy-harness/commit/7bed46153288d0d29d5cf3e4214b4f96ba10d170))
* **specs:** add delegate pane lifecycle rules ([81ed163](https://github.com/lazynet/lazy-harness/commit/81ed1635472aca9c44ae3ff07dc967b02db0d93c))
* **specs:** add loop engineering design ([77e7cdb](https://github.com/lazynet/lazy-harness/commit/77e7cdb8c9bb723100d5509b3ad8505c3e21f205))
* **specs:** add loop engineering implementation plan for phases 0-1 ([eed42f3](https://github.com/lazynet/lazy-harness/commit/eed42f3c117d7c45c5bf313f937371c71de5f4f6))

## [0.37.0](https://github.com/lazynet/lazy-harness/compare/v0.36.1...v0.37.0) (2026-08-15)


### Documentation

* restore the features omitted from the 0.36.1 changelog ([#156](https://github.com/lazynet/lazy-harness/issues/156)) ([b243aaa](https://github.com/lazynet/lazy-harness/commit/b243aaac6f49cde5491d76c1e11f3f41ec888c15))

## [0.36.1](https://github.com/lazynet/lazy-harness/compare/v0.36.0...v0.36.1) (2026-08-15)


### Features

* sample the herdr context gauge mid-turn on `PostToolUse`, throttled per pane ([#154](https://github.com/lazynet/lazy-harness/issues/154)) ([6d9d662](https://github.com/lazynet/lazy-harness/commit/6d9d6626f9496cb5375f054ebbc554d3031b69b3))
* accept per-event matchers in the builtin hook registry ([#154](https://github.com/lazynet/lazy-harness/issues/154)) ([6d9d662](https://github.com/lazynet/lazy-harness/commit/6d9d6626f9496cb5375f054ebbc554d3031b69b3))


### Bug Fixes

* give the herdr context gauge a lifecycle and a mid-turn sample ([#154](https://github.com/lazynet/lazy-harness/issues/154)) ([6d9d662](https://github.com/lazynet/lazy-harness/commit/6d9d6626f9496cb5375f054ebbc554d3031b69b3))

## [0.36.0](https://github.com/lazynet/lazy-harness/compare/v0.35.0...v0.36.0) (2026-08-14)


### Features

* own third-party hooks in config instead of overwriting them ([#152](https://github.com/lazynet/lazy-harness/issues/152)) ([d0f8289](https://github.com/lazynet/lazy-harness/commit/d0f8289dd96cda510a37697d43c48bfb5590d796)), closes [#150](https://github.com/lazynet/lazy-harness/issues/150) [#151](https://github.com/lazynet/lazy-harness/issues/151)

## [0.35.0](https://github.com/lazynet/lazy-harness/compare/v0.34.0...v0.35.0) (2026-08-14)


### Features

* add herdr-context-gauge hook to surface worker context size ([#148](https://github.com/lazynet/lazy-harness/issues/148)) ([aa00b99](https://github.com/lazynet/lazy-harness/commit/aa00b99aaae1a9940f1f657488eb7b641fb074af))

## [0.34.0](https://github.com/lazynet/lazy-harness/compare/v0.33.4...v0.34.0) (2026-08-13)


### Features

* add post-tool-use-ansible-lint hook ([#146](https://github.com/lazynet/lazy-harness/issues/146)) ([64db18c](https://github.com/lazynet/lazy-harness/commit/64db18c3d989e3d83cebf931760247381927c491))


### Bug Fixes

* harden post_tool_use_format hook against non-dict tool_input and OSError ([#147](https://github.com/lazynet/lazy-harness/issues/147)) ([f10e5b3](https://github.com/lazynet/lazy-harness/commit/f10e5b39e1c5afc076f346f77a34251670ba5f9d))


### Documentation

* **specs:** add agent surface adoption design ([433dbaa](https://github.com/lazynet/lazy-harness/commit/433dbaa5304c3e7ccd941124af347f03c873fc11))
* **specs:** add agent surface adoption implementation plan ([3b87be7](https://github.com/lazynet/lazy-harness/commit/3b87be7162e4bbc11d030aec4937cb2940eb2276))
* **specs:** correct session counts for compound-loop sidecars ([fbc366b](https://github.com/lazynet/lazy-harness/commit/fbc366b091b7b9ea2e55c79baefe89860c61fc9c))
* **specs:** triage the 49 unused skills across the estate ([0ded7e0](https://github.com/lazynet/lazy-harness/commit/0ded7e098c9214047d11202c6e310ae6f5fa22c8))
* **specs:** widen agent surface audit to 18 repos ([19f1b70](https://github.com/lazynet/lazy-harness/commit/19f1b70db447c9a09df4dc9baf464216e6d51866))

## [0.33.4](https://github.com/lazynet/lazy-harness/compare/v0.33.3...v0.33.4) (2026-08-13)


### Bug Fixes

* **cli:** resolve project memory dir from the main checkout ([#144](https://github.com/lazynet/lazy-harness/issues/144)) ([c5aa954](https://github.com/lazynet/lazy-harness/commit/c5aa9542a817f5006aad50788cb9cc7163c616c6))
* **doctor:** report MEMORY.md byte size alongside line count ([#142](https://github.com/lazynet/lazy-harness/issues/142)) ([f32ed74](https://github.com/lazynet/lazy-harness/commit/f32ed74912ef2a5ff7b4b7046b08ecd5cecd4dca))

## [0.33.3](https://github.com/lazynet/lazy-harness/compare/v0.33.2...v0.33.3) (2026-08-13)


### Bug Fixes

* **hooks:** warn on MEMORY.md byte size, not just line count ([#140](https://github.com/lazynet/lazy-harness/issues/140)) ([b1e604a](https://github.com/lazynet/lazy-harness/commit/b1e604af4f94d0dd7d353a6534c7255e27e3914b))

## [0.33.2](https://github.com/lazynet/lazy-harness/compare/v0.33.1...v0.33.2) (2026-08-13)


### Bug Fixes

* stop the .env rule from blocking greps for process.env ([#138](https://github.com/lazynet/lazy-harness/issues/138)) ([6ebb2f8](https://github.com/lazynet/lazy-harness/commit/6ebb2f8fb6d5ec0a63d149575c3dcfbd6abe5551))

## [0.33.1](https://github.com/lazynet/lazy-harness/compare/v0.33.0...v0.33.1) (2026-08-12)


### Bug Fixes

* stop warning about the &lt;synthetic&gt; model placeholder ([#136](https://github.com/lazynet/lazy-harness/issues/136)) ([0ce1b48](https://github.com/lazynet/lazy-harness/commit/0ce1b48785ab5dd01f13e64c8c3044915e4123e6))

## [0.33.0](https://github.com/lazynet/lazy-harness/compare/v0.32.0...v0.33.0) (2026-08-12)


### Features

* compose token/cost breakdowns by profile, period and model ([#134](https://github.com/lazynet/lazy-harness/issues/134)) ([fe74c52](https://github.com/lazynet/lazy-harness/commit/fe74c524196fafe01c2a6399be67fb688abaa152))

## [0.32.0](https://github.com/lazynet/lazy-harness/compare/v0.31.0...v0.32.0) (2026-08-12)


### Features

* add lh knowledge graph to keep code graphs fresh ([#132](https://github.com/lazynet/lazy-harness/issues/132)) ([987da98](https://github.com/lazynet/lazy-harness/commit/987da987c8c36ac6c1df07f26dbc48a7636f8f2a))

## [0.31.0](https://github.com/lazynet/lazy-harness/compare/v0.30.0...v0.31.0) (2026-08-12)


### Features

* warn before an unbounded read of a large file ([#129](https://github.com/lazynet/lazy-harness/issues/129)) ([c256666](https://github.com/lazynet/lazy-harness/commit/c256666d28379d1292d2551efe2b84d38fc481c7))


### Bug Fixes

* anchor distilled memory to the main working tree ([#128](https://github.com/lazynet/lazy-harness/issues/128)) ([96b485f](https://github.com/lazynet/lazy-harness/commit/96b485f414b3279e12fd319086ac2164267e1b67))
* keep the code-structure summary out of the truncation cliff ([#130](https://github.com/lazynet/lazy-harness/issues/130)) ([7e36f72](https://github.com/lazynet/lazy-harness/commit/7e36f7262f914a5d81a399a4e763006d0ccf12ba))
* make lh metrics status report the local sink ([#125](https://github.com/lazynet/lazy-harness/issues/125)) ([12ea676](https://github.com/lazynet/lazy-harness/commit/12ea676ea3de97b6f9a8cec0dcffa9edc2e64216))


### Documentation

* merge accepted compound-loop proposals into the governance surface ([#131](https://github.com/lazynet/lazy-harness/issues/131)) ([5e23b60](https://github.com/lazynet/lazy-harness/commit/5e23b60c1a29b2e4f619dccbc915a7e7f65cdc63))

## [0.30.0](https://github.com/lazynet/lazy-harness/compare/v0.26.0...v0.30.0) (2026-08-12)


### ⚠ BREAKING CHANGES

* replace knowledge.path with a marker-described knowledge store root

### Features

* add knowledge store marker with strict validation ([8c99c21](https://github.com/lazynet/lazy-harness/commit/8c99c21c45396b51b7efe995e5c46fd9cbcedad1))
* add knowledge store push cycle ([1a8cf8a](https://github.com/lazynet/lazy-harness/commit/1a8cf8afff6f212f2b1520f28e5e7306820def2f))
* add lh knowledge init, path and push ([5aee648](https://github.com/lazynet/lazy-harness/commit/5aee6481f6a44faa15521c330c55ac6a22abd646))
* migrate knowledge config to the root shape ([c260531](https://github.com/lazynet/lazy-harness/commit/c2605311f17753b34b57b44beea6a28fb3067959))
* replace knowledge.path with a marker-described knowledge store root ([811354f](https://github.com/lazynet/lazy-harness/commit/811354f10f46be896a6a824545c58775cec5c8d6))
* suffix learning filenames with the origin host ([652705f](https://github.com/lazynet/lazy-harness/commit/652705fd65dee5a11852cc036ec7fee771ea7311))


### Bug Fixes

* make lh init write a loadable config and a marked store ([ace4c4a](https://github.com/lazynet/lazy-harness/commit/ace4c4aececdc1edfc89aedec6c857b7d766b210))


### Refactors

* name the learning month bucket for what it is ([957fef8](https://github.com/lazynet/lazy-harness/commit/957fef88ea7d677b636eb1ce8286ecd586da840b))


### Documentation

* describe the knowledge store and its CLI ([76fcb97](https://github.com/lazynet/lazy-harness/commit/76fcb97bdf9f77c26f5076c8278b7f94501f1441))
* **specs:** add knowledge store extraction design ([a99514a](https://github.com/lazynet/lazy-harness/commit/a99514a013901665e8fd345a1fe0b05245c9e2a2))
* **specs:** add knowledge store extraction implementation plan ([8f155a6](https://github.com/lazynet/lazy-harness/commit/8f155a6f4ae3ac028cedb2c4fe7b65748c0f55e8))


### CI

* keep release-please on 0.x until 1.0 is declared ([#124](https://github.com/lazynet/lazy-harness/issues/124)) ([5f6322f](https://github.com/lazynet/lazy-harness/commit/5f6322f81d8ca466f7c95060323b112f0bc52da4))

## [0.26.0](https://github.com/lazynet/lazy-harness/compare/v0.25.0...v0.26.0) (2026-08-10)


### Features

* wire the Graphify MCP server and drop the phantom rebuild flag ([#121](https://github.com/lazynet/lazy-harness/issues/121)) ([038317d](https://github.com/lazynet/lazy-harness/commit/038317d564b8d73c09cadf9b42d700f41922e292))


### Bug Fixes

* repair three harness failures that reported success ([#120](https://github.com/lazynet/lazy-harness/issues/120)) ([e439167](https://github.com/lazynet/lazy-harness/commit/e439167c59787c85753c583f732b722bc75f1382))


### Documentation

* **adrs:** annotate ADR-013 with its partial implementation state ([62f150f](https://github.com/lazynet/lazy-harness/commit/62f150f9631c3b202e8f51c57bd5c1ab00a4d92b))

## [0.25.0](https://github.com/lazynet/lazy-harness/compare/v0.24.3...v0.25.0) (2026-08-08)


### Features

* add coherence-audit slash command for semantic spec drift ([259075f](https://github.com/lazynet/lazy-harness/commit/259075fda497c430b6e67caab65851ef41623f83))


### Bug Fixes

* add timeout to engram save subprocess call ([35be7d6](https://github.com/lazynet/lazy-harness/commit/35be7d6f6dd5e35cdbe29e8568b5ee0518133ff7))
* fail loudly on unimplemented scheduler backends ([735b19b](https://github.com/lazynet/lazy-harness/commit/735b19b8a0d88d29911d527bbd6d69e66eb3169e))
* **hooks:** sync CLAUDE.md segments when no config.toml exists ([e3dfe0d](https://github.com/lazynet/lazy-harness/commit/e3dfe0dda2dd88dbe3db2c62c499ace18de93cdc))
* make metrics outbox claim atomic with WAL and BEGIN IMMEDIATE ([08365e5](https://github.com/lazynet/lazy-harness/commit/08365e5bbf776353af1dc6549dbefc740fb11585))
* parse slim_handoff_enabled from compound_loop config ([cbf884a](https://github.com/lazynet/lazy-harness/commit/cbf884ac202c6c9092075c34e58f292b42fe7d13))
* roll back the outbox claim transaction on failure ([63accbd](https://github.com/lazynet/lazy-harness/commit/63accbd16b402344f2f05eba655d10204f80f038))


### Documentation

* correct the scheduler passage in the CLI reference ([fc6b139](https://github.com/lazynet/lazy-harness/commit/fc6b13964fab5d6073dc23c6a44814d5b04df155))
* document compound_loop.slim_handoff_enabled ([e5db3d3](https://github.com/lazynet/lazy-harness/commit/e5db3d35d68cf3c48cfb109e0edb21605af58908))
* **getting-started:** fix drifted lh profile/scheduler subcommands ([09e2f08](https://github.com/lazynet/lazy-harness/commit/09e2f08e4b6a346a2e7571767b553476af6bcbdf))
* match Piece A spec to the shipped docs-wide CLI coherence scan ([e7494f1](https://github.com/lazynet/lazy-harness/commit/e7494f1bac8c7ec8af96403b4026ac5493a87a6b))
* **reference:** fix internally-contradictory hooks example in config.md ([363f68b](https://github.com/lazynet/lazy-harness/commit/363f68b501f9b38977aa94a303b0b75d193178ea))
* **specs:** add coherence-audit design ([913aa9f](https://github.com/lazynet/lazy-harness/commit/913aa9fbe78d677feda433ee2ba3c16dad6865e1))
* state that only the launchd scheduler backend installs jobs ([25eb0dc](https://github.com/lazynet/lazy-harness/commit/25eb0dc8b75316065d2d8c24bb8ce5b76ade31fd))
* use the real ADR status form in the coherence-audit command ([b6b7578](https://github.com/lazynet/lazy-harness/commit/b6b7578796bd3b368fe35efeb16cf9f9e3c3fc42))

## [0.24.3](https://github.com/lazynet/lazy-harness/compare/v0.24.2...v0.24.3) (2026-08-08)


### Bug Fixes

* require both recursion and force flags in rm block rule ([#113](https://github.com/lazynet/lazy-harness/issues/113)) ([dee487d](https://github.com/lazynet/lazy-harness/commit/dee487dfe8693f722311fc1199b493b975425966))

## [0.24.2](https://github.com/lazynet/lazy-harness/compare/v0.24.1...v0.24.2) (2026-07-29)


### Bug Fixes

* add claude-opus-5 to default pricing table ([#111](https://github.com/lazynet/lazy-harness/issues/111)) ([ba15411](https://github.com/lazynet/lazy-harness/commit/ba1541119cfa5895e6800a0521264a1803bf5a03))

## [0.24.1](https://github.com/lazynet/lazy-harness/compare/v0.24.0...v0.24.1) (2026-07-14)


### Bug Fixes

* preserve agent process name across argv0 and Linux comm ([#107](https://github.com/lazynet/lazy-harness/issues/107)) ([9cb7d0f](https://github.com/lazynet/lazy-harness/commit/9cb7d0f11903e7c2233a1ea428cd8439be839384))


### Documentation

* **specs:** add ADR-034 OKF knowledge producer proposal ([#105](https://github.com/lazynet/lazy-harness/issues/105)) ([c812643](https://github.com/lazynet/lazy-harness/commit/c812643e35fd4fdf0e69ab93acc4cc8e84e4d2bf))

## [0.24.0](https://github.com/lazynet/lazy-harness/compare/v0.23.1...v0.24.0) (2026-07-02)


### Features

* add claude-sonnet-5 to default pricing ([#103](https://github.com/lazynet/lazy-harness/issues/103)) ([8100774](https://github.com/lazynet/lazy-harness/commit/810077471fa51f9a0c5bcb9a27b6deb30596accf))

## [0.23.1](https://github.com/lazynet/lazy-harness/compare/v0.23.0...v0.23.1) (2026-06-20)


### Bug Fixes

* recognize literal scalar context blocks in qmd context-gen ([#101](https://github.com/lazynet/lazy-harness/issues/101)) ([d5ad572](https://github.com/lazynet/lazy-harness/commit/d5ad572b7f57cc8265e8b828ebc73983d26b5084))

## [0.23.0](https://github.com/lazynet/lazy-harness/compare/v0.22.1...v0.23.0) (2026-06-11)


### Features

* claude-md proposals lifecycle (accept/reject with immunity registry) ([#99](https://github.com/lazynet/lazy-harness/issues/99)) ([c1b4344](https://github.com/lazynet/lazy-harness/commit/c1b4344aab647b0eac16c0550c3122573617425f))
* failure promotion and memory hygiene checks ([#100](https://github.com/lazynet/lazy-harness/issues/100)) ([a90b43c](https://github.com/lazynet/lazy-harness/commit/a90b43c0b29046de873a682be3ca7aab147133d2))
* LLM backend abstraction (ADR-033) ([#97](https://github.com/lazynet/lazy-harness/issues/97)) ([9f2119b](https://github.com/lazynet/lazy-harness/commit/9f2119b48ae4ea241459623492e646ecb0682215))
* surface pending claude-md proposals despite context budget ([#98](https://github.com/lazynet/lazy-harness/issues/98)) ([a831ec4](https://github.com/lazynet/lazy-harness/commit/a831ec42f7f583c929dc74f87522c2ce36239132))


### Bug Fixes

* add claude-fable-5 to pricing table ([#94](https://github.com/lazynet/lazy-harness/issues/94)) ([7d611ad](https://github.com/lazynet/lazy-harness/commit/7d611ad6d5f44c22f68be6292898c9618bfce3b2))


### Refactors

* close ADR-032 agent-adapter leaks (L3/L4) ([#96](https://github.com/lazynet/lazy-harness/issues/96)) ([cab4ca2](https://github.com/lazynet/lazy-harness/commit/cab4ca26590fafe7a3b8091b5f67b1035e2e4b85))


### Documentation

* add docs-coherence and persistence-verification rules ([#93](https://github.com/lazynet/lazy-harness/issues/93)) ([5f48cf6](https://github.com/lazynet/lazy-harness/commit/5f48cf62197233c145f2700e4f2b5f81919a2d75))
* **specs:** add 2026-06-11 adequacy plan with execution log ([5e9a2fc](https://github.com/lazynet/lazy-harness/commit/5e9a2fc9d9089351e8cb15e75cda838dc5a4c371))

## [0.22.1](https://github.com/lazynet/lazy-harness/compare/v0.22.0...v0.22.1) (2026-06-02)


### Bug Fixes

* accumulate metrics across transcript retention ([#91](https://github.com/lazynet/lazy-harness/issues/91)) ([cbb1fff](https://github.com/lazynet/lazy-harness/commit/cbb1fffa4663df4717c5a7b0c2431c5818bbcd2d))
* add claude-opus-4-8 to pricing table ([#90](https://github.com/lazynet/lazy-harness/issues/90)) ([d4532f7](https://github.com/lazynet/lazy-harness/commit/d4532f75174dd08981c360bf9e59541bed6af5c0))

## [0.22.0](https://github.com/lazynet/lazy-harness/compare/v0.21.0...v0.22.0) (2026-05-29)


### Features

* close agent adapter protocol gaps (ADR-032) ([#88](https://github.com/lazynet/lazy-harness/issues/88)) ([f29460b](https://github.com/lazynet/lazy-harness/commit/f29460b4284ade49525e157d119f396c2cef6203))

## [0.21.0](https://github.com/lazynet/lazy-harness/compare/v0.20.0...v0.21.0) (2026-05-21)


### Features

* capture insights deterministically in compound-loop ([#86](https://github.com/lazynet/lazy-harness/issues/86)) ([9a5e9a3](https://github.com/lazynet/lazy-harness/commit/9a5e9a3be9d409b5307cf859bcb17e20d5a023f0))
* default hooks merge layer in lh deploy ([#87](https://github.com/lazynet/lazy-harness/issues/87)) ([0dc4259](https://github.com/lazynet/lazy-harness/commit/0dc425968ce8d7c3f87d1e66454daa392daaf2db))


### Documentation

* align cli/hooks/memory references with 0.20.0 features ([57efe48](https://github.com/lazynet/lazy-harness/commit/57efe48dee5d942c5b4ff09a58d9964a0bf7be8a))

## [0.20.0](https://github.com/lazynet/lazy-harness/compare/v0.19.0...v0.20.0) (2026-05-20)


### Features

* compound-loop emits claude-md proposals ([#82](https://github.com/lazynet/lazy-harness/issues/82)) ([cdfe8bd](https://github.com/lazynet/lazy-harness/commit/cdfe8bde7822e48c3b4d22eab75e194e9f5679af))
* context_inject surfaces claude-md proposals ([#83](https://github.com/lazynet/lazy-harness/issues/83)) ([c0f0519](https://github.com/lazynet/lazy-harness/commit/c0f0519b82ef8e1f8a7516263c53a80399976b46))
* tail decisions/failures jsonl in PreCompact summary ([#81](https://github.com/lazynet/lazy-harness/issues/81)) ([4b9a4f5](https://github.com/lazynet/lazy-harness/commit/4b9a4f55d63e07a86b282e2108de388fc03073b5))

## [0.19.0](https://github.com/lazynet/lazy-harness/compare/v0.18.0...v0.19.0) (2026-05-05)


### Features

* lh profile sync-claude-md + auto-sync hook ([#76](https://github.com/lazynet/lazy-harness/issues/76)) ([d6e0b3b](https://github.com/lazynet/lazy-harness/commit/d6e0b3b0b74af1c0fe228d1b9a8874e20c339945))

## [0.18.0](https://github.com/lazynet/lazy-harness/compare/v0.17.1...v0.18.0) (2026-05-05)


### Features

* graphify integration in context_inject (G4) ([#71](https://github.com/lazynet/lazy-harness/issues/71)) ([b585a10](https://github.com/lazynet/lazy-harness/commit/b585a109f9f1cc74637a43f831abe00fe4b56517))
* lh memory consolidate command (G2 consolidator) ([#73](https://github.com/lazynet/lazy-harness/issues/73)) ([504b075](https://github.com/lazynet/lazy-harness/commit/504b0759cb85a1e330000ce9aea3f3bd85512213))
* lh memory cross-profile-check command (G7) ([#72](https://github.com/lazynet/lazy-harness/issues/72)) ([9f84e17](https://github.com/lazynet/lazy-harness/commit/9f84e1780bb554c5c0a8c16123a6d97b512859d8))
* MEMORY.md size warning hook with per-script matcher (G2) ([#68](https://github.com/lazynet/lazy-harness/issues/68)) ([ef082ca](https://github.com/lazynet/lazy-harness/commit/ef082ca99f3e164e161a5b030377c300c8980b2c))
* slim_handoff fast-path when compound_loop gates block (G1) ([#69](https://github.com/lazynet/lazy-harness/issues/69)) ([1502019](https://github.com/lazynet/lazy-harness/commit/150201932b2a111c131bdd3455336d6880bc0991))
* surface dropped sections in context_inject truncation (G5) ([#67](https://github.com/lazynet/lazy-harness/issues/67)) ([5a0ab97](https://github.com/lazynet/lazy-harness/commit/5a0ab976a6b3460875d063878838987e0cf8af3a))
* surface QMD vault hits in context_inject (G3) ([#70](https://github.com/lazynet/lazy-harness/issues/70)) ([ded34be](https://github.com/lazynet/lazy-harness/commit/ded34be1bc52da9acda47926158029c415be9ce0))


### Documentation

* add ADR-030 memory stack glue layer (proposed) ([#65](https://github.com/lazynet/lazy-harness/issues/65)) ([607cfab](https://github.com/lazynet/lazy-harness/commit/607cfab1702a0d5f2db63092e447f1a4a1292879))
* ADR-030 → accepted (all 7 components shipped) ([#75](https://github.com/lazynet/lazy-harness/issues/75)) ([cf518e3](https://github.com/lazynet/lazy-harness/commit/cf518e3eb84e4d168a0ace16006566ad36c43aaa))
* glue-layer paragraph in overview + ADR-027 annotation (G6) ([#74](https://github.com/lazynet/lazy-harness/issues/74)) ([3477061](https://github.com/lazynet/lazy-harness/commit/347706174bb7407f296eb38051f044a1d97735a5))

## [0.17.1](https://github.com/lazynet/lazy-harness/compare/v0.17.0...v0.17.1) (2026-05-04)


### Documentation

* **public:** expand coverage of security hooks, engram-persist, graphify, metrics sinks, and missing config sections ([e3cc60c](https://github.com/lazynet/lazy-harness/commit/e3cc60cd5bf56974ac32e7347e0ef8f55828c097))

## [0.17.0](https://github.com/lazynet/lazy-harness/compare/v0.16.0...v0.17.0) (2026-05-04)


### Features

* add engram-persist health block to lh doctor ([#62](https://github.com/lazynet/lazy-harness/issues/62)) ([adcb379](https://github.com/lazynet/lazy-harness/commit/adcb379d887f27506984a0527edc5b3b31a575e4))

## [0.16.0](https://github.com/lazynet/lazy-harness/compare/v0.15.4...v0.16.0) (2026-05-04)


### Features

* **hooks:** engram-persist deterministic Stop-time mirror ([#60](https://github.com/lazynet/lazy-harness/issues/60)) ([f907107](https://github.com/lazynet/lazy-harness/commit/f907107ac76d71dafb172c2e1a4ccd6fc84d9927))

## [0.15.4](https://github.com/lazynet/lazy-harness/compare/v0.15.3...v0.15.4) (2026-05-04)


### Documentation

* cover lh config wizards, doctor features section, and mcp deploy seam (ADRs 024-026) ([f8435c6](https://github.com/lazynet/lazy-harness/commit/f8435c6701dee7ba26d73b072fa65d9bcf699b31))
* fix qmd upstream url, broken backlog link, and personal paths in examples ([e19662f](https://github.com/lazynet/lazy-harness/commit/e19662f2c67ba2032904c4f9a7dee1bf28c34f99))
* rewrite memory model to canonical five-layer view (ADR-027) ([379034b](https://github.com/lazynet/lazy-harness/commit/379034b9aa20213c109c6ecf28a95beebb4883e4))

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
