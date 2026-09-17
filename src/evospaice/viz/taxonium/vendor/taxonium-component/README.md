# Local Taxonium component fork

This directory distributes a modified browser bundle of
[`taxonium-component` v2.1.24](https://github.com/theosanderson/taxonium/tree/v2.1.24)
from upstream commit `9d251e3c4f6ee8a9de00bcfdc31b27de4a0bfb34`.

## License and source

Taxonium and this modified component are licensed under GPL-3.0-only. See
`LICENSE`. The preferred form for modification is included under `source/`,
along with the exact package lockfile, tests, assets, local source dependency,
and build configuration. `source/UPSTREAM.md` records provenance and all local
changes. `modifications.patch` is the complete diff from the pinned upstream
commit.

The viewer that incorporates this component is also distributed under
GPL-3.0-only; see `../../LICENSE` and `../../NOTICE`.

## Modifications

The fork adds the opt-in `configDict.colorBranchesByMetadata` setting. Each
horizontal and vertical branch segment then uses the active metadata color of
its child node. Nodes without metadata retain Taxonium's neutral line color.
The main tree and minimap use the same rule. The
`configDict.hideInternalNodes` setting forces both point layers to retain tips
only without changing branch colors.

Modified by the Evospaice project on 2026-09-16.

## Build

From this directory, run:

```bash
./build.sh
```

The script uses the public `node:22-bookworm` container, installs the declared
`npm@11.4.0`, restores dependencies from `source/taxonium_component/package-lock.json`,
type-checks the component, and writes `taxonium-component.es.js`. Docker and
network access to the npm registry are required. Generally available,
unmodified npm dependencies are not duplicated in `source/`.

The checked-in bundle was initially obtained from the pinned v2.1.24 esm.sh
build and modified to match the included source. Its process and prop-types
helper imports remain pinned to esm.sh, as do the viewer's React peer
dependencies. Rebuilding may not be byte-for-byte identical because esm.sh and
Vite use different build environments, but it produces the modified component
from the complete corresponding source.

Bundle SHA-256: `a8037dd589ec36cccd8f171b4ee8183fadceb9ca3186524110804f958c2a1bf7`
