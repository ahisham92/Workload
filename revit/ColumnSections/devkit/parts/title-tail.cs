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
        Autodesk.Revit.UI.TaskDialog.Show("Column section titles", textType == null
            ? "This model has no text type, so nothing can be written."
            : (onlyTheActiveView
                ? "The active view is not a section."
                : "No section is named \"" + viewNameContains + "\"."));
    }
    else
    {
        double textSizeFeet = 0.0082;   // 2.5 mm on paper
        double textWidthFactor = 1.0;
        Autodesk.Revit.DB.Parameter textSizeParam =
            textType.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.TEXT_SIZE);
        if (textSizeParam != null && textSizeParam.AsDouble() > 1e-9)
            textSizeFeet = textSizeParam.AsDouble();
        Autodesk.Revit.DB.Parameter widthFactorParam =
            textType.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.TEXT_WIDTH_SCALE);
        if (widthFactorParam != null && widthFactorParam.AsDouble() > 1e-9)
            textWidthFactor = widthFactorParam.AsDouble();

        System.Action<Autodesk.Revit.DB.View, Autodesk.Revit.DB.XYZ, Autodesk.Revit.DB.XYZ> drawLine =
            (v, a, b) =>
        {
            if (a.DistanceTo(b) < 1e-7) return;
            theDoc.Create.NewDetailCurve(v, Autodesk.Revit.DB.Line.CreateBound(a, b));
        };

        System.Action<Autodesk.Revit.DB.View, string, Autodesk.Revit.DB.XYZ,
            Autodesk.Revit.DB.HorizontalTextAlignment> write = (v, text, origin, align) =>
        {
            if (string.IsNullOrEmpty(text)) return;
            var options = new Autodesk.Revit.DB.TextNoteOptions(textType.Id);
            options.HorizontalAlignment = align;
            options.Rotation = 0.0;
            Autodesk.Revit.DB.TextNote.Create(theDoc, v.Id, origin, text, options);
        };

        var titled = new System.Collections.Generic.List<string>();
        var skipped = new System.Collections.Generic.List<string>();

        using (var transaction = new Autodesk.Revit.DB.Transaction(theDoc, "Column section titles"))
        {
            transaction.Start();

            foreach (Autodesk.Revit.DB.ViewSection view in targets)
            {
                try
                {
                    Autodesk.Revit.DB.BoundingBoxXYZ crop = view.CropBox;
                    if (crop == null)
                    {
                        skipped.Add(view.Name + ": no crop to hang the title under");
                        continue;
                    }
                    Autodesk.Revit.DB.Transform frame = crop.Transform;
                    Autodesk.Revit.DB.Transform intoCrop = frame.Inverse;

                    // Which column is this section of? The one nearest its origin
                    // in plan - the section was cut on it.
                    Autodesk.Revit.DB.XYZ eye = view.Origin;
                    double reach = toFeet(matchToleranceMm);
                    Autodesk.Revit.DB.ElementId found = null;
                    double nearest = double.MaxValue;
                    foreach (Autodesk.Revit.DB.ElementId id in ids)
                    {
                        Autodesk.Revit.DB.XYZ stands = basePointOf[id];
                        double dx = stands.X - eye.X, dy = stands.Y - eye.Y;
                        double distance = System.Math.Sqrt(dx * dx + dy * dy);
                        if (distance > reach) continue;
                        if (distance < nearest - 1e-6
                            || (System.Math.Abs(distance - nearest) < 1e-6
                                && found != null && stands.Z < basePointOf[found].Z))
                        {
                            nearest = distance;
                            found = id;
                        }
                    }

                    string key = null;
                    if (found != null && subjectOf.ContainsKey(found))
                    {
                        key = keyOfSubject[subjectOf[found]];
                    }
                    else
                    {
                        for (int k = 0; k < keys.Count; k++)
                        {
                            string wanted = string.Format(inv, "{0}-{1:00}", typeCodePrefix, k + 1);
                            if (view.Name.IndexOf(wanted, System.StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                key = keys[k];
                                break;
                            }
                        }
                    }
                    if (key == null)
                    {
                        skipped.Add(view.Name + ": no column of this model stands within "
                            + string.Format(inv, "{0:0}", matchToleranceMm)
                            + "mm of it, and its name carries no type code");
                        continue;
                    }

                    Autodesk.Revit.DB.ElementId subject = membersOf[key][0];
                    int index = keys.IndexOf(key);

                    // The detail number is the number in the view's name -
                    // COL SECTION - 01-C04 - CT-27 gives 27.
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

                    string tag = textOf[subject][T_TAG];
                    if (tag.Length == 0)
                        tag = string.Format(inv, "{0}-{1:00}", typeCodePrefix, index + 1);

                    int scale = view.Scale > 0 ? view.Scale : viewScale;
                    string line1 = string.Format(inv, titleLine1Format, tag);
                    string line2 = string.Format(inv, titleLine2Format, detailNumber);
                    string scaleText = string.Format(inv, titleScaleFormat, scale);
                    string detailText = string.Format(inv, titleDetailFormat, detailNumber);

                    // ---- how big the title is ----

                    double rowHeight = toFeet(titleRowHeightMm * scale);
                    double margin = toFeet(titleMarginMm * scale);
                    double innerInset = toFeet(titleInnerInsetMm * scale);
                    double gap = toFeet(titleGapBelowMm * scale);
                    double textHeight = textSizeFeet * scale;
                    double pad = (rowHeight - textHeight) / 2.0;

                    int longest = line1.Length;
                    if (line2.Length > longest) longest = line2.Length;
                    if (scaleText.Length + detailText.Length + 6 > longest)
                        longest = scaleText.Length + detailText.Length + 6;
                    double needed = longest * textSizeFeet * textWidthFactor * 0.62 * scale
                        + 2 * (margin + innerInset);

                    double cropWidth = crop.Max.X - crop.Min.X;
                    double titleWidth = System.Math.Max(cropWidth, needed);
                    double titleHeight = 3 * rowHeight;
                    double middleX = (crop.Min.X + crop.Max.X) / 2.0;

                    // Hung under the lowest thing the section draws - the footing
                    // where there is one - so it does not creep down the page on
                    // every run.
                    double lowest = double.MaxValue;
                    foreach (Autodesk.Revit.DB.ElementId lift in chainOf[subject])
                    {
                        double y = intoCrop.OfPoint(basePointOf[lift]).Y;
                        if (y < lowest) lowest = y;
                        if (foundationBoxOf.ContainsKey(lift))
                        {
                            foreach (Autodesk.Revit.DB.XYZ corner in cornersOf(foundationBoxOf[lift]))
                            {
                                double cy = intoCrop.OfPoint(corner).Y;
                                if (cy < lowest) lowest = cy;
                            }
                        }
                    }
                    if (lowest == double.MaxValue) lowest = crop.Min.Y;

                    double titleTop = lowest - gap;
                    double titleBottom = titleTop - titleHeight;
                    double titleLeft = middleX - titleWidth / 2.0;
                    double titleRight = middleX + titleWidth / 2.0;

                    // Clear the title drawn here before - everything below the
                    // line the title hangs from, and nothing above it.
                    if (replaceExistingTitle)
                    {
                        double cutOff = titleTop + gap / 2.0;
                        var stale = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                        foreach (Autodesk.Revit.DB.Element e in
                            new Autodesk.Revit.DB.FilteredElementCollector(theDoc, view.Id))
                        {
                            if (!e.ViewSpecific || e.OwnerViewId != view.Id) continue;
                            var note = e as Autodesk.Revit.DB.TextNote;
                            var curve = e as Autodesk.Revit.DB.CurveElement;
                            double where;
                            if (note != null)
                            {
                                where = intoCrop.OfPoint(note.Coord).Y;
                            }
                            else if (curve != null && curve.GeometryCurve != null)
                            {
                                where = System.Math.Max(
                                    intoCrop.OfPoint(curve.GeometryCurve.GetEndPoint(0)).Y,
                                    intoCrop.OfPoint(curve.GeometryCurve.GetEndPoint(1)).Y);
                            }
                            else continue;
                            if (where < cutOff) stale.Add(e.Id);
                        }
                        if (stale.Count > 0) theDoc.Delete(stale);
                    }

                    // ---- the box ----

                    System.Func<double, double, Autodesk.Revit.DB.XYZ> at =
                        (x, y) => frame.OfPoint(new Autodesk.Revit.DB.XYZ(x, y, 0));

                    drawLine(view, at(titleLeft, titleTop), at(titleRight, titleTop));
                    drawLine(view, at(titleLeft, titleBottom), at(titleRight, titleBottom));
                    drawLine(view, at(titleLeft, titleBottom), at(titleLeft, titleTop));
                    drawLine(view, at(titleRight, titleBottom), at(titleRight, titleTop));

                    // The inner box, round the two lines of the title.
                    double innerLeft = titleLeft + innerInset;
                    double innerRight = titleRight - innerInset;
                    double innerTop = titleTop - innerInset;
                    double innerBottom = titleTop - 2 * rowHeight;
                    drawLine(view, at(innerLeft, innerTop), at(innerRight, innerTop));
                    drawLine(view, at(innerLeft, innerBottom), at(innerRight, innerBottom));
                    drawLine(view, at(innerLeft, innerBottom), at(innerLeft, innerTop));
                    drawLine(view, at(innerRight, innerBottom), at(innerRight, innerTop));

                    // ---- the words ----

                    write(view, line1, at(middleX, titleTop - pad - innerInset),
                        Autodesk.Revit.DB.HorizontalTextAlignment.Center);
                    write(view, line2, at(middleX, titleTop - rowHeight - pad),
                        Autodesk.Revit.DB.HorizontalTextAlignment.Center);

                    if (underlineSecondLine)
                    {
                        double half = line2.Length * textSizeFeet * textWidthFactor * 0.62 * scale / 2.0;
                        double under = titleTop - 2 * rowHeight + pad / 2.0;
                        drawLine(view, at(middleX - half, under), at(middleX + half, under));
                    }

                    write(view, scaleText, at(titleLeft + margin, titleBottom + rowHeight - pad),
                        Autodesk.Revit.DB.HorizontalTextAlignment.Left);
                    write(view, detailText, at(titleRight - margin, titleBottom + rowHeight - pad),
                        Autodesk.Revit.DB.HorizontalTextAlignment.Right);

                    // The crop cuts detail lines, so it has to take the title in.
                    if (growCropForTitle)
                    {
                        Autodesk.Revit.DB.BoundingBoxXYZ grown = view.CropBox;
                        grown.Min = new Autodesk.Revit.DB.XYZ(
                            System.Math.Min(grown.Min.X, titleLeft - margin),
                            System.Math.Min(grown.Min.Y, titleBottom - margin),
                            grown.Min.Z);
                        grown.Max = new Autodesk.Revit.DB.XYZ(
                            System.Math.Max(grown.Max.X, titleRight + margin),
                            grown.Max.Y, grown.Max.Z);
                        view.CropBox = grown;
                    }

                    titled.Add(string.Format(inv, "{0}  ->  {1}, detail {2}, 1:{3}",
                        view.Name, tag, detailNumber, scale));
                }
                catch (System.Exception ex)
                {
                    skipped.Add(view.Name + ": " + ex.Message);
                }
            }

            transaction.Commit();
        }

        var done = new Autodesk.Revit.UI.TaskDialog("Column section titles");
        done.MainInstruction = string.Format(inv, "{0} title{1} drawn.",
            titled.Count, titled.Count == 1 ? "" : "s");
        done.MainContent = skipped.Count == 0
            ? "One under each section."
            : string.Format(inv, "{0} section{1} to look at:\n{2}", skipped.Count,
                skipped.Count == 1 ? "" : "s", string.Join("\n", skipped.ToArray()));
        done.ExpandedContent = string.Join("\n", titled.ToArray());
        done.Show();
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
