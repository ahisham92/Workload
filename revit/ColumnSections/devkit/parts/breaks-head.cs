// ===========================================================================
//  COLUMN BREAK LINES - a script of its own, for DevKit
//  Revit 2021 and later.  GENERATED - do not edit; see tools/build_macro.py.
// ---------------------------------------------------------------------------
//  Places your break line detail item - DT_BreakLine by default - on the column
//  sections, wherever a floor, a beam or a foundation runs out of the view. One
//  to each edge a member leaves by, turned to cut across it, and sized to the
//  thickness of what it breaks where the family has a length parameter.
//
//  It knows which column each section is of, and which slabs, beams and footing
//  belong to it, because the middle of this file is the sections script's own
//  code. The family must be loaded in the project first; it is not created.
//
//  Run it as often as you like: it clears the break lines it placed before.
// ---------------------------------------------------------------------------
//  THIS FILE IS STATEMENTS ONLY - no using lines, no namespace, no class - so
//  it can be pasted into a box that wraps your code in a method. Every type is
//  written out in full for the same reason.
// ===========================================================================

// How this gets hold of the model. DevKit hands the code a Document called doc.
Autodesk.Revit.DB.Document theDoc = doc;
// Autodesk.Revit.DB.Document theDoc = uidoc.Document;
// Autodesk.Revit.DB.Document theDoc = uiapp.ActiveUIDocument.Document;
