#!/usr/bin/env python3
"""Assemble the macro version of the add-in.

Revit's own macro editor takes one file, so the shared classes in src/ are
concatenated into macro/ColumnSectionsMacro.cs behind a ThisDocument class that
calls them. src/ stays the only copy of the code; run this after changing it:

    python3 tools/build_macro.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SHARED = [
    "Settings.cs",
    "Units.cs",
    "ColumnSignature.cs",
    "ColumnInfo.cs",
    "ColumnScanner.cs",
    "SectionFactory.cs",
    "ColumnSectionsJob.cs",
]

HEADER = '''// Column Sections, as a Revit macro. GENERATED — do not edit.
//
// Made from the add-in sources by tools/build_macro.py; edit those and run it
// again. It is one file so that it can be pasted straight into Revit's own
// macro editor, with no Visual Studio and nothing to install:
//
//   1. Manage > Macros > Macro Manager, and pick the tab with your project's
//      name on it (not Application).
//   2. Module..., name it exactly  ColumnSections , language C#, and OK.
//   3. In the editor that opens, select all of the generated file and paste
//      this file over it. If the compiler complains that AddInId or
//      Transaction is set twice, delete the two attribute lines below.
//   4. Build (F8, or the hammer), then close the editor.
//   5. Macro Manager again: CreateColumnSections cuts the sections,
//      ColumnTypeReport only counts and writes the CSV. Run.
//
// The module name has to be ColumnSections, because that is the namespace the
// class below is declared in.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    [Autodesk.Revit.DB.Macros.AddInId("6c1f4d5e-2c8a-4a2f-9d5e-7b3a1f0c9e42")]
    public partial class ThisDocument
    {
        private void Module_Startup(object sender, EventArgs e)
        {
        }

        private void Module_Shutdown(object sender, EventArgs e)
        {
        }

        /// <summary>One cross section per column type, with the count noted in it.</summary>
        public void CreateColumnSections()
        {
            Run(true);
        }

        /// <summary>Count the types and write the CSV, changing nothing.</summary>
        public void ColumnTypeReport()
        {
            Run(false);
        }

        private void Run(bool createSections)
        {
            Document doc = this.Document;
            if (doc == null)
            {
                TaskDialog.Show("Column sections", "Open a project first.");
                return;
            }

            var uidoc = new UIDocument(doc);
            string problem;
            bool ok = createSections
                ? ColumnSectionsJob.CreateSections(uidoc, out problem)
                : ColumnSectionsJob.Report(uidoc, out problem);
            if (!ok && !string.IsNullOrEmpty(problem))
                TaskDialog.Show("Column sections", problem);
        }
    }
'''


def body_of(path):
    """The classes in a source file, without its usings or namespace wrapper."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("namespace "))
    if lines[start + 1].strip() != "{":
        raise SystemExit("%s: expected a brace under the namespace" % path.name)
    end = max(i for i, line in enumerate(lines) if line.rstrip() == "}")
    body = lines[start + 2:end]
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def main():
    parts = [HEADER]
    for name in SHARED:
        source = HERE / "src" / name
        parts.append("\n    // %s\n    // %s\n\n%s\n"
                     % (name, "-" * (len(name) + 3), body_of(source)))
    parts.append("}\n")

    out = HERE / "macro" / "ColumnSectionsMacro.cs"
    out.write_text("\n".join(parts), encoding="utf-8")
    print("wrote %s (%d lines)" % (out, len(out.read_text().splitlines())))

    # A .txt of each pasteable file as well: some machines will not open, mail
    # or download a .cs, and these are only ever copied out of, never compiled
    # where they sit.
    for source in [HERE / "devkit" / "ColumnSectionsDevKit.cs", out]:
        mirror = source.with_suffix(".txt")
        mirror.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print("wrote %s" % mirror)


if __name__ == "__main__":
    main()
