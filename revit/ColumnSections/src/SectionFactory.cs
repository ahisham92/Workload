using System;
using System.Collections.Generic;
using System.Linq;
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

            ViewFamilyType sectionType = new FilteredElementCollector(_doc)
                .OfClass(typeof(ViewFamilyType))
                .Cast<ViewFamilyType>()
                .FirstOrDefault(v => v.ViewFamily == ViewFamily.Section);
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
                textType = new FilteredElementCollector(_doc)
                    .OfClass(typeof(TextNoteType)).Cast<TextNoteType>().FirstOrDefault();
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

            foreach (View v in new FilteredElementCollector(_doc)
                .OfClass(typeof(View)).Cast<View>())
            {
                _usedNames.Add(v.Name);
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

            double minR = 0, maxR = 0, minU = 0, maxU = 0, minD = 0, maxD = 0;
            bool first = true;
            foreach (XYZ p in ExtentPoints(column))
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

            minR -= Units.ToFeet(_s.SideClearanceMm);
            maxR += Units.ToFeet(_s.SideClearanceMm);
            minU -= Units.ToFeet(_s.BottomClearanceMm);
            maxU += Units.ToFeet(_s.TopClearanceMm);
            minD -= Units.ToFeet(_s.ViewDepthClearanceMm);
            maxD += Units.ToFeet(_s.ViewDepthClearanceMm);

            // Leave a band above the column wide and tall enough for the note,
            // so it never lands on top of the drawing.
            string[] lines = NoteLines(group);
            double lineHeight = _textSizeFeet * _s.ViewScale * 1.4;
            double noteHeight = lineHeight * lines.Length;
            double noteWidth = lines.Max(l => l.Length)
                * _textSizeFeet * _textWidthFactor * 0.62 * _s.ViewScale;
            double inset = _textSizeFeet * _s.ViewScale;

            maxU += noteHeight + 2 * inset;
            double needed = noteWidth + 2 * inset;
            if (maxR - minR < needed)
            {
                double grow = (needed - (maxR - minR)) / 2.0;
                minR -= grow;
                maxR += grow;
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

            view.Name = UniqueName(string.Format("{0} - {1} ({2} NO{3})",
                _s.ViewNamePrefix, group.Code, group.Count, group.Count == 1 ? "" : "S"));

            _doc.Regenerate();

            // Top left of the band above the column.
            XYZ notePoint = centre
                + right * (-halfWidth + inset)
                + up * (halfHeight - inset);
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

        /// <summary>The note in the section: the count first, then why this type is
        /// its own type.</summary>
        private string[] NoteLines(ColumnTypeGroup group)
        {
            var lines = new List<string>
            {
                string.Format("{0} - {1} COLUMN{2} OF THIS TYPE",
                    group.Code, group.Count, group.Count == 1 ? "" : "S")
            };
            lines.AddRange(group.Signature.DescriptionLines());

            if (_s.MaxMarksInNote > 0)
            {
                List<string> marks = group.Members
                    .Select(m => m.Mark)
                    .Where(m => !string.IsNullOrEmpty(m))
                    .Take(_s.MaxMarksInNote)
                    .ToList();
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

        /// <summary>Corners of the column, and of the foundation under it, so the
        /// section frames both.</summary>
        private static IEnumerable<XYZ> ExtentPoints(ColumnInfo column)
        {
            foreach (XYZ p in Corners(column.Box)) yield return p;
            if (column.FoundationBox != null)
                foreach (XYZ p in Corners(column.FoundationBox)) yield return p;
            yield return column.BasePoint;
            yield return column.TopPoint;
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
