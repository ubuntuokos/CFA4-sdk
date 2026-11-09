# CFA4 AI worker-protokoll, 3. változat

> **Állapot:** javaslat, még egyetlen worker sem valósítja meg · **Utolsó átnézés:** 2026-11-08 ·
> **Változás:** major (3. változat: a CFA4-nek nincs fizetős része, ezért a licenckulcsos vízjel,
> az export utáni lépés, a használati korlátok és a `limit_reached` hibakód minden változatból
> kikerült; az 1. és a 2. változat ezek nélkül érvényes marad) ·
> **Séma:** [`schemas/protocol.schema.json`](../schemas/protocol.schema.json), a gazda felé
> mutatott állapotokhoz [`schemas/host.schema.json`](../schemas/host.schema.json)

A CFA4 (a „gazda”) az AI-modelleket külön worker-folyamatokban futtatja. Ez a leírás a gazda és
a worker közötti beszélgetést rögzíti. A worker bármilyen nyelven és bármilyen licenccel
megírható. A gazda a CFA4 GPL-3.0-or-later licencű része, ez a protokoll és az SDK viszont
MIT OR Apache-2.0 licencű, hogy bárki, bármilyen licenccel írhasson rá workert. A CFA4-nek nincs
fizetős része (tulajdonosi döntés, 2026-11-08): a protokollban nincs licenckulcs, vízjel vagy
használati korlát.

## 1. Csatorna

- **Indítás:** a gazda indítja a workert, és átadja neki a Unix socket elérési útját a
  `CFA4_AI_SOCKET` környezeti változóban. A socket egy 0700-as jogú könyvtárban van.
  TCP-portot a protokoll nem használ.
- **Üzenetek:** egy üzenet egy sor, UTF-8 JSON, a végén `\n`. Egy sor legfeljebb 1 MiB lehet,
  a gazda a hosszabbat `protocol` hibával eldobja.
- **Képkockák:** sosem utaznak a socketen. A gazda osztott memóriát foglal (`/dev/shm`,
  `/cfa4-ai-` előtaggal), az üzenetek csak hivatkoznak rá (`buffer`). A worker csak a kapott
  szegmenseket nyithatja meg. A gazda az eltolást és a hosszt a szegmens méretével ellenőrzi.
- **Azonosítók:** minden üzenetnek van `id` mezője, amely irányonként és kapcsolatonként
  egyedi. A válasz a `reply_to` mezőben nevezi meg a kérést.

## 2. Menet

```text
gazda                          worker
hello {protocol:{min,max}} ->
                           <- caps {protocol, worker, impls, limits, features}
load {impl, device}        ->
                           <- loaded {vram_mb}       vagy error
run {job, inputs, outputs} ->
                           <- progress … (nem kötelező)
                           <- result {outputs}       vagy error
cancel {job}               ->
                           <- error {code: cancelled}
unload {impl}              ->
                           <- stats {loaded}
shutdown                   ->  (a worker kilép, kód: 0)
```

- **Verzió:** a `caps.protocol` a gazda `hello.protocol` tartományába kell, hogy essen,
  különben a gazda lezárja a kapcsolatot. A worker a közös tartomány legmagasabb verzióját
  választja; 1. változatú `caps` nem tartalmazhatja a 2. változat mezőit.
- **Képességek** (2. változat): a `caps.features` sorolja fel, mit tud a worker a nem kötelező
  viselkedések közül. A gazda csak ezeket kínálja fel a felületen.

  | Érték | Jelentés | Ha hiányzik |
  |---|---|---|
  | `cancel` | a `cancel` a szakasz közepén is leállítja a futást | a gazda a szakasz végét várja meg (`cancelling` állapot) |
  | `progress` | a worker `progress` üzeneteket küld | a gazda csak szakaszonként jelez haladást |
  | `preview` | a `tier: "preview"` gyorsabb, kisebb minőségű futást jelent | a gazda nem kínál előnézeti futást |
  | `resume` | a job az utolsó kész szakasztól folytatható újraindítás után | a gazda elölről kezdi |
- **Kimenetek:** a `run` előre megnevezi a kimeneti puffereket. A worker ezekbe ír, a
  `result` pedig visszaadja őket. A hossz és a formátum nem változhat.
- **Szakaszolás:** hosszú klipnél a gazda szakaszokra bontja a feladatot (`chunk`).
  Megszakítani szakaszhatáron vagy lépéshatáron lehet, ahogy a manifest `behavior.cancellable`
  mezője megadja.
- **Eszköz:** a `device` értéke `"cpu"`, vagy a gazda által láthatóvá tett GPU-k egyikének
  indexe. A `caps.devices` sorolja fel, mit tud a worker. Így a részleges CPU-s kiürítés (§3, `oom`)
  és a nem AI-s, csak CPU-s worker is leírható, több GPU-s gépen pedig ugyanaz a worker több eszközt is
  kaphat.

## 3. Hibák

Az `error.code` értékei:

