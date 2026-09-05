using System;
using System.Collections.Generic;
using System.Text;
using Autodesk.Revit.DB;

namespace ColumnSections
{
    /// <summary>
    /// Draws one cross section per column type, with a note in it saying how many
    /// columns share that type.
    /// </summary>
    public class SectionFactory
    {
        private readonly Document _doc;
        private readonly Settings _s;
        private readonly HashSet<string> _usedNames =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        private ElementId _sectionTypeId = ElementId.InvalidElementId;
        private ElementId _textTypeId = ElementId.InvalidElementId;
        private readonly List<ElementId> _alwaysVisibleIds = new List<ElementId>();
        private double _textSizeFeet = 0.0082;   // 2.5 mm on paper
        private double _textWidthFactor = 1.0;

        public SectionFactory(Document doc, Settings settings)
        {
            _doc = doc;
            _s = settings ?? Settings.Default;
        }

        /// <summary>Finds the view type and text type to use. Returns false, with a
        /// reason, when the template has neither.</summary>
        public bool Prepare(out string problem)
        {
            problem = null;

            ViewFamilyType sectionType = null;
            foreach (Element e in new FilteredElementCollector(_doc).OfClass(typeof(ViewFamilyType)))
            {
                var candidate = e as ViewFamilyType;
                if (candidate != null && candidate.ViewFamily == ViewFamily.Section)
                {
                    sectionType = candidate;
                    break;
                }
            }
            if (sectionType == null)
            {
                problem = "This model has no section view type, so no section can be created.";
                return false;
            }
            _sectionTypeId = sectionType.Id;

            ElementId defaultText = _doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);
            TextNoteType textType = defaultText != ElementId.InvalidElementId
                ? _doc.GetElement(defaultText) as TextNoteType
                : null;
            if (textType == null)
            {
                foreach (Element e in new FilteredElementCollector(_doc).OfClass(typeof(TextNoteType)))
                {
                    textType = e as TextNoteType;
                    if (textType != null) break;
                }
            }
            if (textType == null)
            {
                problem = "This model has no text type, so the note cannot be written.";
                return false;
            }
            _textTypeId = textType.Id;

            Parameter size = textType.get_Parameter(BuiltInParameter.TEXT_SIZE);
            if (size != null && size.AsDouble() > 1e-9) _textSizeFeet = size.AsDouble();
            Parameter factor = textType.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE);
            if (factor != null && factor.AsDouble() > 1e-9) _textWidthFactor = factor.AsDouble();

            foreach (Element e in new FilteredElementCollector(_doc).OfClass(typeof(View)))
            {
                var view = e as View;
                if (view != null) _usedNames.Add(view.Name);
            }

