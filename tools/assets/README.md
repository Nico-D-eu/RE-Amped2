# Amped 2 asset toolkit

Scripts for pulling Amped 2's textures and scripts out of the game files,
upscaling the textures with Upscayl, editing them in Paint.NET, and putting
everything back.

```
python tools/assets/amped_assets.py <command> --help
```

Everything is written under `amped2/mods/`, which is git-ignored because it
holds game data. Only `install` and `restore` write to `game/`.

## Requirements

| Tool | Where | Used by |
|---|---|---|
| Python 3 with `pillow` and `numpy` | `pip install --user pillow numpy` | everything |
| `texconv.exe` (DirectXTex) | `tools/bin/` | `tex-pack`, `tex-inject` |
| `unluac.jar` + Java | `tools/bin/` | `decompile` |
| Upscayl 2.15 | `../upscayl-2.15.0-win/` | `tex-upscale` (uses its `upscayl-bin.exe` and models) |

## What's in the game files

* `.gfx` / `.res` are plain ZIP archives. Each entry is either stored or
  deflated, and `repack` keeps each entry's method, name order and timestamp.
* Textures are standard Xbox D3D texture headers followed by raw GPU data.
  They sit in three places:
  * `.xpr` (XPR0) files: UI, character parts, effects, lightmaps;
  * `.pgf` files, before the geometry: all level surfaces (`Levels/*/XX.pgf`)
    and character/object meshes. Character `.pgf` files have a matching
    `.tmap` script listing each texture's name, size and mip count, in the
    same order;
  * `.trees` files: an XPR0 embedded after a small header. These can be
    exported but not rebuilt.

  About 97% of the textures are DXT1 or DXT3. The rest are swizzled
  A8R8G8B8, L8 or A8. `tex-export` skips 7 textures in an unknown format
  (0x3C) and 2 cube maps.
* The scripts are a **pre-release Lua 5.0 (beta)** build.
  [`lua50beta.py`](lua50beta.py) converts them to standard 5.0 bytecode
  for unluac. It handles the different header test number, the swapped
  locals/lines order, the missing upvalue names, and the game's extra
  wide-string constant (`L"text"`).

## Textures, workflow A: a replacement pack for the PC recomp

```
python tools/assets/amped_assets.py decompile      # optional, but gives character textures real names
python tools/assets/amped_assets.py tex-export     # mods/textures/original/*.png + manifest.json
python tools/assets/amped_assets.py tex-upscale    # mods/textures/upscaled/*.png  (4x, 1-2 h on an RTX 2070)
python tools/assets/amped_assets.py tex-pack       # mods/texture_pack/<key>.dds + index.json
```

* **Names.** Files are `<key>__<where it came from>.png`, and the key is
  what identifies a texture. Don't rename the key part.
* **Kinds.** `manifest.json` gives each texture a kind: `world`, `ui`,
  `normal`, `lightmap` or `font`. Lightmaps and anything under 16 px get
  plain Lanczos scaling, because AI models add noise to smooth gradients.
  Normal maps are AI-upscaled and then renormalised. Fonts (glyph atlases)
  have their alpha AI-upscaled too, since it holds the glyphs, and its edges
  tightened, so text stays sharp.
* **Tiling and transparency.** Before upscaling, textures are padded with
  their own wrapped edges so tiling surfaces stay seamless, and transparent
  pixels are filled with nearby colour so cut-outs (trees, fences) don't get
  dark halos. Alpha is scaled separately with Lanczos.
* **Options.** `--model` picks any Upscayl model; the default is
  `ultrasharp-4x`, and `remacri-4x` and `high-fidelity-4x` are worth
  comparing. `--filter BR1` runs a subset. `--max-size` (default 4096) caps
  the output. Finished textures are skipped, so an interrupted run can
  continue.
* **Hand edits.** Put a PNG with the same file name into
  `mods/textures/edit/` and `tex-pack` uses it in place of the upscaled one.
  Paint.NET works for this.

**The pack format, for the runtime hook that still needs writing.** The
recomp's D3D layer should look up each guest texture it creates:

* key = `crc32(top mip bytes as stored in guest memory)` as 8 hex digits,
  `_<width>x<height>_<format code as 2 hex digits>`. Example:
  `ddf3bb52_256x256_0c` (DXT1 is 0x0C, DXT3 is 0x0E). For DXT these are the
  raw 4×4 blocks; other formats are hashed in their swizzled form.
* If `texture_pack/<key>.dds` exists, create the host texture from it: BC7,
  full mip chain, DX10 header. Otherwise upload the guest data as usual.
* Only host VRAM grows. The emulated 64 MB of guest RAM still holds the
  original small textures, so this has no memory limit.

The hook is in xboxrecomp (`RECOMP_TEXTURE_PACK`, on by default through
`amped2.ini` `TexturePack=1`).

* **Freed textures.** Amped 2 draws some menu and loading-screen textures
  after freeing them, when its pool's free-list header has replaced their
  first 16 bytes, so their key names nothing. `tex-pack` also writes
  `tails.txt`, the crc32 of each DXT texture's top mip past those 16 bytes,
  and the runtime falls back to it.