| Kód | Jelentés | Mit tesz a gazda |
|---|---|---|
| `oom` | elfogyott a VRAM | automatikusan csak eredményt nem változtató lépéssel próbálja újra (kisebb köteg, csempézés átfedéssel, szakaszolás, részleges kiürítés RAM-ba, vagy az 5. változatú manifest olyan útjára, amelynek `tolerance.automatic` értéke `true`); kisebb pontossághoz, kisebb felbontáshoz, másik futtatóhoz vagy `automatic = false` úthoz a felhasználó jóváhagyása kell (AI ADR 0008, 3. pont, 2026-11-07) |
| `invalid_input` | hibás bemenet vagy paraméter | nem próbálja újra, jelzi a felhasználónak |
| `model_error` | a modell futás közben hibázott | egyszer újrapróbálja |
| `model_missing` | a modellfájl hiányzik vagy rossz az ellenőrzőösszege | a felhasználót a modell beszerzésére kéri |
| `unsupported` | a worker nem ismeri az `impl`-t vagy a kérést | nem próbálja újra |
| `cancelled` | a gazda megszakította | nincs teendő |
| `protocol` | hibás üzenet | lezárja a kapcsolatot |
| `crash` | a worker belső hibája | újraindítja a workert |

A worker összeomlása nem omlaszthatja össze a CFA4-et. Ha a socket bezárul, a gazda minden
futó feladatot `crash` hibával zár le, és újraindítja a workert.

## 4. Nincs fizetős korlát és vízjel

A CFA4-nek nincs fizetős része (tulajdonosi döntés, 2026-11-08; CFA4-AI_modules ADR 0008,
8. pont). A protokollban ezért nincs licenckulcs, használati, időtartam- vagy felbontáskorlát,
licenckulcshoz kötött vízjel és export utáni lépés. A 2. változat `caps.post_export` és
`caps.limits.watermark_above_height` mezője, valamint a `caps.limits.max_duration_s`,
`caps.limits.max_output_height` mező és a `limit_reached` hibakód a 3. változattól egyik
verzióban sem fogadható el (egyetlen worker sem valósította meg őket). A `caps.limits` csak
erőforrás-adatot tartalmaz (`max_jobs`, `max_buffer_bytes`).

A `result.watermarked` megmarad: azt jelzi, hogy a worker látható jelölést tett a kimenetre egy
tartalmi szabály miatt (például az arccsere „AI által módosított” jelölése), nem fizetés miatt.

## 5. Változáskezelés

A séma szigorú (`additionalProperties: false`), így egy elírt mezőnév már a teszteken
kiderül. Ebből következik, hogy minden protokollváltozás, egy új, nem kötelező mező is, új
protokollverziót kap. A gazda egyszerre több verziót is támogathat, a közös verziót a
`hello`/`caps` kézfogás választja ki.

| Protokollverzió | Változás |
|---|---|
| 1 | Első változat |
| 2 | `caps.features` (a 2026-11-07-i `caps.post_export` és `caps.limits.watermark_above_height` a 3. változattal kikerült) |
| 3 | A CFA4-nek nincs fizetős része (2026-11-08): a `caps.post_export`, a `caps.limits.watermark_above_height`, `max_duration_s` és `max_output_height`, valamint a `limit_reached` hibakód minden változatból kikerült (4. pont). Egyébként azonos a 2. változattal. |

A manifest verzióját a `manifest_version` mező adja meg, és a séma minden támogatott verziót
elfogad:

| Verzió | Változás |
|---|---|
| 1 | Első változat: `AI-nnn` azonosítók, M1–M12 motorcsaládok |
| 2 | `capability.languages` (BCP 47 nyelvcímkék), `AU-nnn` azonosítók a hanglistához, M13–M15 motorcsaládok |
| 3 | A `license` négy mező (`code`, `dependencies`, `weights`, `dataset`), mindegyikben `spdx` és `commercial` (`yes`, `no`, `unknown`); a `weights` elemeiben kötelező a `url`, a rögzített `revision` és a `format` |
| 4 | A `resources.vram_mb` és a `resources.fps_hint` kulcsa lehet `any` (vagy `any@fp16` stb.) is: a képkockamérettől független érték hang- és szövegképességekhez. A licenc- és súlyszabály a 3. változaté. |
| 5 | Kötelező `paths`: az igazolt végrehajtási utak (eszköz, pontosság, offload, csempézés, mért VRAM, RAM és sebesség, a mérés helye, dátuma és a `run-minspec.sh` profilja). Pontosan egy a referencia-út; a többi `tolerance` mezőben adja meg, mennyire térhet el tőle (`exact`, `max_abs`, `psnr_db`, `boundary_ms`), és az `automatic` jelzi, hogy a gazda magától válthat-e rá. A licenc- és súlyszabály a 3., a kulcsszabály a 4. változaté. |
| 6 | Azonos az 5. változattal; az `edition` (`free`/`paid`) mező minden változatból kikerült, mert a CFA4-nek nincs fizetős része (2026-11-08). |

