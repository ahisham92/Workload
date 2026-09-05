// ===========================================================================
//  COLUMN PLAN TAGS - a script of its own, for DevKit
//  Revit 2021 and later.  GENERATED - do not edit; see tools/build_macro.py.
// ---------------------------------------------------------------------------
//  Run it with a PLAN OPEN. Beside every column the plan cuts it puts:
//
//      ( 01-C02 )        [column]     01-C 02
//      (   01   )                     (600x800)
//
//  On the right, the column's tag and its size. On the left, a bubble with a
//  leader to the column: the tag above the line, and below it the number of the
//  detail the column is drawn on - read off the section views themselves where
//  they exist, so the two agree, and off the type's own number where they do
//  not.
//
//  It knows the tags, the sizes and the types because the middle of this file
//  is the sections script's own code. It does not clear anything: a column
//  something is already written beside is left alone.
// ---------------------------------------------------------------------------
//  THIS FILE IS STATEMENTS ONLY - no using lines, no namespace, no class - so
//  it can be pasted into a box that wraps your code in a method. Every type is
//  written out in full for the same reason.
// ===========================================================================

// How this gets hold of the model. DevKit hands the code a Document called doc.
Autodesk.Revit.DB.Document theDoc = doc;
// Autodesk.Revit.DB.Document theDoc = uidoc.Document;
// Autodesk.Revit.DB.Document theDoc = uiapp.ActiveUIDocument.Document;
