using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;

namespace ColumnSections
{
    /// <summary>
    /// Reads the model: measures every column, looks for the foundation under it
    /// and the beams framing into it, and sorts the lot into types.
    /// </summary>
    public class ColumnScanner
    {
        private readonly Document _doc;
        private readonly Settings _s;
        private readonly List<FoundationRef> _foundations = new List<FoundationRef>();
        private readonly List<BeamRef> _beams = new List<BeamRef>();
        private double _groundElevation;

        public string GroundLevelName { get; private set; }

        public ColumnScanner(Document doc, Settings settings)
        {
            _doc = doc;
            _s = settings ?? Settings.Default;
            GroundLevelName = "";
        }

        // -----------------------------------------------------------------
        // Entry point
        // -----------------------------------------------------------------

        public List<ColumnTypeGroup> Scan(IEnumerable<FamilyInstance> columns)
        {
            LoadContext();

            var byKey = new Dictionary<string, ColumnTypeGroup>();
            foreach (FamilyInstance column in columns)
            {
                ColumnInfo info = Measure(column);
                if (info == null) continue;

                ColumnTypeGroup group;
                if (!byKey.TryGetValue(info.Signature.Key, out group))
                {
                    group = new ColumnTypeGroup { Signature = info.Signature };
                    byKey.Add(info.Signature.Key, group);
                }
                group.Members.Add(info);
            }

            // Most common type first, so CT-01 is the one that repeats most.
            List<ColumnTypeGroup> groups = byKey.Values
                .OrderByDescending(g => g.Count)
                .ThenBy(g => g.Signature.SizeText, StringComparer.OrdinalIgnoreCase)
                .ThenBy(g => g.Signature.Key, StringComparer.Ordinal)
                .ToList();

            for (int i = 0; i < groups.Count; i++)
            {
                groups[i].Members.Sort((a, b) =>
                    string.Compare(a.Mark, b.Mark, StringComparison.OrdinalIgnoreCase));
                groups[i].Code = string.Format("{0}-{1:00}", _s.TypeCodePrefix, i + 1);
            }
            return groups;
        }

        /// <summary>Every structural column in the model.</summary>
        public static List<FamilyInstance> AllColumns(Document doc)
        {
            var columns = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_StructuralColumns)
                .OfClass(typeof(FamilyInstance))
                .WhereElementIsNotElementType()
                .Cast<FamilyInstance>()
                .ToList();

            // Architectural columns count too, if that is all the model has.
            columns.AddRange(new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Columns)
                .OfClass(typeof(FamilyInstance))
                .WhereElementIsNotElementType()
                .Cast<FamilyInstance>());