**Elérhetőség az 5. változattól** (AI ADR 0008, 3. pont, tulajdonosi döntés, 2026-11-07): egy
implementáció egy gépen akkor elérhető, ha legalább egy `paths` eleme elfér rajta a CFA4
AI-minimum (12 GB VRAM, 16 GB RAM) fölött. Ha csak lassabb út fér el, a gazda a `fps_hint`
alapján becsült időt mutat, és a felhasználó dönt. GPU nélküli gépen az AI nem támogatott; a
`cpu` út a GPU melletti másik igazolt út lehet.

**A 3–6. változat licencszabálya.** Az `spdx` SPDX-kifejezés, `LicenseRef-…` hivatkozás vagy
`NOASSERTION`, ha nem ismert. **A CFA4 modellt nem terjeszt, csak a modelleket használó
alkalmazást.** Az alkalmazás felhasználójának felelőssége, hogy az adott modell felhasználási
feltételeit megismerje, és a modellt első használatkor maga töltse le (a gazda letöltője az ő
kérésére, közvetlenül a forrásból, például Hugging Face-ről vagy GitHubról; a CFA4 tárhelyén súly
nincs). CFA4-AI_modules ADR 0008 (`docs/adr/ADR-0008-ai-processing-layer.md`, korábban ADR 0006),
2. pont, István döntése, 2026-11-07. Ebből következik:

- A `weights` és a `dataset` rész `NOASSERTION`, `unknown` vagy `no` értéke egyik workerben sem
  tiltja le az implementációt, a CFA4-gyel szállított GPL-es workerekben sem.
- A gazda megmutatja a négy licencrészt, és a felhasználónak implementációnként egyszer el kell
  fogadnia a figyelmeztetést az első letöltés előtt, a modell feltételeire mutató hivatkozással
  (`license.*.url`). Amíg nem fogadta el, a job `blocked` állapotban vár `license` okkal
  ([`host.schema.json`](../schemas/host.schema.json)); az elfogadás a projektben rögzül, a
  `weights` elemeinek hash-ével együtt, így új súlynál újra kérdez.
- Kereskedelmi kérésnél (`route_decision.request.commercial`) a gazda külön, erősebb
  figyelmeztetést ad, ha bármelyik rész `commercial` értéke `no` vagy `unknown`, de nem tilt.
- A `code` és a `dependencies` rész `NOASSERTION` vagy `unknown` értéke továbbra is blokkol: ezeket
  a worker kiadója szállítja, nem a felhasználó tölti le.

A `revision` pontos, megváltoztathatatlan változat (például commit-hash); `main`,
`master`, `latest` vagy `HEAD` nem fogadható el. Az első körben a gazda csak `onnx` és
`safetensors` formátumú súlyt tölt be; a pickle-alapú formátumokat (`pt`, `bin`, `ckpt`) a séma
leírja, de a gazda a PyTorch-kapuig `blocked` állapotba teszi.

## 6. Gazdajelentések

A [`schemas/host.schema.json`](../schemas/host.schema.json) nem a worker-protokoll része: azt írja
le, mit jelent a CFA4 a saját felületének, a CLI-nek, a vezérlőcsatornának és az MCP-nek.
Workerek ilyen üzenetet nem küldenek és nem kapnak. Két fajtája van:

- **`job_status`:** egy job állapota minden állapotváltás után, ahogy a tartós jobtárba kerül. Az
  állapotok: `scheduled` (későbbi indulásra ütemezve), `queued`, `preparing_model`,
  `waiting_for_resources`, `loading`, `running`, `paused` (ellenőrzőpont mentve, erőforrások
  felszabadítva, folytatható; 2. változat, 2026-11-07), `cancelling`, `succeeded`, `failed`, `cancelled`, `blocked`. Hibakód (`error`) csak `failed`,
  blokkolási ok (`blocked`) csak `blocked` állapotban lehet, a `watermarked` csak `succeeded`
  állapotban.
- **`route_decision`:** „mi futna és miért”. A jegyzék futtatás nélkül megmondja, melyik
  implementáció futna egy kérésre, és minden jelöltnél felsorolja, mely feltételen bukott el
  (`capability`, `language`, `license`, `model`, `format`, `runtime`, `device`, `vram`, `ram`,
  `resolution`), a szükséges és a meglévő értékkel. A `chosen` az első jelölt, amelyen minden
  feltétel teljesült, vagy `null`, ha egyik sem. Ugyanezek a feltételek adják a `blocked` job
  okait, így a felület mindkét helyen ugyanazt a mondatot mutatja.

| Gazdajelentés-verzió | Változás |
|---|---|
| 1 | Első változat: `job_status`, `route_decision` |
| 2 | `scheduled` és `paused` állapot (2026-11-07) |
| 3 | A `limit_reached` hibakód és a `route_decision` `watermark` becslése kikerült, mert a CFA4-nek nincs fizetős része (2026-11-08); a `watermarked` csak tartalmi jelölést jelent (4. pont) |
