<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# cfa4-ai (Python)

A CFA4 AI-workerek Python SDK-ja, a [protokoll](../docs/protocol.md) 1. változatához. Nincs
függősége, így bármelyik modellkörnyezetbe (PyTorch, ONNX Runtime) ütközés nélkül telepíthető.
Csak Linuxon fut, mert a képkockák a `/dev/shm` osztott memóriájában utaznak.

```sh
pip install ./python
```

| Modul | Tartalom |
|---|---|
| `cfa4_ai.protocol` | `decode`, `encode`, `validate`, `MessageReader`, `negotiate`; pontosan azt fogadja el, amit a `schemas/protocol.schema.json` |
| `cfa4_ai.shm` | `MappedBuffer`: a gazda által létrehozott szegmens leképezése, határellenőrzéssel |
| `cfa4_ai.worker` | `Worker` alaposztály és `serve()`: kézfogás, betöltés, futtatás szálakon, megszakítás, hibakódok |

Egy worker a `Worker` alosztálya: megadja a `name`, `version` és `impls` mezőt, és megvalósítja
a `load` és a `run` metódust. A `run` a `job.inputs` és a `job.outputs` `memoryview`-ját kapja,
a `job.cancelled` jelzi a megszakítást, a `job.progress()` haladást küld. Minta:
[`examples/invert_worker.py`](examples/invert_worker.py).

A worker kódjában keletkező kivétel nem állítja le a hurkot, hanem `error` üzenet lesz belőle:

- a `WorkerError` megtartja a saját kódját;
- a memóriahiány (például a `torch.cuda.OutOfMemoryError`) `oom` lesz;
- a betöltéskor hiányzó fájl `model_missing` lesz;
- minden más `model_error` lesz.
