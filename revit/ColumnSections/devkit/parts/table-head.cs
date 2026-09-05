// ===========================================================================
//  COLUMN TABLE - a script of its own, for a paste-in code runner (DevKit)
//  Revit 2021 and later.  GENERATED - do not edit; see tools/build_macro.py.
// ---------------------------------------------------------------------------
//  Draws the schedule table on sections that already exist:
//
//      COLUMN TYPE    |            01-C04(600x800)
//      NUMBER         |                  3
//                     |     Y-AXIS       |      X-AXIS
//      LOCATION       | ON.AXIS( A07.1 ) | NEAR.AXIS.( B05.I )
//                     | ON.AXIS( A07.3 ) | NEAR.AXIS.( B05.I )
//      DETAIL NUMBER  |                 01
//
//  It sorts the columns into types EXACTLY as the sections script does - the
//  tag, the size, the foundation, the beams, the floors, the levels, the ground
//  and the lifts of the stack - because the middle of this file is that script's
//  own code. So the NUMBER here is the count the section was made for: a type of
//  3 says 3, whatever else wears the same tag.
//
//  It finds which type each section belongs to by looking inside its crop, and
//  the detail number comes from the section's name: COL SECTION - C1 - CT-01
//  gives 01.
//
//  Run it as often as you like: it clears what it drew before.
// ---------------------------------------------------------------------------
//  THIS FILE IS STATEMENTS ONLY - no using lines, no namespace, no class - so
//  it can be pasted into a box that wraps your code in a method. Every type is
//  written out in full for the same reason.
// ===========================================================================

// How this gets hold of the model. DevKit hands the code a Document called doc.
Autodesk.Revit.DB.Document theDoc = doc;
// Autodesk.Revit.DB.Document theDoc = uidoc.Document;
// Autodesk.Revit.DB.Document theDoc = uiapp.ActiveUIDocument.Document;
