# Using the command line

If you live in a terminal, you don't need the desktop application at all.
The `kicad-importer` command drives the exact same import pipeline — symbol
merging, footprint copying, 3D-model path repair, library-table registration,
validation — without ever opening a window. Download a ZIP, type one command,
and the part is in your project library.

A typical session looks like this:

```bash
cd ~/projects/my-board          # anywhere inside the KiCad project works
kicad-importer init --library MyBoard_Parts --downloads ~/Downloads   # once
kicad-importer import           # pick a ZIP, done
```

That's the whole workflow. The rest of this page explains what each piece
does and the handful of options you might want.

## Setting up a project: `kicad-importer init`

Every project needs a one-time `init` so the importer knows two things: which
library to put components into, and where you usually download ZIP files.

```bash
kicad-importer init --library MyBoard_Parts --downloads ~/Downloads
```

Run it anywhere inside your KiCad project. The command looks for the folder
containing your `.kicad_pro` file and drops a small `.kicad-importer` file
next to it. That file is plain INI, and you can edit it by hand if you like:

```ini
[kicad-importer]
library = MyBoard_Parts
downloads = /home/you/Downloads
```

- `library` is the name of the project library that imports go into. The
  importer creates `libraries/MyBoard_Parts.kicad_sym` and
  `libraries/MyBoard_Parts.pretty` under the project root and registers them
  in the project's library tables.
- `downloads` is optional. If set, `import` also searches this folder, so you
  can import straight from your browser's download directory without moving
  files around.

Changed your mind about a setting? Just run `init` again with only the flag
you want to change — everything else is left alone:

```bash
kicad-importer init --downloads ~/parts-inbox   # library name stays as-is
```

A couple of small courtesies: `--downloads` understands `~`, is stored as an
absolute path, and only warns (rather than failing) if the folder doesn't
exist yet. If you run `init` somewhere that isn't inside a KiCad project — no
`.kicad-importer` above you and no `.kicad_pro` to be found — it says so and
exits instead of guessing.

## Importing parts: `kicad-importer import`

Once a project is initialised, you can run `import` from the project root or
any subfolder — the CLI walks up the directory tree until it finds the
`.kicad-importer` file, and that folder is treated as the project root. Deep
inside `hardware/rev-b/simulation`? Doesn't matter.

### Import a specific ZIP

```bash
kicad-importer import ul_TPS631000DRLR.zip
```

You can pass a path (absolute or relative), or just a bare filename. A bare
filename is looked for first in the current directory, then in your
configured downloads folder. So right after downloading a part, this works
from anywhere in the project:

```bash
kicad-importer import ul_TPS631000DRLR.zip     # found in ~/Downloads
```

If the file isn't anywhere to be found, the CLI tells you exactly which
directories it searched and exits with status 1 — no silent failures.

### Or just pick one

Run `import` with no argument and it gathers every ZIP from the current
directory and the downloads folder, then hands you a fuzzy finder:

```bash
kicad-importer import
```

If you have [`fzf`](https://github.com/junegunn/fzf) installed (you want fzf,
it's great) you get the full type-to-narrow experience. Without it, the CLI
falls back to a simple built-in picker: a numbered list you can filter by
typing a substring, or select by number. Pressing Enter on an empty line —
or Esc / Ctrl-C in fzf — cancels cleanly with nothing imported.

### What a successful import looks like

For each part, the importer:

1. reads the symbol name out of the ZIP to use as the part name,
2. merges the symbol into `libraries/<library>.kicad_sym`,
3. copies footprints into `libraries/<library>.pretty/` and 3D models into
   `libraries/3dmodels/`,
4. links the symbol to its footprint and repairs the footprint's 3D-model
   path (using `${KIPRJMOD}` so the project stays portable),
5. registers the library in the project's `sym-lib-table` and `fp-lib-table`
   if it isn't there yet,
6. keeps a copy of the original ZIP in `libraries/source_zips/`, and
7. validates the result and prints a summary.

If the component is already in the library, the importer notices, tells you
`already in library, skipped`, and moves on — importing the same ZIP twice
is harmless.

As with the desktop app: the first time a library is created and registered,
reopen KiCad so it reloads the library tables. Subsequent imports into the
same library show up without a restart.

## Bulk imports: `--all`

Ended a download session with a pile of ZIPs? Drop them in the project
folder (or `cd` to wherever they are inside the project) and run:

```bash
kicad-importer import --all
```

The CLI first takes a pass over every `*.zip` in the **current directory**
and checks whether it actually looks like a component archive — meaning it
contains at least one KiCad symbol library or footprint. Random ZIPs that
happen to be lying around are listed as skipped and never touched. Then each
candidate is imported in turn, with a per-file `OK` or `FAILED` line and a
final tally:

```
Candidate component ZIPs:
  ul_BQ28Z610DRZR.zip
  ul_ISOW7841DWER.zip
Skipped (no symbol or footprint assets):
  firmware-backup.zip

Importing ul_BQ28Z610DRZR.zip ...
  OK: BQ28Z610DRZR
Importing ul_ISOW7841DWER.zip ...
  OK: ISOW7841DWER

Imported 2 of 2 component ZIP(s).
```

The exit code is 0 only if every candidate imported cleanly, so `--all` is
safe to use in scripts.

## Cleaning up after yourself: `--delete`

Add `--delete` (or `-d`) and the CLI removes each ZIP it successfully
imported. This is safer than it sounds: the import itself already archived a
copy under `libraries/source_zips/`, so the original in your downloads pile
is redundant the moment the import succeeds.

```bash
kicad-importer import --all --delete
```

Two things to know:

- Components that were skipped as *already in the library* count as
  successes, so their ZIPs are cleaned up too.
- In `--all` mode the delete step is all-or-nothing. If even one import
  fails, **nothing** is deleted and you'll see a message like
  `1 of 4 imports failed — skipping deletion of imported zips`. The idea is
  that you fix the problem and re-run, rather than ending up with a
  half-cleaned folder and no memory of what went where.

## When something goes wrong

Errors come out as one-line messages on stderr — a corrupt archive, an
unreadable ZIP entry, a library-table conflict — followed by a non-zero exit
code. If a message isn't enough and you want the full story, add `--debug`
to get the complete Python traceback.

```bash
kicad-importer import weird-part.zip --debug
```

And if you ever see
`no .kicad-importer found; run 'kicad-importer init' inside your KiCad project`,
that's just the CLI telling you it walked all the way up the directory tree
without finding a configured project — you're either outside the project or
haven't run `init` yet.

## Quick reference

```
kicad-importer init [--library NAME] [--downloads PATH]
kicad-importer import [FILE] [--all|-a] [--delete|-d] [--debug]
```

| I want to… | Run |
|---|---|
| Set up a project | `kicad-importer init --library MyParts --downloads ~/Downloads` |
| Change one setting later | `kicad-importer init --downloads <new-path>` |
| Import a downloaded part | `kicad-importer import <file.zip>` |
| Browse and pick a part | `kicad-importer import` |
| Import everything here | `kicad-importer import --all` |
| …and tidy up the ZIPs | `kicad-importer import --all --delete` |
