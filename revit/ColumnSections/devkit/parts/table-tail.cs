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

    if (targets.Count == 0 || textType == null)
    {
        Autodesk.Revit.UI.TaskDialog.Show("Column table", textType == null
            ? "This model has no text type, so nothing can be written."
            : (onlyTheActiveView
                ? "The active view is not a section."
                : "No section is named \"" + viewNameContains + "\"."));
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

        var drawnOn = new System.Collections.Generic.List<string>();
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

                    // Which column is this section of? The one standing inside
                    // its crop - the lowest, where a stack of them is - and from
                    // that, which type it belongs to.
                    Autodesk.Revit.DB.ElementId found = null;
                    double lowest = double.MaxValue;
                    foreach (Autodesk.Revit.DB.ElementId id in ids)
                    {
                        Autodesk.Revit.DB.XYZ local = intoCrop.OfPoint(basePointOf[id]);
                        if (local.X < crop.Min.X || local.X > crop.Max.X) continue;
                        if (local.Y < crop.Min.Y || local.Y > crop.Max.Y) continue;
                        if (local.Z < crop.Min.Z || local.Z > crop.Max.Z) continue;
                        if (basePointOf[id].Z < lowest)
                        {
                            lowest = basePointOf[id].Z;
                            found = id;
                        }
                    }

                    if (found == null || !subjectOf.ContainsKey(found))
                    {
                        skipped.Add(view.Name + ": no column stands inside its crop");
                        continue;
                    }

                    Autodesk.Revit.DB.ElementId subject = subjectOf[found];
                    string key = keyOfSubject[subject];
                    System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members = membersOf[key];
                    int index = keys.IndexOf(key);

                    // The detail number is the number in the view's name -
                    // COL SECTION - C1 - CT-01 (3 NOS) gives 01 - and the type's
                    // own number where the name does not carry one.
                    string trimmed = view.Name;
                    int bracket = trimmed.IndexOf('(');
                    if (bracket > 0) trimmed = trimmed.Substring(0, bracket);
                    trimmed = trimmed.Trim();
                    int lastPart = trimmed.LastIndexOf(" - ", System.StringComparison.Ordinal);
                    string code = lastPart >= 0 ? trimmed.Substring(lastPart + 3).Trim() : trimmed;
                    int dash = code.LastIndexOf('-');
                    string detailNumber = dash >= 0 && dash + 1 < code.Length
                        ? code.Substring(dash + 1).Trim()
                        : string.Format(inv, "{0:00}", index + 1);

                    // Clear what was drawn here before, so this can be run again
                    // without stacking one table on another.
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

                    // ---- the table ----

                    int scale = view.Scale > 0 ? view.Scale : viewScale;
                    double labelWidth = toFeet(tableLabelWidthMm * scale);
                    double valueWidth = toFeet(tableValueWidthMm * scale);
                    double rowHeight = toFeet(tableRowHeightMm * scale);
                    double gap = toFeet(tableGapAboveViewMm * scale);
                    double textHeight = textSizeFeet * scale;
                    double pad = (rowHeight - textHeight) / 2.0;

                    // One location row per column of the type - the columns the
                    // section stands for, not everything wearing the same tag.
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
                        locationY.Add(textOf[member][T_LOCATION_Y]);
                        locationX.Add(textOf[member][T_LOCATION_X]);
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

                    // The frame, the label column, and the row lines. A row line
                    // inside the location block starts at the label column,
                    // because LOCATION runs on down beside them.
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

                    string tag = textOf[subject][T_TAG];
                    string typeCell = (tag.Length > 0
                            ? tag
                            : string.Format(inv, "{0}-{1:00}", typeCodePrefix, index + 1))
                        + "(" + sizeTextOf(numberOf[subject]).Replace(" ", "") + ")";

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

                    drawnOn.Add(string.Format(inv, "{0}  ->  {1} column{2}, detail {3}",
                        view.Name, members.Count, members.Count == 1 ? "" : "s", detailNumber));
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
            drawnOn.Count, drawnOn.Count == 1 ? "" : "s");
        done.MainContent = skipped.Count == 0
            ? string.Format(inv, "{0} columns in {1} types, counted as the sections were made.",
                subjects.Count, keys.Count)
            : string.Format(inv, "{0} section{1} skipped:\n{2}", skipped.Count,
                skipped.Count == 1 ? "" : "s", string.Join("\n", skipped.ToArray()));
        done.ExpandedContent = string.Join("\n", drawnOn.ToArray());
        done.Show();
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
