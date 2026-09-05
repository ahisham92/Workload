// ===========================================================================
//  COLUMN TABLE - a script of its own, for a paste-in code runner (DevKit)
//  Revit 2021 and later.
// ---------------------------------------------------------------------------
//  Draws the schedule table on sections that already exist:
//
//      COLUMN TYPE    |            01-C04(600x800)
//      NUMBER         |                  2
//                     |     Y-AXIS       |      X-AXIS
//      LOCATION       | ON.AXIS( A07.1 ) | NEAR.AXIS.( B05.I )
//                     | ON.AXIS( A07.3 ) | NEAR.AXIS.( B05.I )
//      DETAIL NUMBER  |                 01
//
//  It works out which column a section is of by looking inside its crop, takes
//  that column's tag from Comments, and lists every column in the model wearing
//  the same tag - one location row each, saying which grid it stands on or near
//  in either direction. The detail number is the number in the section's name:
//  COL SECTION - C1 - CT-01 gives 01.
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

// --------------------------------------------------------------- settings --

// The tag written on each column, and where it is kept.
string tagParameterName = "Comments";

// Which sections to draw on. Empty name: every section in the model.
bool onlyTheActiveView = false;
string viewNameContains = "COL SECTION";

// Clear the detail lines and text this script drew before, so running it again
// replaces the table instead of drawing a second one on top. It clears ALL
// view-specific lines and text in the sections it draws on, so turn it off if
// you have annotated them by hand.
bool clearExistingAnnotation = true;

// The table, in millimetres ON PAPER: it comes out the same size on the sheet
// whatever scale the section is at.
double tableLabelWidthMm = 32.0;
double tableValueWidthMm = 64.0;
double tableRowHeightMm = 7.0;
double tableGapAboveViewMm = 4.0;
int maxLocationRows = 12;

// A column is ON the axis within this of the grid line, and NEAR it beyond.
double onAxisToleranceMm = 100.0;

// The left location cell names the grid running parallel to Y, the right one
// the grid running parallel to X. True swaps the two columns over.
bool swapAxisColumns = false;

// Section size parameters looked for, in order, for the size in the type cell.
string[] widthParameterNames = new string[] { "b", "Width", "Depth 1", "bf" };
string[] depthParameterNames = new string[] { "h", "Depth", "Height", "d" };
string[] diameterParameterNames = new string[] { "Diameter", "D" };

// ===========================================================================

var inv = System.Globalization.CultureInfo.InvariantCulture;
var theUiDoc = new Autodesk.Revit.UI.UIDocument(theDoc);

System.Func<double, double> toMm = feet =>
    Autodesk.Revit.DB.UnitUtils.ConvertFromInternalUnits(
        feet, Autodesk.Revit.DB.UnitTypeId.Millimeters);
System.Func<double, double> toFeet = mm =>
    Autodesk.Revit.DB.UnitUtils.ConvertToInternalUnits(
        mm, Autodesk.Revit.DB.UnitTypeId.Millimeters);

// ------------------------------------------------------------ the columns --

var columnIds = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
var columnTag = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string>();
var columnMark = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string>();
var columnSize = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string>();
var columnPoint = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.XYZ>();
var columnLocationY = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string>();
var columnLocationX = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string>();

// First of the named parameters that holds a length, on the instance or its
// type. Zero when none of them do.
System.Func<Autodesk.Revit.DB.Element, Autodesk.Revit.DB.Element, string[], double> firstLength =
    (instance, type, names) =>
{
    foreach (string name in names)
    {
        Autodesk.Revit.DB.Element[] hosts = new Autodesk.Revit.DB.Element[] { instance, type };
        foreach (Autodesk.Revit.DB.Element host in hosts)
        {
            if (host == null) continue;
            Autodesk.Revit.DB.Parameter p = host.LookupParameter(name);
            if (p != null && p.StorageType == Autodesk.Revit.DB.StorageType.Double && p.HasValue)
            {
                double v = p.AsDouble();
                if (v > 1e-9) return v;
            }
        }
    }
    return 0.0;
};

