// ===========================================================================
//  COLUMN SECTION TITLES - a script of its own, for DevKit
//  Revit 2021 and later.  GENERATED - do not edit; see tools/build_macro.py.
// ---------------------------------------------------------------------------
//  Draws the title under each column section:
//
//      +-----------------------------------------------+
//      |  +-----------------------------------------+  |
//      |  |          01-C04 COLUMNS RFT.            |  |
//      |  |         SEC. ELEVATION 27-27            |  |
//      |  +-----------------------------------------+  |
//      |  SCALE   1:100                   DETAIL 27    |
//      +-----------------------------------------------+
//
//  The tag comes off the column the section was cut on, the detail number out
//  of the section's name - CT-27 gives 27 - and the scale off the view itself.
//  The wording is four format strings in the settings, so a different office's
//  title is a matter of typing it there.
//
//  It knows which column each section is of because the middle of this file is
//  the sections script's own code. Run it as often as you like: it clears the
//  title it drew before.
// ---------------------------------------------------------------------------
//  THIS FILE IS STATEMENTS ONLY - no using lines, no namespace, no class - so
//  it can be pasted into a box that wraps your code in a method. Every type is
//  written out in full for the same reason.
// ===========================================================================

// How this gets hold of the model. DevKit hands the code a Document called doc.
Autodesk.Revit.DB.Document theDoc = doc;
// Autodesk.Revit.DB.Document theDoc = uidoc.Document;
// Autodesk.Revit.DB.Document theDoc = uiapp.ActiveUIDocument.Document;