            return columns;
        }

        // -----------------------------------------------------------------
        // The model around the columns
        // -----------------------------------------------------------------

        private void LoadContext()
        {
            foreach (Element e in new FilteredElementCollector(_doc)
                .OfCategory(BuiltInCategory.OST_StructuralFoundation)
                .WhereElementIsNotElementType())
            {
                BoundingBoxXYZ bb = e.get_BoundingBox(null);
                if (bb == null) continue;
                _foundations.Add(new FoundationRef
                {
                    Element = e,
                    Box = bb,
                    TypeName = TypeNameOf(e)
                });
            }

            foreach (Element e in new FilteredElementCollector(_doc)
                .OfCategory(BuiltInCategory.OST_StructuralFraming)
                .WhereElementIsNotElementType())
            {
                var lc = e.Location as LocationCurve;
                if (lc == null || lc.Curve == null) continue;
                IList<XYZ> pts = lc.Curve.Tessellate();
                if (pts == null || pts.Count < 2) continue;
                _beams.Add(new BeamRef
                {
                    Element = e,
                    Points = pts,
                    ZMin = pts.Min(p => p.Z),
                    ZMax = pts.Max(p => p.Z)
                });
            }

            Level ground = FindGroundLevel();
            _groundElevation = ground != null ? ground.Elevation : 0.0;
            GroundLevelName = ground != null ? ground.Name : "elevation 0";
        }

        private Level FindGroundLevel()
        {
            List<Level> levels = new FilteredElementCollector(_doc)
                .OfClass(typeof(Level)).Cast<Level>().ToList();
            if (levels.Count == 0) return null;

            if (!string.IsNullOrEmpty(_s.GroundLevelName))
            {
                Level named = levels.FirstOrDefault(l =>
                    string.Equals(l.Name, _s.GroundLevelName, StringComparison.OrdinalIgnoreCase));
                if (named != null) return named;
            }
            // Otherwise the level sitting closest to project zero.
            return levels.OrderBy(l => Math.Abs(l.Elevation)).First();
        }

        // -----------------------------------------------------------------
        // One column
        // -----------------------------------------------------------------

        private ColumnInfo Measure(FamilyInstance column)
        {
            BoundingBoxXYZ box = column.get_BoundingBox(null);
            if (box == null) return null;

            var info = new ColumnInfo
            {
                Instance = column,
                Box = box,
                Mark = ParameterText(column, BuiltInParameter.ALL_MODEL_MARK),
                Rotation = RotationOf(column)
            };
            if (string.IsNullOrEmpty(info.Mark))
                info.Mark = column.Id.ToString();

            double baseZ, topZ;
            EndsOf(column, box, out baseZ, out topZ);

            XYZ centre = new XYZ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0, 0);
            var lp = column.Location as LocationPoint;
            if (lp != null) centre = new XYZ(lp.Point.X, lp.Point.Y, 0);

            info.BasePoint = new XYZ(centre.X, centre.Y, baseZ);
            info.TopPoint = new XYZ(centre.X, centre.Y, topZ);

            var sig = new ColumnSignature
            {
                FamilyName = column.Symbol != null && column.Symbol.Family != null
                    ? column.Symbol.Family.Name : "",
                TypeName = column.Symbol != null ? column.Symbol.Name : "",
                BaseElevationMm = Units.ToMm(baseZ),
                TopElevationMm = Units.ToMm(topZ),
                HeightMm = Units.ToMm(topZ - baseZ),
                GroundElevationMm = Units.ToMm(_groundElevation),
                BaseBelowGroundMm = Units.ToMm(_groundElevation - baseZ),
                BaseLevelName = LevelName(column, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM),
                TopLevelName = LevelName(column, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
            };

            MeasureSection(column, info.Rotation, sig);
            FindFoundation(info, sig);
            CountBeams(info, sig);

            sig.Build(_s);
            info.Signature = sig;
            return info;
        }

        private static double RotationOf(FamilyInstance column)
        {
            var lp = column.Location as LocationPoint;
            if (lp != null)
            {
                try { return lp.Rotation; }
                catch { return 0.0; }
            }
            var lc = column.Location as LocationCurve;
            if (lc != null && lc.Curve != null)
            {
                XYZ d = lc.Curve.GetEndPoint(1) - lc.Curve.GetEndPoint(0);
                XYZ flat = new XYZ(d.X, d.Y, 0);
                if (flat.GetLength() > 1e-6) return Math.Atan2(flat.Y, flat.X) + Math.PI / 2.0;
            }
            return 0.0;
        }

        /// <summary>Base and top of the column, from its level parameters where it
        /// has them and from its geometry where it does not (slanted columns).</summary>
        private void EndsOf(FamilyInstance column, BoundingBoxXYZ box, out double baseZ, out double topZ)
        {
            baseZ = box.Min.Z;
            topZ = box.Max.Z;

            double? levelBase = LevelElevation(column, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
                BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
            double? levelTop = LevelElevation(column, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM,
                BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);

            if (levelBase.HasValue) baseZ = levelBase.Value;
            if (levelTop.HasValue) topZ = levelTop.Value;
            if (topZ < baseZ)
            {
                double swap = baseZ; baseZ = topZ; topZ = swap;
            }
        }

        private double? LevelElevation(Element e, BuiltInParameter levelParam, BuiltInParameter offsetParam)
        {
            Parameter p = e.get_Parameter(levelParam);
            if (p == null || p.StorageType != StorageType.ElementId) return null;
            var level = _doc.GetElement(p.AsElementId()) as Level;
            if (level == null) return null;

            double offset = 0.0;
            Parameter o = e.get_Parameter(offsetParam);
            if (o != null && o.StorageType == StorageType.Double) offset = o.AsDouble();
            return level.Elevation + offset;
        }

        private string LevelName(Element e, BuiltInParameter levelParam)
        {
            Parameter p = e.get_Parameter(levelParam);
            if (p == null || p.StorageType != StorageType.ElementId) return "";
            var level = _doc.GetElement(p.AsElementId()) as Level;
            return level != null ? level.Name : "";
        }

        // -----------------------------------------------------------------
        // Size
        // -----------------------------------------------------------------

        private void MeasureSection(FamilyInstance column, double rotation, ColumnSignature sig)
        {
            FamilySymbol symbol = column.Symbol;

            double? diameter = FirstParameter(column, symbol, _s.DiameterParameterNames);
            if (diameter.HasValue && LooksRound(symbol))
            {
                sig.IsRound = true;
                sig.WidthMm = Units.ToMm(diameter.Value);
                sig.DepthMm = sig.WidthMm;
                return;
            }

            double? width = FirstParameter(column, symbol, _s.WidthParameterNames);
            double? depth = FirstParameter(column, symbol, _s.DepthParameterNames);
            if (width.HasValue && depth.HasValue)
            {
                sig.WidthMm = Units.ToMm(width.Value);
                sig.DepthMm = Units.ToMm(depth.Value);
                return;
            }

            // No usable parameters: measure the solid, square-on to the column.
            XYZ right = new XYZ(Math.Cos(rotation), Math.Sin(rotation), 0);
            XYZ into = right.CrossProduct(XYZ.BasisZ);
            double minR = double.MaxValue, maxR = double.MinValue;
            double minI = double.MaxValue, maxI = double.MinValue;
            bool any = false;
            foreach (XYZ p in Vertices(column))
            {
                any = true;
                double r = p.DotProduct(right), i = p.DotProduct(into);
                if (r < minR) minR = r;
                if (r > maxR) maxR = r;
                if (i < minI) minI = i;
                if (i > maxI) maxI = i;
            }
            if (any)
            {
                sig.WidthMm = Units.ToMm(maxR - minR);
                sig.DepthMm = Units.ToMm(maxI - minI);
            }
            else
            {
                BoundingBoxXYZ bb = column.get_BoundingBox(null);
                sig.WidthMm = Units.ToMm(bb.Max.X - bb.Min.X);
                sig.DepthMm = Units.ToMm(bb.Max.Y - bb.Min.Y);
            }
            sig.IsRound = LooksRound(symbol) && Math.Abs(sig.WidthMm - sig.DepthMm) < _s.SizeToleranceMm;
        }

        private static bool LooksRound(FamilySymbol symbol)
        {
            if (symbol == null) return false;
            string name = ((symbol.Family != null ? symbol.Family.Name : "") + " " + symbol.Name).ToUpperInvariant();
            return name.Contains("CIRC") || name.Contains("ROUND") || name.Contains("PIPE")
                || name.Contains("DIAM") || name.Contains("CYLIND");
        }

        private static double? FirstParameter(Element instance, Element type, string[] names)
        {
            foreach (string name in names)
            {
                foreach (Element host in new[] { instance, type })
                {
                    if (host == null) continue;
                    Parameter p = host.LookupParameter(name);
                    if (p != null && p.StorageType == StorageType.Double && p.HasValue)
                    {
                        double v = p.AsDouble();
                        if (v > 1e-9) return v;
                    }
                }
            }
            return null;
        }

        private static IEnumerable<XYZ> Vertices(Element e)
        {
            var options = new Options
            {
                ComputeReferences = false,
                IncludeNonVisibleObjects = false,
                DetailLevel = ViewDetailLevel.Medium
            };
            GeometryElement ge = e.get_Geometry(options);
            if (ge == null) return new List<XYZ>();
            var points = new List<XYZ>();
            Collect(ge, points);
            return points;
        }

        private static void Collect(GeometryElement ge, List<XYZ> points)
        {
            foreach (GeometryObject go in ge)
            {
                var solid = go as Solid;
                if (solid != null && solid.Volume > 1e-9)
                {
                    foreach (Edge edge in solid.Edges)
                        points.AddRange(edge.Tessellate());
                    continue;
                }
                var instance = go as GeometryInstance;
                if (instance != null)
                {
                    GeometryElement inner = instance.GetInstanceGeometry();
                    if (inner != null) Collect(inner, points);
                }
            }
        }

        // -----------------------------------------------------------------
        // Foundation below
        // -----------------------------------------------------------------

        private void FindFoundation(ColumnInfo info, ColumnSignature sig)
        {
            double tol = Units.ToFeet(_s.FoundationSearchToleranceMm);
            double baseZ = info.BasePoint.Z;
            FoundationRef best = null;

            foreach (FoundationRef f in _foundations)
            {
                BoundingBoxXYZ bb = f.Box;
                if (info.BasePoint.X < bb.Min.X - tol || info.BasePoint.X > bb.Max.X + tol) continue;
                if (info.BasePoint.Y < bb.Min.Y - tol || info.BasePoint.Y > bb.Max.Y + tol) continue;
                if (bb.Max.Z > baseZ + tol) continue;          // it is not below the column
                if (best == null || bb.Max.Z > best.Box.Max.Z) best = f;   // the topmost one
            }

            if (best == null) return;
            sig.HasFoundation = true;
            sig.FoundationTypeName = best.TypeName;
            sig.FoundationTopMm = Units.ToMm(best.Box.Max.Z);
            sig.FoundationThicknessMm = Units.ToMm(best.Box.Max.Z - best.Box.Min.Z);
            info.FoundationBox = best.Box;
        }

        // -----------------------------------------------------------------
        // Beams framing in
        // -----------------------------------------------------------------

        private void CountBeams(ColumnInfo info, ColumnSignature sig)
        {
            double half = Units.ToFeet(Math.Max(sig.WidthMm, sig.DepthMm)) / 2.0;
            double planTol = half + Units.ToFeet(_s.BeamSearchToleranceMm);
            double vTol = Units.ToFeet(_s.BeamVerticalToleranceMm);
            double baseZ = info.BasePoint.Z, topZ = info.TopPoint.Z;

            int count = 0;
            bool atTop = false;
            foreach (BeamRef beam in _beams)
            {
                if (beam.ZMax < baseZ - vTol || beam.ZMin > topZ + vTol) continue;
                double distance = PlanDistance(beam.Points, info.BasePoint);
                if (distance > planTol) continue;
                count++;
                if (beam.ZMax > topZ - vTol) atTop = true;
            }
            sig.BeamCount = count;
            sig.BeamAtTop = atTop;
        }

        /// <summary>Shortest distance in plan from a point to a tessellated curve.</summary>
        private static double PlanDistance(IList<XYZ> points, XYZ target)
        {
            double best = double.MaxValue;
            for (int i = 0; i < points.Count - 1; i++)
            {
                double d = SegmentDistance(points[i], points[i + 1], target);
                if (d < best) best = d;
            }
            return best;
        }

        private static double SegmentDistance(XYZ a, XYZ b, XYZ p)
        {
            double ax = a.X, ay = a.Y, bx = b.X, by = b.Y;
            double dx = bx - ax, dy = by - ay;
            double lengthSquared = dx * dx + dy * dy;
            double t = lengthSquared < 1e-12
                ? 0.0
                : ((p.X - ax) * dx + (p.Y - ay) * dy) / lengthSquared;
            if (t < 0) t = 0; else if (t > 1) t = 1;
            double cx = ax + t * dx, cy = ay + t * dy;
            return Math.Sqrt((p.X - cx) * (p.X - cx) + (p.Y - cy) * (p.Y - cy));
        }

        // -----------------------------------------------------------------

        private static string ParameterText(Element e, BuiltInParameter bip)
        {
            Parameter p = e.get_Parameter(bip);
            if (p == null) return "";
            string v = p.AsString();
            return string.IsNullOrEmpty(v) ? "" : v.Trim();
        }

        private string TypeNameOf(Element e)
        {
            var type = _doc.GetElement(e.GetTypeId()) as ElementType;
            return type != null ? type.Name : e.Name;
        }

        private class FoundationRef
        {
            public Element Element;
            public BoundingBoxXYZ Box;
            public string TypeName;
        }

        private class BeamRef
        {
            public Element Element;
            public IList<XYZ> Points;
            public double ZMin;
            public double ZMax;
        }
    }
}