var wantedCategories = new Autodesk.Revit.DB.BuiltInCategory[]
{
    Autodesk.Revit.DB.BuiltInCategory.OST_StructuralColumns,
    Autodesk.Revit.DB.BuiltInCategory.OST_Columns
};

foreach (Autodesk.Revit.DB.BuiltInCategory bic in wantedCategories)
{
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfCategory(bic)
        .OfClass(typeof(Autodesk.Revit.DB.FamilyInstance))
        .WhereElementIsNotElementType())
    {
        var column = e as Autodesk.Revit.DB.FamilyInstance;
        if (column == null) continue;
        Autodesk.Revit.DB.BoundingBoxXYZ box = column.get_BoundingBox(null);
        if (box == null) continue;

        // Where it stands, and how far up it runs.
        var point = column.Location as Autodesk.Revit.DB.LocationPoint;
        Autodesk.Revit.DB.XYZ centre = point != null
            ? new Autodesk.Revit.DB.XYZ(point.Point.X, point.Point.Y, box.Min.Z)
            : new Autodesk.Revit.DB.XYZ((box.Min.X + box.Max.X) / 2.0,
                                        (box.Min.Y + box.Max.Y) / 2.0, box.Min.Z);

        // The tag: the named parameter first, Comments after it.
        string tag = "";
        Autodesk.Revit.DB.Parameter tagParam = string.IsNullOrEmpty(tagParameterName)
            ? null : column.LookupParameter(tagParameterName);
        if (tagParam == null)
            tagParam = column.get_Parameter(
                Autodesk.Revit.DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
        if (tagParam != null && tagParam.StorageType == Autodesk.Revit.DB.StorageType.String)
        {
            string raw = tagParam.AsString();
            if (!string.IsNullOrEmpty(raw)) tag = raw.Trim();
        }

        // Its size, for the type cell.
        Autodesk.Revit.DB.FamilySymbol symbol = column.Symbol;
        string size;
        double diameter = firstLength(column, symbol, diameterParameterNames);
        double width = firstLength(column, symbol, widthParameterNames);
        double depth = firstLength(column, symbol, depthParameterNames);
        if (diameter > 0 && width <= 0 && depth <= 0)
        {
            size = string.Format(inv, "D{0:0}", toMm(diameter));
        }
        else if (width > 0 && depth > 0)
        {
            size = string.Format(inv, "{0:0}x{1:0}", toMm(width), toMm(depth));
        }
        else
        {
            size = string.Format(inv, "{0:0}x{1:0}",
                toMm(box.Max.X - box.Min.X), toMm(box.Max.Y - box.Min.Y));
        }

        Autodesk.Revit.DB.Parameter markParam =
            column.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ALL_MODEL_MARK);
        string mark = markParam != null ? markParam.AsString() : null;

        columnIds.Add(column.Id);
        columnTag[column.Id] = tag;
        columnMark[column.Id] = string.IsNullOrEmpty(mark) ? column.Id.ToString() : mark.Trim();
        columnSize[column.Id] = size;
        columnPoint[column.Id] = centre;
    }
}

