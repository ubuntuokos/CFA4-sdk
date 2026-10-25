#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# Every source file carries the SDK's permissive SPDX header, and no GPL
# text slips in: closed paid workers must be able to build on this repo.
set -euo pipefail
cd "$(dirname "$0")/.."

status=0
while IFS= read -r -d '' file; do
  if ! head -n 3 "$file" | grep -q 'SPDX-License-Identifier: MIT OR Apache-2.0'; then
    echo "missing SPDX header: $file" >&2
    status=1
  fi
done < <(git ls-files -z -- '*.py' '*.rs' '*.sh')

if git grep -lI -E 'GNU (Affero |Lesser )?General Public License|SPDX-License-Identifier: .*(A|L)?GPL' \
    -- ':!scripts/check-licence.sh' ':!docs/*.md' ':!README.md' ':!AGENTS.md'; then
  echo "GPL text found in the SDK (see the files above)" >&2
  status=1
fi
[[ -f LICENSE ]] && { echo "LICENSE (GPL) must not exist; use LICENSE-MIT and LICENSE-APACHE" >&2; status=1; }

exit "$status"
