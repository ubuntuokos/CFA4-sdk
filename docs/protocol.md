# CFA4 AI worker-protokoll, 1. változat

> **Állapot:** javaslat, még egyetlen worker sem valósítja meg · **Utolsó átnézés:** 2026-10-25 ·
> **Változás:** major (első változat) · **Séma:** [`schemas/protocol.schema.json`](../schemas/protocol.schema.json)

A CFA4 (a „gazda”) az AI-modelleket külön worker-folyamatokban futtatja. Ez a leírás a gazda és
a worker közötti beszélgetést rögzíti. A worker bármilyen nyelven és bármilyen licenccel
megírható. A gazda a CFA4 GPL-3.0-or-later licencű része, ez a protokoll és az SDK viszont
MIT OR Apache-2.0 licencű, ezért a zárt, fizetős workerek is szabadon használhatják.

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
                           <- caps {protocol, worker, impls, limits}
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
  különben a gazda lezárja a kapcsolatot.
- **Kimenetek:** a `run` előre megnevezi a kimeneti puffereket. A worker ezekbe ír, a
  `result` pedig visszaadja őket. A hossz és a formátum nem változhat.
- **Szakaszolás:** hosszú klipnél a gazda szakaszokra bontja a feladatot (`chunk`).
  Megszakítani szakaszhatáron vagy lépéshatáron lehet, ahogy a manifest `behavior.cancellable`
  mezője megadja.
- **Eszköz:** a `device` értéke `"cpu"`, vagy a gazda által láthatóvá tett GPU-k egyikének
  indexe. A `caps.devices` sorolja fel, mit tud a worker. Így a CPU-s visszalépés (§3, `oom`)
  és a csak CPU-s worker is leírható, több GPU-s gépen pedig ugyanaz a worker több eszközt is
  kaphat.

## 3. Hibák

Az `error.code` értékei:

| Kód | Jelentés | Mit tesz a gazda |
|---|---|---|
| `oom` | elfogyott a VRAM | visszalép: kisebb felbontás, csempézés, kisebb pontosság, végül CPU |
| `invalid_input` | hibás bemenet vagy paraméter | nem próbálja újra, jelzi a felhasználónak |
| `model_error` | a modell futás közben hibázott | egyszer újrapróbálja |
| `model_missing` | a modellfájl hiányzik vagy rossz az ellenőrzőösszege | a felhasználót a modell beszerzésére kéri |
| `unsupported` | a worker nem ismeri az `impl`-t vagy a kérést | nem próbálja újra |
| `limit_reached` | a fizetős worker saját korlátja (időtartam, kimeneti felbontás) | jelzi a felhasználónak |
| `cancelled` | a gazda megszakította | nincs teendő |
| `protocol` | hibás üzenet | lezárja a kapcsolatot |
| `crash` | a worker belső hibája | újraindítja a workert |

A worker összeomlása nem omlaszthatja össze a CFA4-et. Ha a socket bezárul, a gazda minden
futó feladatot `crash` hibával zár le, és újraindítja a workert.

## 4. Korlátok a fizetős workerekben

A `caps.limits.max_duration_s` és a `caps.limits.max_output_height` mező tájékoztató jellegű: a
korlátot a worker maga tartatja be, és túllépéskor `limit_reached` hibát küld. A GPL-es gazda
semmilyen korlátot nem tartalmaz és nem kényszerít ki.

## 5. Változáskezelés

A séma szigorú (`additionalProperties: false`), így egy elírt mezőnév már a teszteken
kiderül. Ebből következik, hogy minden protokollváltozás, egy új, nem kötelező mező is, új
protokollverziót kap. A gazda egyszerre több verziót is támogathat, a közös verziót a
`hello`/`caps` kézfogás választja ki.

A manifest verzióját a `manifest_version` mező adja meg, és a séma minden támogatott verziót
elfogad:

| Verzió | Változás |
|---|---|
| 1 | Első változat: `AI-nnn` azonosítók, M1–M12 motorcsaládok |
| 2 | `capability.languages` (BCP 47 nyelvcímkék), `AU-nnn` azonosítók a hanglistához, M13–M15 motorcsaládok |
