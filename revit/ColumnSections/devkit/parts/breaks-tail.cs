    // ------------------------------------------------ the break line family --

    Autodesk.Revit.DB.FamilySymbol breakSymbol = null;
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfClass(typeof(Autodesk.Revit.DB.FamilySymbol))
        .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_DetailComponents))
    {
        var symbol = e as Autodesk.Revit.DB.FamilySymbol;
        if (symbol == null || symbol.Family == null) continue;
        if (!string.Equals(symbol.Family.Name, breakFamilyName, System.StringComparison.OrdinalIgnoreCase))
            continue;
        if (breakTypeName.Length > 0
            && !string.Equals(symbol.Name, breakTypeName, System.StringComparison.OrdinalIgnoreCase))
        {
            if (breakSymbol == null) breakSymbol = symbol;   // the family at least
            continue;
        }
        breakSymbol = symbol;
        break;
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

    if (breakSymbol == null || targets.Count == 0)
    {
        Autodesk.Revit.UI.TaskDialog.Show("Column break lines", breakSymbol == null
            ? "No detail item family called \"" + breakFamilyName
              + "\" is loaded in this project. Load it and run this again."
            : (onlyTheActiveView
                ? "The active view is not a section."
                : "No section is named \"" + viewNameContains + "\"."));
    }
    else
    {
        var placed = new System.Collections.Generic.List<string>();
        var skipped = new System.Collections.Generic.List<string>();
        int placedCount = 0;

        using (var transaction = new Autodesk.Revit.DB.Transaction(theDoc, "Column break lines"))
        {
            transaction.Start();

            if (!breakSymbol.IsActive)
            {
                breakSymbol.Activate();
                theDoc.Regenerate();
            }

            foreach (Autodesk.Revit.DB.ViewSection view in targets)
            {
                try
                {
                    Autodesk.Revit.DB.BoundingBoxXYZ crop = view.CropBox;
                    if (crop == null)
                    {
                        skipped.Add(view.Name + ": no crop to measure the edges of");
                        continue;
                    }
                    Autodesk.Revit.DB.Transform frame = crop.Transform;

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

                    if (found == null || !subjectOf.ContainsKey(found))
                    {
                        skipped.Add(view.Name + ": no column of this model stands within "
                            + string.Format(inv, "{0:0}", matchToleranceMm) + "mm of it");
                        continue;
                    }
                    Autodesk.Revit.DB.ElementId subject = subjectOf[found];

                    // Clear the break lines put here by an earlier run.
                    if (replaceExistingBreakLines)
                    {
                        var stale = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                        foreach (Autodesk.Revit.DB.Element e in
                            new Autodesk.Revit.DB.FilteredElementCollector(theDoc, view.Id)
                            .OfClass(typeof(Autodesk.Revit.DB.FamilyInstance)))
                        {
                            var instance = e as Autodesk.Revit.DB.FamilyInstance;
                            if (instance == null || !instance.ViewSpecific) continue;
                            if (instance.OwnerViewId != view.Id) continue;
                            if (instance.Symbol == null || instance.Symbol.Family == null) continue;
                            if (string.Equals(instance.Symbol.Family.Name, breakFamilyName,
                                System.StringComparison.OrdinalIgnoreCase))
                                stale.Add(instance.Id);
                        }
                        if (stale.Count > 0) theDoc.Delete(stale);
                    }

                    // The members drawn beside this column: its footing, the beams
                    // framing in, the slabs it meets - lift by lift.
                    var beside = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                    foreach (Autodesk.Revit.DB.ElementId lift in chainOf[subject])
                    {
                        if (foundationIdOf.ContainsKey(lift)) beside.Add(foundationIdOf[lift]);
                        if (beamIdsOf.ContainsKey(lift)) beside.AddRange(beamIdsOf[lift]);
                        if (floorIdsOf.ContainsKey(lift)) beside.AddRange(floorIdsOf[lift]);
                    }

                    double halfWidth = (crop.Max.X - crop.Min.X) / 2.0;
                    double halfHeight = (crop.Max.Y - crop.Min.Y) / 2.0;
                    double midX = (crop.Min.X + crop.Max.X) / 2.0;
                    double midY = (crop.Min.Y + crop.Max.Y) / 2.0;
                    Autodesk.Revit.DB.Transform intoCrop = frame.Inverse;
                    double edgeInset = toFeet(breakLineInsetMm * (view.Scale > 0 ? view.Scale : viewScale));
                    double turn = breakLineRotationDegrees * System.Math.PI / 180.0;

                    var alreadyBroken = new System.Collections.Generic.HashSet<string>();
                    foreach (Autodesk.Revit.DB.ElementId memberId in beside)
                    {
                        Autodesk.Revit.DB.Element member = theDoc.GetElement(memberId);
                        if (member == null) continue;
                        Autodesk.Revit.DB.BoundingBoxXYZ bb = member.get_BoundingBox(null);
                        if (bb == null) continue;

                        // Its reach across the view, and its thickness up it.
                        double memberMinX = double.MaxValue, memberMaxX = double.MinValue;
                        double memberMinY = double.MaxValue, memberMaxY = double.MinValue;
                        foreach (Autodesk.Revit.DB.XYZ corner in cornersOf(bb))
                        {
                            Autodesk.Revit.DB.XYZ local = intoCrop.OfPoint(corner);
                            if (local.X < memberMinX) memberMinX = local.X;
                            if (local.X > memberMaxX) memberMaxX = local.X;
                            if (local.Y < memberMinY) memberMinY = local.Y;
                            if (local.Y > memberMaxY) memberMaxY = local.Y;
                        }

                        double lowY = System.Math.Max(memberMinY, crop.Min.Y);
                        double highY = System.Math.Min(memberMaxY, crop.Max.Y);
                        if (highY - lowY < 1e-6) continue;

                        for (int side = 0; side < 2; side++)
                        {
                            bool leftSide = side == 0;
                            if (leftSide && memberMinX > crop.Min.X + 1e-6) continue;
                            if (!leftSide && memberMaxX < crop.Max.X - 1e-6) continue;

                            double x = leftSide ? crop.Min.X + edgeInset : crop.Max.X - edgeInset;
                            double y = (lowY + highY) / 2.0;
                            string place = string.Format(inv, "{0}:{1:0.000}", leftSide ? "L" : "R", y);
                            if (!alreadyBroken.Add(place)) continue;

                            Autodesk.Revit.DB.XYZ where = frame.OfPoint(
                                new Autodesk.Revit.DB.XYZ(x, y, 0));
                            Autodesk.Revit.DB.FamilyInstance broken =
                                theDoc.Create.NewFamilyInstance(where, breakSymbol, view);
                            placedCount++;

                            // Turned to cut across the member rather than along it.
                            if (System.Math.Abs(turn) > 1e-9)
                            {
                                Autodesk.Revit.DB.Line axis = Autodesk.Revit.DB.Line.CreateBound(
                                    where, where + frame.BasisZ);
                                Autodesk.Revit.DB.ElementTransformUtils.RotateElement(
                                    theDoc, broken.Id, axis, turn);
                            }

                            // Sized to what it breaks, where the family says how.
                            double thickness = highY - lowY;
                            foreach (string name in breakLengthParameterNames)
                            {
                                Autodesk.Revit.DB.Parameter p = broken.LookupParameter(name);
                                if (p == null || p.IsReadOnly
                                    || p.StorageType != Autodesk.Revit.DB.StorageType.Double) continue;
                                try { p.Set(thickness); }
                                catch { /* the family may hold it to a formula */ }
                                break;
                            }
                        }
                    }

                    placed.Add(string.Format(inv, "{0}  ->  {1} break line{2}",
                        view.Name, alreadyBroken.Count, alreadyBroken.Count == 1 ? "" : "s"));
                }
                catch (System.Exception ex)
                {
                    skipped.Add(view.Name + ": " + ex.Message);
                }
            }

            transaction.Commit();
        }

        var done = new Autodesk.Revit.UI.TaskDialog("Column break lines");
        done.MainInstruction = string.Format(inv, "{0} break line{1} placed on {2} section{3}.",
            placedCount, placedCount == 1 ? "" : "s", placed.Count, placed.Count == 1 ? "" : "s");
        done.MainContent = skipped.Count == 0
            ? breakFamilyName + " : " + breakSymbol.Name
            : string.Format(inv, "{0} : {1}\n\n{2} section{3} to look at:\n{4}",
                breakFamilyName, breakSymbol.Name, skipped.Count,
                skipped.Count == 1 ? "" : "s", string.Join("\n", skipped.ToArray()));
        done.ExpandedContent = string.Join("\n", placed.ToArray());
        done.Show();
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
