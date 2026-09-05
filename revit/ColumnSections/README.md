# Column Sections — a Revit add-in

Takes a section of every column that is *different*, and says on the drawing how
many columns are not.

Two columns are the same type when all five of these agree:

1. **Size** — family and type, and the section dimensions (`b`/`h`, `Width`/`Depth`
   or `Diameter`; measured off the solid when the family has no such parameters).
   The column's height counts as size too, unless you turn that off.
2. **The foundation below it** — whether one is found under the column at all, its
   type, the level of its top and its thickness.
3. **Whether a beam is connected** — how many beams frame into the column, and
   whether one lands at the top.
4. **The level of the ground** — how far the column base sits below (or above)
   ground level.
5. **What the stack does** — the size of the column sitting on the same plan
   location above it and below it. A 600x900 that carries a 400x900 is not the
   same type as a 600x900 that carries its own size on up, nor as one with
   nothing above it; and the 400x900 landing on a 600x900 is not the same as one
   landing on another 400x900.

Everything is rounded before it is compared — 5 mm on sizes, 10 mm on levels — so
a model that is a millimetre out does not produce two types.

For every type it creates one cross section, cut square-on to the column and
framed to take in the foundation below, the beam above and the lift either side
of it, and writes a note in it:

```
CT-01 - 7 COLUMNS OF THIS TYPE
SIZE: 600 x 900  (C-600x900)
FDN TOP -1500 (600 THK)
2 BEAMS CONNECTED (AT TOP)
BASE 1500 BELOW GROUND
NOTHING BELOW (COLUMN STARTS HERE)
ABOVE: 400 x 900 - SIZE CHANGES
BASE -1500 / TOP 3600 / HT 5100
MARKS: C1, C2, C3, C4, C5, C6, C7
```

The section reaches a little past the column at both ends, so the change of size
is drawn where it happens rather than only written down.

The view is named `COL SECTION - CT-01 (7 NOS)`.

## Getting it into Revit

There are three ways in, and **only one file to handle** in each. Do not
paste the files in `src/` one at a time into a code-runner window: they are eight
parts of one program, and a window that wraps what you paste inside a method
cannot take a `using` line or a `namespace` at all.

### 1. As a macro — nothing to install, nothing to build

Use [`macro/ColumnSectionsMacro.cs`](macro/ColumnSectionsMacro.cs). It is the whole
program in one file, generated from `src/`.

1. Open your project. **Manage ▸ Macros ▸ Macro Manager**, and pick the tab
   named after the project (not *Application*).
2. **Module…**, name it exactly `ColumnSections`, language **C#**, OK. The name
   matters: it becomes the namespace the file is written in.
3. The macro editor opens on a generated file. Select all of it and paste the
   whole of `ColumnSectionsMacro.cs` over it.
4. Build — the hammer, or F8 — and close the editor.
5. **Macro Manager** again. `CreateColumnSections` cuts the sections;
   `ColumnTypeReport` only counts and writes the CSV. Select one and **Run**.

If the compiler says `AddInId` or `Transaction` is given twice, delete those two
attribute lines near the top of what you pasted — your Revit put them in the
hidden half of the class.

Macros live in the project file, so this travels with the model and has to be
done again in the next one. The add-in does not.

### 2. In a paste-in code runner (DevKit and the like)

Use [`devkit/ColumnSectionsDevKit.cs`](devkit/ColumnSectionsDevKit.cs). Those
tools wrap what you paste inside a method of their own, which is why they choke
on the other files: a `using` line, a `namespace` and a `class` cannot go inside
a method. This one is statements only, with every type written out in full, so it
does not care what the tool has already imported.

Paste the whole file and run it. DevKit hands the pasted code a `Document`
called `doc`, which is what the file's first statement reads; in another runner
that name will be its own, and the alternatives are commented under it.

If it then says not all code paths return a value, add the return the tool wants
as the last line — the commented lines at the bottom of the file.

Both pasteable files are mirrored as `.txt` beside them —
[`devkit/ColumnSectionsDevKit.txt`](devkit/ColumnSectionsDevKit.txt) and
[`macro/ColumnSectionsMacro.txt`](macro/ColumnSectionsMacro.txt) — for machines
that will not open or download a `.cs`. They are copies, written by the same
script; the `.cs` is the one to edit.

