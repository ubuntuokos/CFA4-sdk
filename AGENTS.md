# CFA4 SDK – szabályok közreműködőknek és ügynököknek

1. **Licenc:** minden fájl MIT OR Apache-2.0. Forrásfájl első soraiban
   `SPDX-License-Identifier: MIT OR Apache-2.0`. GPL-es, AGPL-es vagy ismeretlen licencű kód
   nem kerülhet be, a CFA4-ből sem: a kódot frissen kell megírni. Ezt a
   `scripts/check-licence.sh` ellenőrzi.
2. **A protokoll és a sémák szerződés.** Minden változás új protokoll- vagy manifestverziót
   jelent (`docs/protocol.md` §5). A változás ugyanabban a commitban frissíti a sémát, a
   leírást, a mintákat és a teszteket.
3. **Minden minta érvényes, minden hibás minta elutasított.** Új üzenettípus vagy mező csak a
   `examples/` és a `tests/` bővítésével kerülhet be.
4. **Soha ne omoljon össze:** a későbbi SDK-kódra a CFA4 szabályai érvényesek (nincs
   `unwrap`/`panic!`, minden bemenet ellenséges, korlátos foglalás).
5. **Rust:** a `cfa4-ai-protocol` pontosan azt fogadja el, amit a séma: minden minta
   (`examples/messages/*.jsonl`) oda-vissza változatlan, minden hibás minta elutasított. Új
   függőség csak megengedő licenccel (`cargo deny check licenses`), `unsafe` tilos.
6. **Commit:** egy feladatazonosító commitonként (`S1: …`), csak zöld állapot.
