
# Usage

If you prefer the terminal, you don't need the desktop application at all.
The `kicad-importer` command drives the same import pipeline as the GUI application.
Download a ZIP, type one command, and the part is in your project library.

```
kicad-importer init [--library NAME] [--downloads PATH]
kicad-importer import [FILE] [--all|-a] [--delete|-d] [--debug]
```

# Project workflow

A typical project session configuration looks like this:

```bash
cd ~/projects/my-board          # anywhere inside the KiCad project works
kicad-importer init --library MyBoard_Parts --downloads ~/Downloads   # once
kicad-importer import           # pick a ZIP, done
```

That's the whole workflow. The rest of this page explains what each piece
does and the handful of options you might want.

# Setting up a project: `kicad-importer init`

Every project needs a one-time `init` so the importer knows two things: which
library to put components into, and where you usually download ZIP files.

```bash
kicad-importer init --library MyBoard_Parts --downloads ~/Downloads
```

Run it anywhere inside your KiCad project. The command looks for the folder
containing your `.kicad_pro` file and drops a `.kicad-importer` file
next to it. That file is plain INI, and you can edit it by hand:

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

You can also change individual settings usingthe CLI. Just run `init` again with only the flag
you want to change — everything else is left alone:

```bash
kicad-importer init --downloads ~/parts-inbox   # library name stays as-is
```

Note:
 * `--downloads` understands `~`, is stored as an absolute path, and only warns (rather than failing) if the folder doesn't exist yet.
 *  If you run `init` somewhere that isn't inside a KiCad project (no `.kicad-importer` above you and no `.kicad_pro` to be found) it says so and exits.

# Importing parts: `kicad-importer import`

Once a project is initialised, you can run `import` from the project root or
any subfolder. 

The CLI walks up the directory tree until it finds the
`.kicad-importer` file, and that folder is treated as the project root.
### Import a specific ZIP

```bash
kicad-importer import ul_TPS631000DRLR.zip
```

You can pass filename. It is looked for first in the current directory, then in your
configured downloads folder. So right after downloading a part, this works
from anywhere in the project:

```bash
kicad-importer import ul_TPS631000DRLR.zip     # found in ~/Downloads
```

If the file isn't anywhere to be found, the CLI tells you exactly which
directories it searched and exits with status 1.

## Or just pick one with fuzzy finder

Run `import` with no argument and it gathers every ZIP from the current
directory and the downloads folder, then hands you a fuzzy finder:

```bash
kicad-importer import
```

If you have [`fzf`](https://github.com/junegunn/fzf) installed you get the full type-to-narrow experience. Without it, the CLI
falls back to a simple built-in picker: a numbered list you can filter by
typing a substring, or select by number. 

Press Enter on an empty line or Esc / Ctrl-C in fzf to cancel the opration.

## Import process

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
`already in library, skipped`, and moves on. Importing the same ZIP twice
is harmless.

## Bulk imports: `--all`

The CLI supports bulk-import functionality using the `--all` flag. 
This is best suited when you want to import a bunch of ZIPs when creating a new project. 

Navigate with `cd` to the directory with your ZIPs and then run:

```bash
kicad-importer import --all
```

The CLI first takes a pass over every `*.zip` in the **current directory**
and checks whether it actually looks like a component archive (it
contains at least one KiCad symbol library or footprint). Random ZIPs that
happen to be lying around are listed as skipped and never touched. Then each
candidate is imported in turn, with a per-file `OK` or `FAILED` line and a
final report:

The exit code is 0 only if every candidate imported cleanly, so `--all` is
safe to use in scripts.

Append `--delete` to the import command to also delete the imported zips, so they are not
present in the next bulk import invocation.

```bash
kicad-importer import ul_TPS631000DRLR.zip --delete
kicad-importer import --all --delete
```
# Quick reference

| I want to... | Run |
|---|---|
| Set up a project | `kicad-importer init --library MyParts --downloads ~/Downloads` |
| Change one setting later | `kicad-importer init --downloads <new-path>` |
| Import a downloaded part | `kicad-importer import <file.zip>` |
| Browse and pick a part | `kicad-importer import` |
| Import everything here | `kicad-importer import --all` |
| …and tidy up the ZIPs | `kicad-importer import --all --delete` |