This is the same program, but a second copy of it rather than a generated one:
without classes it has to be written differently, keeping each column's
measurements in plain arrays. The settings are the first forty lines. It does the
sections and the CSV; it has no separate report command.

### 3. As an add-in — built once, on every project after that

Needs Visual Studio or the .NET SDK on a machine with Revit installed; see
**Building** below. It produces `ColumnSections.dll`, and the two files go here:

```
%AppData%\Autodesk\Revit\Addins\2025\ColumnSections.addin
%AppData%\Autodesk\Revit\Addins\2025\ColumnSections\ColumnSections.dll
```

That is `C:\Users\<you>\AppData\Roaming\Autodesk\Revit\Addins\2025`. Start
Revit and the buttons are under **Structure Tools ▸ Column Sections**.
`-p:DeployAddin=true` on the build does that copying for you.

## Using it

**Structure Tools ▸ Column Sections ▸ Column Sections.** With nothing selected it
reads every column in the model; select columns first to work on those only. It
shows what it found, and how many sections it is about to create, before it
creates anything.

**Structure Tools ▸ Column Sections ▸ Type Report** does the same grouping without
touching the model, and writes a CSV of it to your temp folder. Run this first on
a real model: it is the quick way to see whether the tolerances are giving you
the number of types you expect.

## Building

For the add-in only — the macro needs none of this. Needs the Revit API from an
installed Revit; nothing is downloaded.

```
dotnet build ColumnSections.csproj -c Release -p:RevitVersion=2024
```

* `RevitVersion` picks the target framework — `net48` for Revit 2022–2024,
  `net8.0-windows` for 2025 and later — and where `RevitAPI.dll` is read from.
* Override the location with `-p:RevitPath="D:\Autodesk\Revit 2024"`.
* Add `-p:DeployAddin=true` to copy the DLL and the `.addin` manifest into
  `%AppData%\Autodesk\Revit\Addins\<version>` for you.

To install by hand, put `ColumnSections.dll` in
`%AppData%\Autodesk\Revit\Addins\<version>\ColumnSections\` and
`ColumnSections.addin` in the folder above it, then start Revit.

Revit 2021 is the oldest version the unit calls (`UnitTypeId`) work with.

## Tuning

The macro is generated, so change `src/` and run `python3 tools/build_macro.py`
to write `macro/ColumnSectionsMacro.cs` again — the sources are the only copy of
the code. Editing the macro file directly works too, until the next generation
overwrites it.

Everything adjustable is in [`src/Settings.cs`](src/Settings.cs), commented, one
property each: the rounding tolerances, how far out a foundation or a beam is
still counted as this column's, which level is "ground" (by name, else the level
nearest zero), the view scale and the clearances around the column, and whether
the type code is written into each column's Comments so the plan can be tagged
with it — that one is off, because it edits your model.

Two switches change what counts as a type:

* `CountBeamsSeparately` — off, and *any* beam connection is one case; the
  distinction becomes connected / not connected.
* `HeightIsPartOfType` — off, and two columns of the same section on different
  storey heights are one type.
* `StackChangeIsPartOfType` — off, and what sits above and below stops counting;
  the sizes are still reported in the note and the CSV.

## How the model is read

* **Columns** — structural columns, plus architectural columns if the model has
  them. Base and top come from the level parameters and their offsets, falling
  back to the geometry for slanted columns.
* **Foundations** — anything in Structural Foundations whose footprint contains
  the column's centre and whose top is at or below the column base. The highest
  one wins, so a footing under a raft is picked over the raft.
* **Beams** — structural framing whose centre line passes within half the column
  width plus a tolerance, in plan, while its elevation overlaps the column.
  That catches beams that run over the column as well as beams that stop at it.
* **Ground** — a named level, or the level closest to project zero.
* **The stack** — the columns whose centres are within a tolerance of this one's,
  plus half the smaller one's least plan dimension, so a column that steps in and
  sits flush on one face is still the same stack. The one immediately above is the
  lowest of them starting at or above this column's top, within a slab thickness;
  the one below is found the same way. Sizes are rounded before they are compared,
  so a step of a millimetre is not a change.

Anything that cannot be measured is skipped rather than guessed at, and a type
whose section fails to draw is reported at the end with the reason; the rest are
still created.