* **Misses.** `RECOMP_TEXTURE_PACK_MISSES=<file>` lists the keys a run drew
  that the pack lacks, and `RECOMP_TEXTURE_PACK_DUMP=<dir>` writes each one's
  top mip as `<key>.raw`. `tex-misses <dir>` decodes those into
  `mods/textures/original/<key>__runtime.png` with manifest entries
  (`--kind`, default `world`), so `tex-upscale --filter __runtime` and
  `tex-pack` include them, and `tex-export` keeps them. On ML1 the remaining
  misses were the four run-time fonts (now packed: `tex-misses --kind font`
  keeps them fonts), a 1×1 fill, one 64×16
  texture in format 0x3C, and a few textures drawn after their memory was
  reused (garbage for a frame, nothing to replace).

## Textures, workflow B: back into the game's own files

This works for xemu or real hardware, and for making new texture variants:

```
copy PNGs (keep their names) into mods/textures/inject/
python tools/assets/amped_assets.py tex-inject     # rebuilds the .xpr/.pgf into mods/overrides/
python tools/assets/amped_assets.py repack         # mods/build/game/<archive>
python tools/assets/amped_assets.py install        # copies into game/, originals -> mods/backup/
python tools/assets/amped_assets.py restore        # undo
```

* The PNG is encoded to the texture's original Xbox format (DXT1/3/5 or
  A8R8G8B8/X8R8G8B8) and resized to a power of two. The mip chain goes down
  to the original's smallest mip size.
* A texture shared by several files is replaced everywhere it's used;
  `--filter` limits which files are changed.
* Changing a `.pgf` texture's size also rewrites the matching `.tmap`.
  This needs `decompile` to have been run first.
* **Memory:** the Xbox has 64 MB of RAM, and so does the recomp without the
  hook above. 4× textures take 16× the memory, so for this route use
  `tex-upscale --scale 2 --max-size 1024` and upscale selectively.
  `tex-inject` prints each file's size before and after.

## Scripts: characters, levels, game data

```
python tools/assets/amped_assets.py decompile      # mods/source/<archive>/<entry>, readable Lua
python tools/assets/amped_assets.py unpack         # mods/extracted/<archive>/<entry>, raw copies
```

To change something, copy the file into `mods/overrides/<archive>/<same
entry path>`, edit it, then `repack` and `install`. New files placed there
are added to the archive. Overrides are written as Lua **source**. The engine
should accept that, since several shipped data files (`Career.levels`,
`*.frame`, `NewModel.parts.male`) are plain-text Lua, but that hasn't been
tested in-game yet.

### New characters from existing parts

* A pro rider is two scripts in `Characters/pro/pro.res`, under `ProParts/`:
  * `<Name>.boarder`: display name (`L"..."`), board name, stance, rank,
    stats, and `MeshFilename` pointing at the `.parts` file.
  * `<Name>.parts`: one table per slot (`Board`, `Bottom`, `Top`, `Head`,
    `Gloves`, `Hat`, `Skate`, ...), each with `MeshName`, `MeshType` and
    `TextureName`.
* **Meshes.** `MeshName = "bigfoot_heads"` resolves to
  `heads/pgf/bigfoot_heads_HI|MED.PGF` in `MedHiResCharacter.gfx`, plus
  `_LOW` in `LoResCharacter.gfx`. `TextureName` picks an `.xpr` texture set
  such as `skates_generic_02`. There are about 2,300 part files to combine;
  browse them with `unpack --filter Character`.
* **Registering.** The executable builds the path `Characters\Pro\ProParts\`
  and uses the `*.*` and `.boarder` patterns, so it most likely picks up
  every `.boarder` file in that folder. Adding
  `ProParts/MyRider.boarder` and `ProParts/MyRider.parts` should create a
  new rider; not yet tested. `ProParts/HiddenCharacters.lua` pairs hidden
  riders with their unlock codes.
* **Recolours.** Copy the texture's file to a new name inside
  `mods/overrides`, for example
  `.../LoResCharacter.gfx/skates/xpr/Blue_skates.xpr`. Edit its PNG from
  `original/`, put it in `inject/`, run
  `tex-inject --into Characters/boarder/LoResCharacter.gfx/skates/xpr/Blue_skates.xpr`,
  and point `TextureName` at it.
* **New careers.** `Characters/NewCareer/NewCareer.res` is the template a
  new career save is made from (`Career.boarder`, `.levels`, `.records`,
  ...). Existing saves keep their own copies, so start a new career after
  changing it.

### Levels

* The level list is `Career.levels` in `NewCareer.res`: display name, path
  (`LEVELS\XX1\`), rank, lock state and unlock text.
* Each level's `.res` holds its gameplay scripts: `LevelInfo.lua`,
  `Weather.lua`, `*_Challenges.lua`, `*_DropPoints.lua`, `*_Progress.lua`,
  the scripted-object maps (`*.scm.lua`), `.CFG` lighting and environment
  files, and ambient rider replays. Editing these gives remixed versions of
  existing mountains: new challenges, drop points and weather.
* Genuinely new terrain isn't possible yet. The mesh half of `.pgf` hasn't
  been decoded; only its header and texture block are handled here. The
  executable also references `\package.levels`, which suggests the engine
  can load extra level packages, like download content. That's worth
  following up in Ghidra.
