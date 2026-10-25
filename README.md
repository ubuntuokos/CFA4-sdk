# CFA4 SDK

A CFA4 videószerkesztő AI-workereinek nyilvános szerződése: a worker-protokoll, a
képesség-manifest sémája, és később a Rust és Python SDK. Licence **MIT OR Apache-2.0**, így
GPL-es és zárt, fizetős worker egyaránt építhet rá. A CFA4 maga (GPL-3.0-or-later) a
[CFA4-AI_modules](https://github.com/ubuntuokos/CFA4-AI_modules) repóban van, ez a repó nem
tartalmaz belőle kódot.

| Hely | Tartalom |
|---|---|
| [`docs/protocol.md`](docs/protocol.md) | A gazda és a worker közötti JSON-lines protokoll, 1. változat |
| [`schemas/protocol.schema.json`](schemas/protocol.schema.json) | A protokoll üzeneteinek JSON Schemája |
| [`schemas/manifest.schema.json`](schemas/manifest.schema.json) | A képesség-manifest (TOML) JSON Schemája |
| [`examples/`](examples) | Mintamanifestek és egy teljes mintabeszélgetés |
| [`crates/cfa4-ai-protocol`](crates/cfa4-ai-protocol) | Rust crate: üzenettípusok, érvényesség-ellenőrzés, JSON-lines kódolás, verzióegyeztetés |
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
2. `cfa4-ai-protocol` Rust crate (üzenettípusok, ellenőrzés, kódolás; ez a változat), majd
   Python csomag ugyanerre. Az osztott memória leképezése a CFA4 gazdaoldalára kerül.
3. Mintaworker ONNX Runtime-mal, amelyet a CFA4 a minimumgépen
   (`scripts/dev/run-minspec.sh`) tesztel.

## Licenc

A repóban lévő minden fájl MIT OR Apache-2.0 licencű, a felhasználó választása szerint
([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)). A forrásfájlok első soraiban
SPDX-fejléc van. GPL-es kód nem kerülhet ide.
