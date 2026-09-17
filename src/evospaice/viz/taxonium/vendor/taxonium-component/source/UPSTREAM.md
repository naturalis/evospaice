# Source provenance

This is the corresponding source for the modified Taxonium component distributed
in the parent directory.

- Upstream project: <https://github.com/theosanderson/taxonium>
- Upstream tag: `v2.1.24`
- Upstream commit: `9d251e3c4f6ee8a9de00bcfdc31b27de4a0bfb34`
- Retrieved: 2026-09-16
- License: GPL-3.0-only; see `../../LICENSE`

Included source directories:

- `taxonium_component`: complete component source, tests, assets, lockfile, and
  build configuration.
- `taxonium_data_handling`: complete local source dependency referenced by the
  component package manifest.

Excluded material is limited to generated `node_modules` and `dist` directories.
The component's remaining dependencies are unmodified, generally available npm
packages pinned by `taxonium_component/package-lock.json`.

## Local modifications

Modified by the Evospaice project on 2026-09-16:

- Added opt-in metadata-derived branch colors for main-tree and minimap edges.
- Added detection of metadata-colored nodes for matching point visibility.
- Added a `hideInternalNodes` configuration override for main-tree and minimap
  point layers.
- Added DeckGL update triggers for metadata-derived edge colors.
- Added a persistent GPL, modification-date, and source-location build banner.

The modified files are `taxonium_component/src/hooks/useLayers.tsx` and
`taxonium_component/vite.config.js`. A complete diff from the upstream commit
is retained as `../modifications.patch`; this source directory is the preferred
form for modification.