if (columnIds.Count == 0)
{
    Autodesk.Revit.UI.TaskDialog.Show("Column table", "No columns found in this model.");
}
else
{
    // -------------------------------------------------------- the grids --

    double onAxis = toFeet(onAxisToleranceMm);
    var gridNames = new System.Collections.Generic.List<string>();
    var gridStarts = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
    var gridDirections = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_Grids).WhereElementIsNotElementType())
    {
        var grid = e as Autodesk.Revit.DB.Grid;
        if (grid == null || grid.Curve == null) continue;
        Autodesk.Revit.DB.XYZ a = grid.Curve.GetEndPoint(0);
        Autodesk.Revit.DB.XYZ b = grid.Curve.GetEndPoint(1);
        var run = new Autodesk.Revit.DB.XYZ(b.X - a.X, b.Y - a.Y, 0);
        if (run.GetLength() < 1e-6) continue;
        gridNames.Add(grid.Name);
        gridStarts.Add(new Autodesk.Revit.DB.XYZ(a.X, a.Y, 0));
        gridDirections.Add(run.Normalize());
    }

    foreach (Autodesk.Revit.DB.ElementId id in columnIds)
    {
        Autodesk.Revit.DB.XYZ at = columnPoint[id];
        string nearestY = "", nearestX = "";
        double bestY = double.MaxValue, bestX = double.MaxValue;
        for (int i = 0; i < gridNames.Count; i++)
        {
            Autodesk.Revit.DB.XYZ start = gridStarts[i], dir = gridDirections[i];
            // Perpendicular distance in plan from the column to the grid line.
            double vx = at.X - start.X, vy = at.Y - start.Y;
            double distance = System.Math.Abs(vx * dir.Y - vy * dir.X);
            string cell = string.Format(inv, "{0}( {1} )",
                distance <= onAxis ? "ON.AXIS" : "NEAR.AXIS.", gridNames[i]);

            if (System.Math.Abs(dir.Y) >= System.Math.Abs(dir.X))
            {
                if (distance < bestY) { bestY = distance; nearestY = cell; }
            }
            else if (distance < bestX)
            {
                bestX = distance;
                nearestX = cell;
            }
        }
        columnLocationY[id] = swapAxisColumns ? nearestX : nearestY;
        columnLocationX[id] = swapAxisColumns ? nearestY : nearestX;
    }

    // ------------------------------------------- the columns of each tag --

    var taggedColumns = new System.Collections.Generic.Dictionary<string,
        System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>>();
    var tagOrder = new System.Collections.Generic.List<string>();
    foreach (Autodesk.Revit.DB.ElementId id in columnIds)
    {
        string tag = columnTag[id];
        if (tag.Length == 0) continue;
        System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> group;
        if (!taggedColumns.TryGetValue(tag, out group))
        {
            group = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
            taggedColumns.Add(tag, group);
            tagOrder.Add(tag);
        }
        group.Add(id);
    }
    tagOrder.Sort(delegate(string a, string b)
    {
        return string.Compare(a, b, System.StringComparison.OrdinalIgnoreCase);
    });
    foreach (string tag in tagOrder)
    {
        taggedColumns[tag].Sort(delegate(Autodesk.Revit.DB.ElementId a, Autodesk.Revit.DB.ElementId b)
        {
            return string.Compare(columnMark[a], columnMark[b], System.StringComparison.OrdinalIgnoreCase);
        });
    }

    // ------------------------------------------------- the views to draw on --

    var targets = new System.Collections.Generic.List<Autodesk.Revit.DB.ViewSection>();
    if (onlyTheActiveView)
    {
        var active = theDoc.ActiveView as Autodesk.Revit.DB.ViewSection;
        if (active != null) targets.Add(active);
    }
    else
    {
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfClass(typeof(Autodesk.Revit.DB.ViewSection)))
        {
            var section = e as Autodesk.Revit.DB.ViewSection;
            if (section == null || section.IsTemplate) continue;
            if (viewNameContains.Length > 0
                && section.Name.IndexOf(viewNameContains, System.StringComparison.OrdinalIgnoreCase) < 0)
                continue;
            targets.Add(section);
        }
        targets.Sort(delegate(Autodesk.Revit.DB.ViewSection a, Autodesk.Revit.DB.ViewSection b)
        {
            return string.Compare(a.Name, b.Name, System.StringComparison.OrdinalIgnoreCase);
        });
    }

    if (targets.Count == 0)
    {
        Autodesk.Revit.UI.TaskDialog.Show("Column table", onlyTheActiveView
            ? "The active view is not a section."
            : "No section is named \"" + viewNameContains + "\".");
    }
    else
    {
        // A text type to write with.
        Autodesk.Revit.DB.TextNoteType textType = null;
        Autodesk.Revit.DB.ElementId defaultTextId =
            theDoc.GetDefaultElementTypeId(Autodesk.Revit.DB.ElementTypeGroup.TextNoteType);
        if (defaultTextId != Autodesk.Revit.DB.ElementId.InvalidElementId)
            textType = theDoc.GetElement(defaultTextId) as Autodesk.Revit.DB.TextNoteType;
        if (textType == null)
        {
            foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
                .OfClass(typeof(Autodesk.Revit.DB.TextNoteType)))
            {
                textType = e as Autodesk.Revit.DB.TextNoteType;
                if (textType != null) break;
            }
        }

        if (textType == null)
        {
            Autodesk.Revit.UI.TaskDialog.Show("Column table",
                "This model has no text type, so nothing can be written.");
        }
        else
        {
            double textSizeFeet = 0.0082;   // 2.5 mm on paper
            Autodesk.Revit.DB.Parameter textSizeParam =
                textType.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.TEXT_SIZE);
            if (textSizeParam != null && textSizeParam.AsDouble() > 1e-9)
                textSizeFeet = textSizeParam.AsDouble();

            System.Action<Autodesk.Revit.DB.View, Autodesk.Revit.DB.XYZ, Autodesk.Revit.DB.XYZ> drawLine =
                (v, a, b) =>
            {
                if (a.DistanceTo(b) < 1e-7) return;
                theDoc.Create.NewDetailCurve(v, Autodesk.Revit.DB.Line.CreateBound(a, b));
            };

            System.Action<Autodesk.Revit.DB.View, string, Autodesk.Revit.DB.XYZ> write =
                (v, text, origin) =>
            {
                if (string.IsNullOrEmpty(text)) return;
                var options = new Autodesk.Revit.DB.TextNoteOptions(textType.Id);
                options.HorizontalAlignment = Autodesk.Revit.DB.HorizontalTextAlignment.Center;
                options.Rotation = 0.0;
                Autodesk.Revit.DB.TextNote.Create(theDoc, v.Id, origin, text, options);
            };

            var drawn = new System.Collections.Generic.List<string>();
            var skipped = new System.Collections.Generic.List<string>();

            using (var transaction = new Autodesk.Revit.DB.Transaction(theDoc, "Column tables"))
            {
                transaction.Start();

                foreach (Autodesk.Revit.DB.ViewSection view in targets)
                {
                    try
                    {
                        Autodesk.Revit.DB.BoundingBoxXYZ crop = view.CropBox;
                        if (crop == null)
                        {
                            skipped.Add(view.Name + ": no crop to hang the table on");
                            continue;
                        }
                        Autodesk.Revit.DB.Transform frame = crop.Transform;
                        Autodesk.Revit.DB.Transform intoCrop = frame.Inverse;

                        // Which column is this section of? The one standing
                        // inside its crop; the lowest, where a stack of them is.
                        Autodesk.Revit.DB.ElementId subject = null;
                        double lowest = double.MaxValue;
                        foreach (Autodesk.Revit.DB.ElementId id in columnIds)
                        {
                            Autodesk.Revit.DB.XYZ local = intoCrop.OfPoint(columnPoint[id]);
                            if (local.X < crop.Min.X || local.X > crop.Max.X) continue;
                            if (local.Y < crop.Min.Y || local.Y > crop.Max.Y) continue;
                            if (local.Z < crop.Min.Z || local.Z > crop.Max.Z) continue;
                            if (columnTag[id].Length == 0) continue;
                            if (columnPoint[id].Z < lowest)
                            {
                                lowest = columnPoint[id].Z;
                                subject = id;
                            }
                        }

                        // Failing that, the tag written in the view's own name.
                        string tag = subject != null ? columnTag[subject] : "";
                        if (tag.Length == 0)
                        {
                            foreach (string candidate in tagOrder)
                            {
                                if (view.Name.IndexOf(candidate, System.StringComparison.OrdinalIgnoreCase) >= 0)
                                {
                                    tag = candidate;
                                    break;
                                }
                            }
                        }
                        if (tag.Length == 0 || !taggedColumns.ContainsKey(tag))
                        {
                            skipped.Add(view.Name + ": no tagged column found in it");
                            continue;
                        }

                        System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members =
                            taggedColumns[tag];

                        // The detail number is the number in the view's name:
                        // COL SECTION - C1 - CT-01 (7 NOS) gives 01.
                        string name = view.Name;
                        int bracket = name.IndexOf('(');
                        if (bracket > 0) name = name.Substring(0, bracket);
                        name = name.Trim();
                        int lastPart = name.LastIndexOf(" - ", System.StringComparison.Ordinal);
                        string code = lastPart >= 0 ? name.Substring(lastPart + 3).Trim() : name;
                        int dash = code.LastIndexOf('-');
                        string detailNumber = dash >= 0 && dash + 1 < code.Length
                            ? code.Substring(dash + 1).Trim()
                            : string.Format(inv, "{0:00}", tagOrder.IndexOf(tag) + 1);

                        // Clear what was drawn here before, so this can be run
                        // again without stacking one table on another.
                        if (clearExistingAnnotation)
                        {
                            var stale = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                            foreach (Autodesk.Revit.DB.Element e in
                                new Autodesk.Revit.DB.FilteredElementCollector(theDoc, view.Id))
                            {
                                if (!e.ViewSpecific || e.OwnerViewId != view.Id) continue;
                                if (e is Autodesk.Revit.DB.TextNote || e is Autodesk.Revit.DB.CurveElement)
                                    stale.Add(e.Id);
                            }
                            if (stale.Count > 0) theDoc.Delete(stale);
                        }

                        // ---- the table itself ----

                        int scale = view.Scale > 0 ? view.Scale : 50;
                        double labelWidth = toFeet(tableLabelWidthMm * scale);
                        double valueWidth = toFeet(tableValueWidthMm * scale);
                        double rowHeight = toFeet(tableRowHeightMm * scale);
                        double gap = toFeet(tableGapAboveViewMm * scale);
                        double textHeight = textSizeFeet * scale;
                        double pad = (rowHeight - textHeight) / 2.0;

                        var locationY = new System.Collections.Generic.List<string>();
                        var locationX = new System.Collections.Generic.List<string>();
                        foreach (Autodesk.Revit.DB.ElementId member in members)
                        {
                            if (locationY.Count >= maxLocationRows)
                            {
                                locationY.Add(string.Format(inv, "(+{0} MORE)",
                                    members.Count - locationY.Count));
                                locationX.Add("");
                                break;
                            }
                            locationY.Add(columnLocationY[member]);
                            locationX.Add(columnLocationX[member]);
                        }
                        if (locationY.Count == 0)
                        {
                            locationY.Add("");
                            locationX.Add("");
                        }

                        int rowCount = 3 + locationY.Count + 1;  // type, number, heading, rows, detail
                        double tableWidth = labelWidth + valueWidth;
                        double tableHeight = rowCount * rowHeight;

                        // Hung above the crop, aligned with its left edge.
                        double halfWidth = (crop.Max.X - crop.Min.X) / 2.0;
                        double halfHeight = (crop.Max.Y - crop.Min.Y) / 2.0;
                        Autodesk.Revit.DB.XYZ centre = frame.OfPoint(new Autodesk.Revit.DB.XYZ(
                            (crop.Min.X + crop.Max.X) / 2.0, (crop.Min.Y + crop.Max.Y) / 2.0, 0));
                        Autodesk.Revit.DB.XYZ right = frame.BasisX;
                        Autodesk.Revit.DB.XYZ up = frame.BasisY;
                        Autodesk.Revit.DB.XYZ topLeft = centre
                            + right * (-halfWidth)
                            + up * (halfHeight + gap + tableHeight);

                        // x runs across the table, y runs down it.
                        System.Func<double, double, Autodesk.Revit.DB.XYZ> at =
                            (x, y) => topLeft + right * x + up * (-y);

                        // The frame, the label column, and the row lines. A row
                        // line inside the location block starts at the label
                        // column, because LOCATION runs on down beside them.
                        drawLine(view, at(0, 0), at(tableWidth, 0));
                        drawLine(view, at(0, tableHeight), at(tableWidth, tableHeight));
                        drawLine(view, at(0, 0), at(0, tableHeight));
                        drawLine(view, at(tableWidth, 0), at(tableWidth, tableHeight));
                        drawLine(view, at(labelWidth, 0), at(labelWidth, tableHeight));
                        for (int r = 1; r < rowCount; r++)
                        {
                            bool insideLocation = r >= 3 && r <= 2 + locationY.Count;
                            drawLine(view, at(insideLocation ? labelWidth : 0, r * rowHeight),
                                           at(tableWidth, r * rowHeight));
                        }

                        double split = labelWidth + valueWidth / 2.0;
                        drawLine(view, at(split, 2 * rowHeight),
                                       at(split, (3 + locationY.Count) * rowHeight));

                        double labelMid = labelWidth / 2.0;
                        double valueMid = labelWidth + valueWidth / 2.0;
                        double downMid = labelWidth + valueWidth / 4.0;
                        double acrossMid = labelWidth + 3.0 * valueWidth / 4.0;

                        string typeCell = tag + "(" + columnSize[members[0]] + ")";

                        write(view, "COLUMN TYPE", at(labelMid, pad));
                        write(view, typeCell, at(valueMid, pad));
                        write(view, "NUMBER", at(labelMid, rowHeight + pad));
                        write(view, members.Count.ToString(inv), at(valueMid, rowHeight + pad));

                        // LOCATION sits against the middle of its own block.
                        double locationTop = ((5 + locationY.Count) / 2.0) * rowHeight - textHeight / 2.0;
                        write(view, "LOCATION", at(labelMid, locationTop));
                        write(view, "Y-AXIS", at(downMid, 2 * rowHeight + pad));
                        write(view, "X-AXIS", at(acrossMid, 2 * rowHeight + pad));
                        for (int r = 0; r < locationY.Count; r++)
                        {
                            write(view, locationY[r], at(downMid, (3 + r) * rowHeight + pad));
                            write(view, locationX[r], at(acrossMid, (3 + r) * rowHeight + pad));
                        }

                        double detailRow = (3 + locationY.Count) * rowHeight + pad;
                        write(view, "DETAIL NUMBER", at(labelMid, detailRow));
                        write(view, detailNumber, at(valueMid, detailRow));

                        drawn.Add(string.Format(inv, "{0}  ->  {1} ({2} column{3}), detail {4}",
                            view.Name, tag, members.Count, members.Count == 1 ? "" : "s", detailNumber));
                    }
                    catch (System.Exception ex)
                    {
                        skipped.Add(view.Name + ": " + ex.Message);
                    }
                }

                transaction.Commit();
            }

            var done = new Autodesk.Revit.UI.TaskDialog("Column table");
            done.MainInstruction = string.Format(inv, "{0} table{1} drawn.",
                drawn.Count, drawn.Count == 1 ? "" : "s");
            done.MainContent = skipped.Count == 0
                ? "One on each section, above the crop."
                : string.Format(inv, "{0} section{1} skipped:\n{2}", skipped.Count,
                    skipped.Count == 1 ? "" : "s", string.Join("\n", skipped.ToArray()));
            done.ExpandedContent = string.Join("\n", drawn.ToArray());
            done.Show();
        }
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
