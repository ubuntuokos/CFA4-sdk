# CFA4 SDK

A CFA4 videószerkesztő AI-workereinek nyilvános szerződése: a worker-protokoll, a
képesség-manifest sémája, és később a Rust és Python SDK. Licence **MIT OR Apache-2.0**, így
GPL-es és zárt, fizetős worker egyaránt építhet rá. A CFA4 maga (GPL-3.0-or-later) a
[CFA4-AI_modules](https://github.com/ubuntuokos/CFA4-AI_modules) repóban van, ez a repó nem
tartalmaz belőle kódot.

| Hely | Tartalom |
|---|---|
| [`docs/protocol.md`](docs/protocol.md) | A gazda és a worker közötti JSON-lines protokoll, 2. változat (az 1. is érvényes) |
| [`schemas/protocol.schema.json`](schemas/protocol.schema.json) | A protokoll üzeneteinek JSON Schemája |
| [`schemas/manifest.schema.json`](schemas/manifest.schema.json) | A képesség-manifest (TOML) JSON Schemája, 3. változat (négy licencmező, rögzített súlyforrás) |
| [`schemas/host.schema.json`](schemas/host.schema.json) | Amit a CFA4 a saját felületének, CLI-jének és MCP-jének jelent: a jobállapotok (10 állapot) és a „mi futna és miért” útválasztási döntés |
| [`examples/`](examples) | Mintamanifestek, egy teljes mintabeszélgetés és gazdajelentések |
| [`crates/cfa4-ai-protocol`](crates/cfa4-ai-protocol) | Rust crate: üzenettípusok, érvényesség-ellenőrzés, JSON-lines kódolás, verzióegyeztetés |
| [`python/`](python) | Python csomag (`cfa4-ai`): ugyanez Pythonban, függőség nélkül, plusz osztott memória és worker-hurok, mintaworkerrel |
| [`tests/`](tests) | A sémák és a minták ellenőrzése |

## Ellenőrzés

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
bash scripts/check-licence.sh

cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo deny check licenses sources
```

## Tervezett lépések

1. Protokoll és manifest-séma (ez a változat).
2. `cfa4-ai-protocol` Rust crate (üzenettípusok, ellenőrzés, kódolás), és a `cfa4-ai` Python
   csomag a workerek oldalára (ez a változat): kódolás, ellenőrzés, osztott memória,
   worker-hurok.
3. Mintaworker ONNX Runtime-mal, amelyet a CFA4 a minimumgépen
   (`scripts/dev/run-minspec.sh`) tesztel.

## Licenc

A repóban lévő minden fájl MIT OR Apache-2.0 licencű, a felhasználó választása szerint
([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)). A forrásfájlok első soraiban
SPDX-fejléc van. GPL-es kód nem kerülhet ide.
