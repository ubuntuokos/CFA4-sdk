# CFA4 AI worker-protokoll, 2. változat

> **Állapot:** javaslat, még egyetlen worker sem valósítja meg · **Utolsó átnézés:** 2026-10-30 ·
> **Változás:** minor (2. változat: `caps.features`, `caps.post_export`,
> `caps.limits.watermark_above_height`; az 1. változat érvényes marad) ·
> **Séma:** [`schemas/protocol.schema.json`](../schemas/protocol.schema.json), a gazda felé
> mutatott állapotokhoz [`schemas/host.schema.json`](../schemas/host.schema.json)

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

## 4. Korlátok és vízjel a fizetős workerekben

A `caps.limits.max_duration_s` és a `caps.limits.max_output_height` mező tájékoztató jellegű: a
korlátot a worker maga tartatja be, és túllépéskor `limit_reached` hibát küld. A GPL-es gazda
semmilyen korlátot nem tartalmaz és nem kényszerít ki.

**Vízjel** (2. változat). A `caps.limits.watermark_above_height` azt mondja meg, hogy licenckulcs
nélkül ennél magasabb kimenetre a worker látható vízjelet tesz; a CFA4 ingyenes határa 2K
(DCI, 2048×1080), ezért ennek értéke 1080. A gazda ebből előre megmondja a felületen, hogy a
kimenet vízjeles lesz, a `result.watermarked` pedig utólag jelzi. A vízjel képét és helyét a
worker adja, a gazda nem rajzol semmit. A CFA4 zárt workereiben a vízjel a CFA logó: a kép jobb
felső sarkában, 50%-os átlátszósággal, minden képkockán; magassága a képmagasság 8%-a, a jobb
felső sarka a jobb és a felső képszéltől a képméret 5%-ára van (EBU R 95 grafikai biztonsági sáv).

**Export utáni lépés** (2. változat). Ha a worker megadja a `caps.post_export` mezőt (az
`impls` egyik elemét), a gazda exportkor minden olyan kész képkockát, amelyen ennek a workernek a
kimenete látszik, egy szokásos `run` üzenettel visszaküld neki ezzel az `impl`-lel, mielőtt a fájl
elkészül. A `run` mezői:

- `inputs.src` és `outputs.out`: a kész exportkocka, azonos geometriával és formátummal;
- `tier`: `"final"`;
- `params.sources`: azoknak a joboknak a listája, amelyek kimenete a kockán van, elemenként
  `job` (a jobazonosító), `rect` (`[x, y, szélesség, magasság]` pixelben, a kockán belül),
  `crop` (a kimenet látható része a saját képén, szintén `[x, y, szélesség, magasság]`) és
  `frame` (a kimenet képkockájának indexe).

A worker maga dönt arról, mit tesz a kockával; a CFA4 vízjeles workere ellenőrzi, hogy a logó
sarka látható-e, és ha kitakarták, kivágták vagy a nagyítás miatt kiesett, a teljes képre tesz
vízjelet. A gazda ebben a lépésben semmit sem tilt és semmit sem ellenőriz: csak továbbítja a
kockát, és azt írja a fájlba, amit visszakap. Ha a worker nem fut, nem érhető el vagy hibával
válaszol, az export hibával leáll, mert a kimenet a worker feltétele nélkül nem készülhet el.

## 5. Változáskezelés

A séma szigorú (`additionalProperties: false`), így egy elírt mezőnév már a teszteken
kiderül. Ebből következik, hogy minden protokollváltozás, egy új, nem kötelező mező is, új
protokollverziót kap. A gazda egyszerre több verziót is támogathat, a közös verziót a
`hello`/`caps` kézfogás választja ki.

| Protokollverzió | Változás |
|---|---|
| 1 | Első változat |
| 2 | `caps.features`, `caps.post_export`, `caps.limits.watermark_above_height` |

A manifest verzióját a `manifest_version` mező adja meg, és a séma minden támogatott verziót
elfogad:

| Verzió | Változás |
|---|---|
| 1 | Első változat: `AI-nnn` azonosítók, M1–M12 motorcsaládok |
| 2 | `capability.languages` (BCP 47 nyelvcímkék), `AU-nnn` azonosítók a hanglistához, M13–M15 motorcsaládok |
| 3 | A `license` négy mező (`code`, `dependencies`, `weights`, `dataset`), mindegyikben `spdx` és `commercial` (`yes`, `no`, `unknown`); a `weights` elemeiben kötelező a `url`, a rögzített `revision` és a `format` |

**A 3. változat licencszabálya.** Az `spdx` SPDX-kifejezés, `LicenseRef-…` hivatkozás vagy
`NOASSERTION`, ha nem ismert. A gazda az olyan implementációt, amelynek bármelyik mezőjében
`NOASSERTION` vagy `unknown` áll, nem kínálja fel, és az ilyen job `blocked` állapotba kerül
([`host.schema.json`](../schemas/host.schema.json), `license` ok). A `revision` pontos, megváltoztathatatlan változat (például commit-hash); `main`,
`master`, `latest` vagy `HEAD` nem fogadható el. Az első körben a gazda csak `onnx` és
`safetensors` formátumú súlyt tölt be; a pickle-alapú formátumokat (`pt`, `bin`, `ckpt`) a séma
leírja, de a gazda a PyTorch-kapuig `blocked` állapotba teszi.

## 6. Gazdajelentések

A [`schemas/host.schema.json`](../schemas/host.schema.json) nem a worker-protokoll része: azt írja
le, mit jelent a CFA4 a saját felületének, a CLI-nek, a vezérlőcsatornának és az MCP-nek.
Workerek ilyen üzenetet nem küldenek és nem kapnak. Két fajtája van:

- **`job_status`:** egy job állapota minden állapotváltás után, ahogy a tartós jobtárba kerül. Az
  állapotok: `queued`, `preparing_model`, `waiting_for_resources`, `loading`, `running`,
  `cancelling`, `succeeded`, `failed`, `cancelled`, `blocked`. Hibakód (`error`) csak `failed`,
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
