    // ------------------------------- the detail number each type is drawn on --

    // Read off the section views where they exist, so a bubble on the plan and
    // the section it points at carry the same number.
    var detailNumberOf = new System.Collections.Generic.Dictionary<string, string>();
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfClass(typeof(Autodesk.Revit.DB.ViewSection)))
    {
        var section = e as Autodesk.Revit.DB.ViewSection;
        if (section == null || section.IsTemplate) continue;
        if (viewNameContains.Length > 0
            && section.Name.IndexOf(viewNameContains, System.StringComparison.OrdinalIgnoreCase) < 0)
            continue;

        Autodesk.Revit.DB.XYZ eye = section.Origin;
        double reach = toFeet(matchToleranceMm);
        Autodesk.Revit.DB.ElementId found = null;
        double nearest = double.MaxValue;
        foreach (Autodesk.Revit.DB.ElementId id in ids)
        {
            Autodesk.Revit.DB.XYZ stands = basePointOf[id];
            double dx = stands.X - eye.X, dy = stands.Y - eye.Y;
            double distance = System.Math.Sqrt(dx * dx + dy * dy);
            if (distance > reach) continue;
            if (distance < nearest - 1e-6) { nearest = distance; found = id; }
        }
        if (found == null || !subjectOf.ContainsKey(found)) continue;

        string trimmed = section.Name;
        int bracket = trimmed.IndexOf('(');
        if (bracket > 0) trimmed = trimmed.Substring(0, bracket);
        trimmed = trimmed.Trim();
        int lastPart = trimmed.LastIndexOf(" - ", System.StringComparison.Ordinal);
        string code = lastPart >= 0 ? trimmed.Substring(lastPart + 3).Trim() : trimmed;
        int dash = code.LastIndexOf('-');
        if (dash < 0 || dash + 1 >= code.Length) continue;
        detailNumberOf[keyOfSubject[subjectOf[found]]] = code.Substring(dash + 1).Trim();
    }

    // ------------------------------------------------------- the plan to do --

    var plans = new System.Collections.Generic.List<Autodesk.Revit.DB.ViewPlan>();
    var activePlan = theDoc.ActiveView as Autodesk.Revit.DB.ViewPlan;
    if (onlyTheActiveView)
    {
        if (activePlan != null) plans.Add(activePlan);
    }
    else
    {
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfClass(typeof(Autodesk.Revit.DB.ViewPlan)))
        {
            var plan = e as Autodesk.Revit.DB.ViewPlan;
            if (plan == null || plan.IsTemplate || plan.GenLevel == null) continue;
            plans.Add(plan);
        }
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

    if (plans.Count == 0 || textType == null)
    {
        Autodesk.Revit.UI.TaskDialog.Show("Column plan tags", textType == null
            ? "This model has no text type, so nothing can be written."
            : "Open the plan you want tagged and run this again.");
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

        System.Action<Autodesk.Revit.DB.View, string, Autodesk.Revit.DB.XYZ,
            Autodesk.Revit.DB.HorizontalTextAlignment> write = (v, text, origin, align) =>
        {
            if (string.IsNullOrEmpty(text)) return;
            var options = new Autodesk.Revit.DB.TextNoteOptions(textType.Id);
            options.HorizontalAlignment = align;
            options.Rotation = 0.0;
            Autodesk.Revit.DB.TextNote.Create(theDoc, v.Id, origin, text, options);
        };

        var tagged = new System.Collections.Generic.List<string>();
        var skipped = new System.Collections.Generic.List<string>();
        int taggedCount = 0, leftAlone = 0;

        using (var transaction = new Autodesk.Revit.DB.Transaction(theDoc, "Column plan tags"))
        {
            transaction.Start();

            foreach (Autodesk.Revit.DB.ViewPlan plan in plans)
            {
                try
                {
                    if (plan.GenLevel == null)
                    {
                        skipped.Add(plan.Name + ": not a level's plan");
                        continue;
                    }

                    int scale = plan.Scale > 0 ? plan.Scale : viewScale;
                    double planZ = plan.Origin != null ? plan.Origin.Z : plan.GenLevel.Elevation;
                    double cutAt = plan.GenLevel.Elevation + toFeet(planCutOffsetMm);
                    Autodesk.Revit.DB.XYZ right = plan.RightDirection;
                    Autodesk.Revit.DB.XYZ up = plan.UpDirection;

                    double labelOut = toFeet(planLabelOffsetMm * scale);
                    double bubbleOut = toFeet(planBubbleOffsetMm * scale);
                    double radiusX = toFeet(planBubbleRadiusXMm * scale);
                    double radiusY = toFeet(planBubbleRadiusYMm * scale);
                    double arrow = toFeet(planArrowMm * scale);
                    double textHeight = textSizeFeet * scale;
                    double alreadyNear = toFeet(4.0 * scale);

                    // What is already written on this plan, so a column somebody
                    // has tagged by hand is left alone.
                    var written = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
                    if (skipWhereAlreadyTagged)
                    {
                        foreach (Autodesk.Revit.DB.Element e in
                            new Autodesk.Revit.DB.FilteredElementCollector(theDoc, plan.Id)
                            .OfClass(typeof(Autodesk.Revit.DB.TextNote)))
                        {
                            var note = e as Autodesk.Revit.DB.TextNote;
                            if (note != null) written.Add(note.Coord);
                        }
                    }

                    int onThisPlan = 0;
                    foreach (Autodesk.Revit.DB.ElementId id in ids)
                    {
                        double[] n = numberOf[id];
                        // Only the columns this plan cuts.
                        if (cutAt < n[N_BASE_Z_FT] - 1e-6 || cutAt > n[N_TOP_Z_FT] + 1e-6) continue;

                        Autodesk.Revit.DB.XYZ stands = basePointOf[id];
                        Autodesk.Revit.DB.XYZ point = new Autodesk.Revit.DB.XYZ(
                            stands.X, stands.Y, planZ);

                        Autodesk.Revit.DB.XYZ labelAt = point + right * labelOut;
                        if (skipWhereAlreadyTagged)
                        {
                            bool taken = false;
                            foreach (Autodesk.Revit.DB.XYZ where in written)
                            {
                                if (where.DistanceTo(labelAt) < alreadyNear) { taken = true; break; }
                            }
                            if (taken)
                            {
                                leftAlone++;
                                continue;
                            }
                        }

                        string tag = textOf[id][T_TAG];
                        string size = sizeTextOf(n).Replace(" ", "");
                        string detail = "";
                        if (subjectOf.ContainsKey(id))
                        {
                            string key = keyOfSubject[subjectOf[id]];
                            if (detailNumberOf.ContainsKey(key))
                            {
                                detail = detailNumberOf[key];
                            }
                            else
                            {
                                detail = string.Format(inv, "{0:00}", keys.IndexOf(key) + 1);
                            }
                        }
                        if (tag.Length == 0) tag = typeCodePrefix + "-" + detail;

                        // On the right: the tag, and the size under it.
                        write(plan, tag + "\n" + string.Format(inv, planSizeFormat, size),
                            labelAt + up * (textHeight / 2.0),
                            Autodesk.Revit.DB.HorizontalTextAlignment.Left);

                        // On the left: the bubble, the line across it, the tag
                        // above and the detail number below.
                        Autodesk.Revit.DB.XYZ centre = point - right * bubbleOut;
                        try
                        {
                            Autodesk.Revit.DB.Curve top = Autodesk.Revit.DB.Ellipse.CreateCurve(
                                centre, radiusX, radiusY, right, up, 0.0, System.Math.PI);
                            Autodesk.Revit.DB.Curve bottom = Autodesk.Revit.DB.Ellipse.CreateCurve(
                                centre, radiusX, radiusY, right, up, System.Math.PI, 2.0 * System.Math.PI);
                            theDoc.Create.NewDetailCurve(plan, top);
                            theDoc.Create.NewDetailCurve(plan, bottom);
                        }
                        catch
                        {
                            // No ellipse to be had: a box will do.
                            drawLine(plan, centre + right * -radiusX + up * radiusY,
                                           centre + right * radiusX + up * radiusY);
                            drawLine(plan, centre + right * -radiusX - up * radiusY,
                                           centre + right * radiusX - up * radiusY);
                            drawLine(plan, centre + right * -radiusX - up * radiusY,
                                           centre + right * -radiusX + up * radiusY);
                            drawLine(plan, centre + right * radiusX - up * radiusY,
                                           centre + right * radiusX + up * radiusY);
                        }

                        drawLine(plan, centre - right * radiusX, centre + right * radiusX);
                        write(plan, tag, centre + up * (textHeight + textHeight / 4.0),
                            Autodesk.Revit.DB.HorizontalTextAlignment.Center);
                        write(plan, detail, centre - up * (textHeight / 4.0),
                            Autodesk.Revit.DB.HorizontalTextAlignment.Center);

                        // The leader, from the bubble to the face of the column.
                        double halfSide = toFeet(System.Math.Max(n[N_WIDTH], n[N_DEPTH])) / 2.0;
                        Autodesk.Revit.DB.XYZ tip = point - right * halfSide;
                        Autodesk.Revit.DB.XYZ from = centre + right * radiusX;
                        drawLine(plan, from, tip);

                        // Its head: two strokes back along the leader.
                        Autodesk.Revit.DB.XYZ along = (tip - from);
                        if (along.GetLength() > 1e-9)
                        {
                            along = along.Normalize();
                            Autodesk.Revit.DB.XYZ across = up.CrossProduct(along).Normalize();
                            drawLine(plan, tip, tip - along * arrow + across * (arrow / 3.0));
                            drawLine(plan, tip, tip - along * arrow - across * (arrow / 3.0));
                        }

                        taggedCount++;
                        onThisPlan++;
                    }

                    tagged.Add(string.Format(inv, "{0}  ->  {1} column{2}",
                        plan.Name, onThisPlan, onThisPlan == 1 ? "" : "s"));
                }
                catch (System.Exception ex)
                {
                    skipped.Add(plan.Name + ": " + ex.Message);
                }
            }

            transaction.Commit();
        }

        var done = new Autodesk.Revit.UI.TaskDialog("Column plan tags");
        done.MainInstruction = string.Format(inv, "{0} column{1} tagged.",
            taggedCount, taggedCount == 1 ? "" : "s");
        done.MainContent = string.Format(inv,
            "{0} left alone, having something written beside them already.{1}",
            leftAlone,
            skipped.Count == 0 ? "" : "\n\n" + string.Join("\n", skipped.ToArray()));
        done.ExpandedContent = string.Join("\n", tagged.ToArray());
        done.Show();
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