            // What every section keeps, whatever column it is of: the datums, and
            // the categories the settings name - the floors above, above all.
            foreach (Element e in new FilteredElementCollector(_doc).OfClass(typeof(Level)))
            {
                _alwaysVisibleIds.Add(e.Id);
            }
            foreach (Element e in new FilteredElementCollector(_doc)
                .OfCategory(BuiltInCategory.OST_Grids).WhereElementIsNotElementType())
            {
                _alwaysVisibleIds.Add(e.Id);
            }
            foreach (BuiltInCategory bic in _s.AlwaysVisibleCategories)
            {
                foreach (Element e in new FilteredElementCollector(_doc)
                    .OfCategory(bic).WhereElementIsNotElementType())
                {
                    _alwaysVisibleIds.Add(e.Id);
                }
            }
            return true;
        }

        /// <summary>Cuts the section for one type and writes its note. Must be
        /// called inside an open transaction.</summary>
        public ViewSection Create(ColumnTypeGroup group)
        {
            ColumnInfo column = group.Representative;

            // The section looks square-on at the column's face.
            XYZ right = new XYZ(Math.Cos(column.Rotation), Math.Sin(column.Rotation), 0).Normalize();
            XYZ up = XYZ.BasisZ;
            XYZ towardsViewer = right.CrossProduct(up).Normalize();
            XYZ origin = column.BasePoint;

            // The column itself, and nothing else, decides how wide and how deep
            // the view is.
            double minR = 0, maxR = 0, minU = 0, maxU = 0, minD = 0, maxD = 0;
            bool first = true;
            foreach (XYZ p in ColumnPoints(column))
            {
                XYZ v = p - origin;
                double r = v.DotProduct(right), u = v.DotProduct(up), d = v.DotProduct(towardsViewer);
                if (first)
                {
                    minR = maxR = r; minU = maxU = u; minD = maxD = d;
                    first = false;
                    continue;
                }
                if (r < minR) minR = r; else if (r > maxR) maxR = r;
                if (u < minU) minU = u; else if (u > maxU) maxU = u;
                if (d < minD) minD = d; else if (d > maxD) maxD = d;
            }

            // The footing below and the lift above may take the view higher or
            // lower, and only so much wider. They may not take it deeper at all:
            // that is what held the far clip out at the size of the raft.
            double reachLeft = minR - Units.ToFeet(_s.MaxExtraWidthMm);
            double reachRight = maxR + Units.ToFeet(_s.MaxExtraWidthMm);
            foreach (XYZ p in NeighbourPoints(column, _s))
            {
                XYZ v = p - origin;
                double r = v.DotProduct(right), u = v.DotProduct(up);
                if (r < reachLeft) r = reachLeft; else if (r > reachRight) r = reachRight;
                if (r < minR) minR = r; else if (r > maxR) maxR = r;
                if (u < minU) minU = u; else if (u > maxU) maxU = u;
            }

            minR -= Units.ToFeet(_s.SideClearanceMm);
            maxR += Units.ToFeet(_s.SideClearanceMm);
            minU -= Units.ToFeet(_s.BottomClearanceMm);
            maxU += Units.ToFeet(_s.TopClearanceMm);
            minD -= Units.ToFeet(_s.ViewDepthClearanceMm);
            maxD += Units.ToFeet(_s.ViewDepthClearanceMm);

            string[] lines = NoteLines(group);
            double lineHeight = _textSizeFeet * _s.ViewScale * 1.4;
            double noteHeight = lineHeight * lines.Length;
            int longestLine = 0;
            foreach (string line in lines)
            {
                if (line.Length > longestLine) longestLine = line.Length;
            }
            double noteWidth = longestLine * _textSizeFeet * _textWidthFactor * 0.62 * _s.ViewScale;
            double inset = _textSizeFeet * _s.ViewScale;

            if (_s.ExpandCropForNote)
            {
                // Room for the note inside the crop, which is what makes the view
                // as wide as the note's longest line.
                maxU += noteHeight + 2 * inset;
                double needed = noteWidth + 2 * inset;
                if (maxR - minR < needed)
                {
                    double grow = (needed - (maxR - minR)) / 2.0;
                    minR -= grow;
                    maxR += grow;
                }
            }

            XYZ centre = origin
                + right * ((minR + maxR) / 2.0)
                + up * ((minU + maxU) / 2.0)
                + towardsViewer * ((minD + maxD) / 2.0);

            var transform = Transform.Identity;
            transform.Origin = centre;
            transform.BasisX = right;
            transform.BasisY = up;
            transform.BasisZ = towardsViewer;

            double halfWidth = (maxR - minR) / 2.0;
            double halfHeight = (maxU - minU) / 2.0;
            double halfDepth = (maxD - minD) / 2.0;

            var box = new BoundingBoxXYZ
            {
                Transform = transform,
                Min = new XYZ(-halfWidth, -halfHeight, -halfDepth),
                Max = new XYZ(halfWidth, halfHeight, halfDepth)
            };

            ViewSection view = ViewSection.CreateSection(_doc, _sectionTypeId, box);
            view.Scale = _s.ViewScale;
            try { view.DetailLevel = ViewDetailLevel.Fine; } catch { /* view template may lock it */ }
            try { view.CropBoxVisible = false; } catch { /* likewise */ }

            view.Name = UniqueName(string.Format("{0} - {1} ({2} NO{3})",
                _s.ViewNamePrefix, group.Code, group.Count, group.Count == 1 ? "" : "S"));

            _doc.Regenerate();

            // Hidden first, written second: a note made before this would be
            // hidden along with everything else.
            if (_s.ShowOnlyThisColumn) ShowOnly(view, column);

            // Above the crop, unless the crop was widened to hold it, so the
            // drawing stays the size of the column.
            XYZ notePoint = _s.ExpandCropForNote
                ? centre + right * (-halfWidth + inset) + up * (halfHeight - inset)
                : centre + right * (-halfWidth) + up * (halfHeight + inset + noteHeight);
            var options = new TextNoteOptions(_textTypeId)
            {
                HorizontalAlignment = HorizontalTextAlignment.Left,
                Rotation = 0.0
            };
            TextNote.Create(_doc, view.Id, notePoint, string.Join("\n", lines), options);

            group.ViewId = view.Id;
            group.ViewName = view.Name;
            return view;
        }

        /// <summary>The lifts of the stack, one line each, where there is more than
        /// one of them.</summary>
        private IEnumerable<string> LiftLines(ColumnInfo column)
        {
            if (column.Lifts.Count < 2) yield break;

            yield return string.Format("{0} LIFTS, FOUNDATION UP", column.Lifts.Count);
            for (int i = 0; i < column.Lifts.Count; i++)
            {
                if (i >= _s.MaxLiftsInNote)
                {
                    yield return string.Format("(+{0} MORE LIFTS)", column.Lifts.Count - i);
                    yield break;
                }
                ColumnSignature lift = column.Lifts[i].Signature;
                yield return string.Format("LIFT {0}: {1}  ({2:0} TO {3:0})",
                    i + 1, lift.SizeText, lift.BaseElevationMm, lift.TopElevationMm);
            }
        }

        /// <summary>Hides everything in the view but this column and what belongs to
        /// it, so the section is of the column rather than of the building.</summary>
        private void ShowOnly(View view, ColumnInfo column)
        {
            try
            {
                var keep = new List<ElementId>();
                List<ColumnInfo> lifts = column.Lifts.Count > 0
                    ? column.Lifts
                    : new List<ColumnInfo> { column };
                foreach (ColumnInfo lift in lifts)
                {
                    keep.Add(lift.Instance.Id);
                    if (lift.FoundationId != null && lift.FoundationId != ElementId.InvalidElementId)
                        keep.Add(lift.FoundationId);
                    keep.AddRange(lift.BeamIds);
                }
                if (column.Above != null) keep.Add(column.Above.Instance.Id);
                if (column.Below != null) keep.Add(column.Below.Instance.Id);
                keep.AddRange(_alwaysVisibleIds);

                view.IsolateElementsTemporary(keep);
                view.ConvertTemporaryHideIsolateToPermanent();
                _doc.Regenerate();
            }
            catch
            {
                // A view template can own the visibility settings; the section is
                // still worth having without the isolation.
            }
        }

        /// <summary>The note in the section: the count first, then why this type is
        /// its own type.</summary>
        private string[] NoteLines(ColumnTypeGroup group)
        {
            var lines = new List<string>
            {
                string.Format("{0} - {1} COLUMN{2} OF THIS TYPE",
                    group.Code, group.Count, group.Count == 1 ? "" : "S")
            };
            lines.AddRange(LiftLines(group.Representative));
            lines.AddRange(group.Signature.DescriptionLines(group.Representative.Lifts.Count > 1));

            if (_s.MaxMarksInNote > 0)
            {
                var marks = new List<string>();
                foreach (ColumnInfo member in group.Members)
                {
                    if (string.IsNullOrEmpty(member.Mark)) continue;
                    if (marks.Count >= _s.MaxMarksInNote) break;
                    marks.Add(member.Mark);
                }
                if (marks.Count > 0)
                {
                    var text = new StringBuilder("MARKS: ");
                    text.Append(string.Join(", ", marks));
                    if (group.Count > marks.Count)
                        text.AppendFormat(" (+{0} MORE)", group.Count - marks.Count);
                    lines.Add(text.ToString());
                }
            }
            return lines.ToArray();
        }

        /// <summary>The stack and nothing else: what the view is sized from. Every
        /// lift of it is in the section, foundation to roof.</summary>
        private static IEnumerable<XYZ> ColumnPoints(ColumnInfo column)
        {
            List<ColumnInfo> lifts = column.Lifts.Count > 0
                ? column.Lifts
                : new List<ColumnInfo> { column };
            foreach (ColumnInfo lift in lifts)
            {
                foreach (XYZ p in Corners(lift.Box)) yield return p;
                yield return lift.BasePoint;
                yield return lift.TopPoint;
            }
        }

        /// <summary>The foundation under it and the first stretch of the lifts above
        /// and below, so the section frames the footing and any change of size at
        /// either end - within the limits the caller puts on them.</summary>
        private static IEnumerable<XYZ> NeighbourPoints(ColumnInfo column, Settings s)
        {
            if (column.FoundationBox != null)
                foreach (XYZ p in Corners(column.FoundationBox)) yield return p;

            // Below the base whatever happens, so the footing is in the view even
            // where none was found to measure.
            yield return new XYZ(column.BasePoint.X, column.BasePoint.Y,
                column.BasePoint.Z - Units.ToFeet(s.AlwaysShowBelowBaseMm));

            if (s.OneSectionPerStack) yield break;

            // Without stacks, the lifts either side are glimpsed, not drawn whole.
            if (column.Above != null && column.Above.Box != null)
            {
                double ceiling = column.TopPoint.Z + Units.ToFeet(s.StackShowAboveMm);
                foreach (XYZ p in Corners(column.Above.Box))
                    yield return new XYZ(p.X, p.Y, Math.Min(p.Z, ceiling));
            }
            if (column.Below != null && column.Below.Box != null)
            {
                double floor = column.BasePoint.Z - Units.ToFeet(s.StackShowBelowMm);
                foreach (XYZ p in Corners(column.Below.Box))
                    yield return new XYZ(p.X, p.Y, Math.Max(p.Z, floor));
            }
        }

        private static IEnumerable<XYZ> Corners(BoundingBoxXYZ box)
        {
            Transform t = box.Transform ?? Transform.Identity;
            double[] xs = { box.Min.X, box.Max.X };
            double[] ys = { box.Min.Y, box.Max.Y };
            double[] zs = { box.Min.Z, box.Max.Z };
            foreach (double x in xs)
                foreach (double y in ys)
                    foreach (double z in zs)
                        yield return t.OfPoint(new XYZ(x, y, z));
        }

        private string UniqueName(string wanted)
        {
            string clean = Clean(wanted);
            string name = clean;
            int n = 2;
            while (_usedNames.Contains(name))
            {
                name = clean + " " + n;
                n++;
            }
            _usedNames.Add(name);
            return name;
        }

        private static string Clean(string name)
        {
            var bad = new[] { '\\', ':', '{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~' };
            var text = new StringBuilder(name.Length);
            foreach (char c in name)
                text.Append(Array.IndexOf(bad, c) >= 0 ? '-' : c);
            return text.ToString().Trim();
        }
    }
}
