// Column Sections, as a Revit macro. GENERATED — do not edit.
//
// Made from the add-in sources by tools/build_macro.py; edit those and run it
// again. It is one file so that it can be pasted straight into Revit's own
// macro editor, with no Visual Studio and nothing to install:
//
//   1. Manage > Macros > Macro Manager, and pick the tab with your project's
//      name on it (not Application).
//   2. Module..., name it exactly  ColumnSections , language C#, and OK.
//   3. In the editor that opens, select all of the generated file and paste
//      this file over it. If the compiler complains that AddInId or
//      Transaction is set twice, delete the two attribute lines below.
//   4. Build (F8, or the hammer), then close the editor.
//   5. Macro Manager again: CreateColumnSections cuts the sections,
//      ColumnTypeReport only counts and writes the CSV. Run.
//
// The module name has to be ColumnSections, because that is the namespace the
// class below is declared in.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    [Autodesk.Revit.DB.Macros.AddInId("6c1f4d5e-2c8a-4a2f-9d5e-7b3a1f0c9e42")]
    public partial class ThisDocument
    {
        private void Module_Startup(object sender, EventArgs e)
        {
        }

        private void Module_Shutdown(object sender, EventArgs e)
        {
        }

        /// <summary>One cross section per column type, with the count noted in it.</summary>
        public void CreateColumnSections()
        {
            Run(true);
        }

        /// <summary>Count the types and write the CSV, changing nothing.</summary>
        public void ColumnTypeReport()
        {
            Run(false);
        }

        private void Run(bool createSections)
        {
            Document doc = this.Document;
            if (doc == null)
            {
                TaskDialog.Show("Column sections", "Open a project first.");
                return;
            }

            var uidoc = new UIDocument(doc);
            string problem;
            bool ok = createSections
                ? ColumnSectionsJob.CreateSections(uidoc, out problem)
                : ColumnSectionsJob.Report(uidoc, out problem);
            if (!ok && !string.IsNullOrEmpty(problem))
                TaskDialog.Show("Column sections", problem);
        }
    }


    // Settings.cs
    // --------------

    /// <summary>
    /// Everything the add-in lets you tune, in one place. Edit, rebuild, reload.
    /// Distances are millimetres unless the name says otherwise.
    /// </summary>
    public class Settings
    {
        public static Settings Default = new Settings();

        // ---------------------------------------------------------------
        // What makes two columns "the same"
        // ---------------------------------------------------------------

        /// <summary>Section sizes are rounded to this before they are compared,
        /// so a 399.7 mm wide column and a 400 mm one are one type.</summary>
        public double SizeToleranceMm = 5.0;

        /// <summary>Elevations (foundation top, base, ground offset) are rounded
        /// to this before they are compared.</summary>
        public double LevelToleranceMm = 10.0;

        /// <summary>True: two beams framing in is a different type from three.
        /// False: only connected / not connected matters.</summary>
        public bool CountBeamsSeparately = true;

        /// <summary>True: the column's height (top - base) is part of its identity.</summary>
        public bool HeightIsPartOfType = true;

        /// <summary>True: the family and type name are part of the identity, so two
        /// 400x400 columns from different families stay apart. False: size alone.</summary>
        public bool FamilyNameIsPartOfType = true;

        /// <summary>True: what sits on the same location above and below counts. A
        /// 600x900 with a 400x900 landing on it is not the same type as a 600x900
        /// carrying its own size on up, nor as one with nothing above it.</summary>
        public bool StackChangeIsPartOfType = true;

        // ---------------------------------------------------------------
        // The stack: the columns on the same location, storey over storey
        // ---------------------------------------------------------------

        /// <summary>Two columns are on the same location when their centres are
        /// within this, plus half the smaller one's least plan dimension - so a
        /// column that steps in and is flush on one face is still the same stack.</summary>
        public double StackSearchToleranceMm = 300.0;

        /// <summary>How far apart the top of one column and the base of the next may
        /// be and still be one continuous stack (a slab thickness, say).</summary>
        public double StackVerticalToleranceMm = 600.0;

        /// <summary>How much of the column above, and of the one below, the section
        /// reaches up and down to take in, so the change of size is drawn.</summary>
        public double StackShowAboveMm = 600.0;
        public double StackShowBelowMm = 300.0;

        // ---------------------------------------------------------------
        // Finding the things around a column
        // ---------------------------------------------------------------

        /// <summary>A foundation counts as "below this column" when the column's
        /// centre falls inside its footprint grown by this much.</summary>
        public double FoundationSearchToleranceMm = 250.0;

        /// <summary>A beam counts as framing into this column when its centre line
        /// passes within this distance of the column face, in plan.</summary>
        public double BeamSearchToleranceMm = 200.0;

        /// <summary>How far above the column top a beam centre line may sit and
        /// still count as landing on it (roughly half a beam depth, plus slack).</summary>
        public double BeamVerticalToleranceMm = 900.0;

        /// <summary>Name of the level to read "ground" from. Empty: the level whose
        /// elevation is closest to zero is used.</summary>
        public string GroundLevelName = "";

        /// <summary>Parameter names searched, in order, for the column's section
        /// size. If none is found the size is measured off the geometry.</summary>
        public string[] WidthParameterNames = { "b", "Width", "Depth 1", "bf" };
        public string[] DepthParameterNames = { "h", "Depth", "Height", "d" };
        public string[] DiameterParameterNames = { "Diameter", "D", "d" };

        // ---------------------------------------------------------------
        // The sections that get drawn
        // ---------------------------------------------------------------

        public int ViewScale = 50;

        /// <summary>Crop left and right of the column, and above and below it.</summary>
        public double SideClearanceMm = 1000.0;
        public double TopClearanceMm = 600.0;
        public double BottomClearanceMm = 300.0;

        /// <summary>How far past the column's own faces the view looks. This alone
        /// sets the far clip - nothing else may push it out, so a raft under the
        /// column cannot turn the section into a view of the whole building.</summary>
        public double ViewDepthClearanceMm = 500.0;

        /// <summary>How far past the column's faces a footing may widen the view,
        /// before the side clearance is added on top. Zero keeps the crop at the
        /// column plus the clearance either side; a footing wider than the column
        /// still shows, as far out as that band reaches.</summary>
        public double MaxExtraWidthMm = 0.0;

        /// <summary>Hide everything in the section but this column, its foundation,
        /// the beams framing into it, the lift above and below, the datums, and the
        /// categories below.</summary>
        public bool ShowOnlyThisColumn = true;

        /// <summary>Kept visible even so - the floors the column carries, first of
        /// all. The view sees only 150 mm past the column, so what shows of them is
        /// the slice at the column. Add OST_Walls, OST_Roofs, OST_StructuralFraming
        /// or anything else you want left in.</summary>
        public BuiltInCategory[] AlwaysVisibleCategories =
        {
            BuiltInCategory.OST_Floors,
            BuiltInCategory.OST_StructuralFoundation
        };

        /// <summary>The note sits above the crop, so a long line cannot force the
        /// view wide. True puts it inside the crop instead.</summary>
        public bool ExpandCropForNote = false;

        /// <summary>Prefix of the created view names, e.g. "COL SECTION - CT-01".</summary>
        public string ViewNamePrefix = "COL SECTION";

        /// <summary>Type codes are numbered CT-01, CT-02, ...</summary>
        public string TypeCodePrefix = "CT";

        /// <summary>Write the type code into each column's Comments parameter, so the
        /// plan can be tagged with it. Off by default: it edits your model data.</summary>
        public bool StampTypeCodeInComments = false;

        /// <summary>List the marks of the columns of the type in the section's note,
        /// up to this many. Zero: never list them.</summary>
        public int MaxMarksInNote = 12;
    }


    // Units.cs
    // -----------

    /// <summary>Revit works in decimal feet internally; this file is the only
    /// place that has to remember it.</summary>
    public static class Units
    {
        public static double ToMm(double internalFeet)
        {
            return UnitUtils.ConvertFromInternalUnits(internalFeet, UnitTypeId.Millimeters);
        }

        public static double ToFeet(double millimetres)
        {
            return UnitUtils.ConvertToInternalUnits(millimetres, UnitTypeId.Millimeters);
        }

        /// <summary>Rounds to a step, so near-identical values compare equal.</summary>
        public static double Snap(double valueMm, double stepMm)
        {
            if (stepMm <= 0) return valueMm;
            return System.Math.Round(valueMm / stepMm, System.MidpointRounding.AwayFromZero) * stepMm;
        }
    }


    // ColumnSignature.cs
    // ---------------------

    /// <summary>
    /// What the job called "a different column": its size, the foundation under it,
    /// whether a beam frames into it, and where it sits against ground level.
    /// Two columns with the same <see cref="Key"/> are one type.
    /// </summary>
    public sealed class ColumnSignature
    {
        // Size
        public string FamilyName = "";
        public string TypeName = "";
        public double WidthMm;
        public double DepthMm;
        public bool IsRound;
        public double HeightMm;

        // Foundation below
        public bool HasFoundation;
        public string FoundationTypeName = "";
        public double FoundationTopMm;
        public double FoundationThicknessMm;

        // Beam connection
        public int BeamCount;
        public bool BeamAtTop;

        // The stack: what sits on the same location above and below
        public bool HasColumnAbove;
        public bool HasColumnBelow;
        public string SizeAboveText = "";
        public string SizeBelowText = "";
        public bool SizeChangesAbove;
        public bool SizeChangesBelow;

        // Levels
        public string BaseLevelName = "";
        public string TopLevelName = "";
        public double BaseElevationMm;
        public double TopElevationMm;
        public double GroundElevationMm;
        /// <summary>Positive when the column starts below ground level.</summary>
        public double BaseBelowGroundMm;

        public string Key { get; private set; }

        /// <summary>Freezes the signature: rounds every measurement to the
        /// tolerances in <paramref name="s"/> and builds the comparison key.</summary>
        public void Build(Settings s)
        {
            WidthMm = Units.Snap(WidthMm, s.SizeToleranceMm);
            DepthMm = Units.Snap(DepthMm, s.SizeToleranceMm);
            HeightMm = Units.Snap(HeightMm, s.LevelToleranceMm);
            FoundationTopMm = Units.Snap(FoundationTopMm, s.LevelToleranceMm);
            FoundationThicknessMm = Units.Snap(FoundationThicknessMm, s.LevelToleranceMm);
            BaseElevationMm = Units.Snap(BaseElevationMm, s.LevelToleranceMm);
            TopElevationMm = Units.Snap(TopElevationMm, s.LevelToleranceMm);
            GroundElevationMm = Units.Snap(GroundElevationMm, s.LevelToleranceMm);
            BaseBelowGroundMm = Units.Snap(BaseBelowGroundMm, s.LevelToleranceMm);

            var k = new StringBuilder();
            var c = CultureInfo.InvariantCulture;

            if (s.FamilyNameIsPartOfType)
                k.Append(FamilyName).Append('|').Append(TypeName).Append('|');

            k.Append(SizeText).Append('|');
            if (s.HeightIsPartOfType)
                k.Append("H").Append(HeightMm.ToString("0", c)).Append('|');

            k.Append(HasFoundation
                ? string.Format(c, "F:{0}:{1:0}:{2:0}", FoundationTypeName, FoundationTopMm, FoundationThicknessMm)
                : "F:none");
            k.Append('|');

            k.Append(s.CountBeamsSeparately
                ? string.Format(c, "B:{0}:{1}", BeamCount, BeamAtTop ? 1 : 0)
                : string.Format(c, "B:{0}", BeamCount > 0 ? 1 : 0));
            k.Append('|');

            k.Append(string.Format(c, "G:{0:0}", BaseBelowGroundMm));

            if (s.StackChangeIsPartOfType)
            {
                k.Append('|');
                k.Append("A:").Append(HasColumnAbove ? SizeAboveText : "none").Append('|');
                k.Append("U:").Append(HasColumnBelow ? SizeBelowText : "none");
            }

            Key = k.ToString();
        }

        public string SizeText
        {
            get
            {
                var c = CultureInfo.InvariantCulture;
                if (IsRound)
                    return string.Format(c, "D{0:0}", WidthMm);
                return string.Format(c, "{0:0} x {1:0}", WidthMm, DepthMm);
            }
        }

        public string FoundationText
        {
            get
            {
                if (!HasFoundation) return "NO FOUNDATION FOUND";
                var c = CultureInfo.InvariantCulture;
                return string.Format(c, "FDN TOP {0:+0;-0;0} ({1:0} THK)",
                    FoundationTopMm, FoundationThicknessMm);
            }
        }

        public string BeamText
        {
            get
            {
                if (BeamCount == 0) return "NO BEAM CONNECTED";
                var c = CultureInfo.InvariantCulture;
                return string.Format(c, "{0} BEAM{1} CONNECTED{2}",
                    BeamCount, BeamCount == 1 ? "" : "S", BeamAtTop ? " (AT TOP)" : "");
            }
        }

        public string GroundText
        {
            get
            {
                var c = CultureInfo.InvariantCulture;
                if (Math.Abs(BaseBelowGroundMm) < 1.0) return "BASE AT GROUND LEVEL";
                return BaseBelowGroundMm > 0
                    ? string.Format(c, "BASE {0:0} BELOW GROUND", BaseBelowGroundMm)
                    : string.Format(c, "BASE {0:0} ABOVE GROUND", -BaseBelowGroundMm);
            }
        }

        /// <summary>Where this column sits in its stack: bottom lift, a middle one,
        /// the top, or on its own.</summary>
        public string StackPosition
        {
            get
            {
                if (!HasColumnAbove && !HasColumnBelow) return "SINGLE LIFT";
                if (!HasColumnBelow) return "BOTTOM OF STACK";
                if (!HasColumnAbove) return "TOP OF STACK";
                return "MIDDLE OF STACK";
            }
        }

        public string AboveText
        {
            get
            {
                if (!HasColumnAbove) return "NOTHING ABOVE (TOP OF STACK)";
                return SizeChangesAbove
                    ? "ABOVE: " + SizeAboveText + " - SIZE CHANGES"
                    : "ABOVE: " + SizeAboveText + " - SAME SIZE";
            }
        }

        public string BelowText
        {
            get
            {
                if (!HasColumnBelow) return "NOTHING BELOW (COLUMN STARTS HERE)";
                return SizeChangesBelow
                    ? "BELOW: " + SizeBelowText + " - SIZE CHANGES"
                    : "BELOW: " + SizeBelowText + " - SAME SIZE";
            }
        }

        /// <summary>One line for a schedule or a dialog: 600 x 900 > 400 x 900.</summary>
        public string StackText
        {
            get
            {
                string below = HasColumnBelow ? SizeBelowText : "-";
                string above = HasColumnAbove ? SizeAboveText : "-";
                return below + " > " + SizeText + " > " + above;
            }
        }

        /// <summary>The five criteria, one per line, for the note in the section.</summary>
        public string[] DescriptionLines()
        {
            var c = CultureInfo.InvariantCulture;
            return new[]
            {
                "SIZE: " + SizeText + "  (" + TypeName + ")",
                FoundationText,
                BeamText,
                GroundText,
                BelowText,
                AboveText,
                string.Format(c, "BASE {0:0} / TOP {1:0} / HT {2:0}",
                    BaseElevationMm, TopElevationMm, HeightMm)
            };
        }
    }


    // ColumnInfo.cs
    // ----------------

    /// <summary>One column, measured.</summary>
    public sealed class ColumnInfo
    {
        public FamilyInstance Instance;
        public string Mark = "";
        /// <summary>Centre of the column at its base, in model coordinates.</summary>
        public XYZ BasePoint;
        public XYZ TopPoint;
        /// <summary>Rotation of the column about Z, radians. The section looks
        /// square-on to the face this angle describes.</summary>
        public double Rotation;
        public BoundingBoxXYZ Box;
        public BoundingBoxXYZ FoundationBox;
        /// <summary>The foundation under it, and the beams framing into it: what the
        /// section keeps when everything else is hidden.</summary>
        public ElementId FoundationId;
        public readonly List<ElementId> BeamIds = new List<ElementId>();
        /// <summary>The columns sharing this plan location, one storey up and one down.</summary>
        public ColumnInfo Above;
        public ColumnInfo Below;
        public ColumnSignature Signature;

        /// <summary>The least of the two plan dimensions, in feet. Used to decide how
        /// far a column above may step in and still be the same stack.</summary>
        public double LeastPlanDimension
        {
            get
            {
                double least = System.Math.Min(Signature.WidthMm, Signature.DepthMm);
                return Units.ToFeet(least);
            }
        }
    }

    /// <summary>All the columns that came out identical, and the section drawn for them.</summary>
    public sealed class ColumnTypeGroup
    {
        public string Code = "";
        public ColumnSignature Signature;
        public readonly List<ColumnInfo> Members = new List<ColumnInfo>();
        public ElementId ViewId = ElementId.InvalidElementId;
        public string ViewName = "";

        public int Count { get { return Members.Count; } }

        /// <summary>The column the section is cut through: the first one, by mark.</summary>
        public ColumnInfo Representative { get { return Members[0]; } }
    }


    // ColumnScanner.cs
    // -------------------

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

            // Measured first, all of them: a column's type depends on what sits on
            // its own location above and below, which is only known once the rest
            // have been measured too.
            var measured = new List<ColumnInfo>();
            foreach (FamilyInstance column in columns)
            {
                ColumnInfo info = Measure(column);
                if (info != null) measured.Add(info);
            }
            LinkStacks(measured);

            var byKey = new Dictionary<string, ColumnTypeGroup>();
            foreach (ColumnInfo info in measured)
            {
                info.Signature.Build(_s);

                ColumnTypeGroup group;
                if (!byKey.TryGetValue(info.Signature.Key, out group))
                {
                    group = new ColumnTypeGroup { Signature = info.Signature };
                    byKey.Add(info.Signature.Key, group);
                }
                group.Members.Add(info);
            }

            // Most common type first, so CT-01 is the one that repeats most.
            var groups = new List<ColumnTypeGroup>(byKey.Values);
            groups.Sort(delegate(ColumnTypeGroup a, ColumnTypeGroup b)
            {
                if (a.Count != b.Count) return b.Count.CompareTo(a.Count);
                int bySize = string.Compare(a.Signature.SizeText, b.Signature.SizeText,
                    StringComparison.OrdinalIgnoreCase);
                if (bySize != 0) return bySize;
                return string.Compare(a.Signature.Key, b.Signature.Key, StringComparison.Ordinal);
            });

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
            // Architectural columns count too, if that is all the model has.
            var categories = new[] { BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Columns };
            var columns = new List<FamilyInstance>();
            foreach (BuiltInCategory category in categories)
            {
                foreach (Element e in new FilteredElementCollector(doc)
                    .OfCategory(category)
                    .OfClass(typeof(FamilyInstance))
                    .WhereElementIsNotElementType())
                {
                    var instance = e as FamilyInstance;
                    if (instance != null) columns.Add(instance);
                }
            }
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
                double zMin = pts[0].Z, zMax = pts[0].Z;
                foreach (XYZ p in pts)
                {
                    if (p.Z < zMin) zMin = p.Z;
                    if (p.Z > zMax) zMax = p.Z;
                }
                _beams.Add(new BeamRef { Element = e, Points = pts, ZMin = zMin, ZMax = zMax });
            }

            Level ground = FindGroundLevel();
            _groundElevation = ground != null ? ground.Elevation : 0.0;
            GroundLevelName = ground != null ? ground.Name : "elevation 0";
        }

        private Level FindGroundLevel()
        {
            var levels = new List<Level>();
            foreach (Element e in new FilteredElementCollector(_doc).OfClass(typeof(Level)))
            {
                var level = e as Level;
                if (level != null) levels.Add(level);
            }
            if (levels.Count == 0) return null;

            if (!string.IsNullOrEmpty(_s.GroundLevelName))
            {
                foreach (Level level in levels)
                {
                    if (string.Equals(level.Name, _s.GroundLevelName, StringComparison.OrdinalIgnoreCase))
                        return level;
                }
            }

            // Otherwise the level sitting closest to project zero.
            Level nearest = levels[0];
            foreach (Level level in levels)
            {
                if (Math.Abs(level.Elevation) < Math.Abs(nearest.Elevation)) nearest = level;
            }
            return nearest;
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
            // Rounded now, not only in Build: the sizes are compared up the stack
            // before the signature is closed.
            sig.WidthMm = Units.Snap(sig.WidthMm, _s.SizeToleranceMm);
            sig.DepthMm = Units.Snap(sig.DepthMm, _s.SizeToleranceMm);

            FindFoundation(info, sig);
            CountBeams(info, sig);

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
        // The stack: same location, storey over storey
        // -----------------------------------------------------------------

        /// <summary>Finds, for each column, the column on the same plan location one
        /// lift up and one lift down, and records whether the size changes there.
        /// A 600x900 carrying a 400x900 is a different case from one that carries
        /// its own size on up, and from one with nothing above it at all.</summary>
        private void LinkStacks(List<ColumnInfo> columns)
        {
            // Bucketed by a coarse plan grid, so this stays quick on a whole tower.
            double cell = Units.ToFeet(3000.0);
            var grid = new Dictionary<long, List<ColumnInfo>>();
            foreach (ColumnInfo c in columns)
            {
                long key = CellKey((int)Math.Floor(c.BasePoint.X / cell),
                                   (int)Math.Floor(c.BasePoint.Y / cell));
                List<ColumnInfo> bucket;
                if (!grid.TryGetValue(key, out bucket))
                {
                    bucket = new List<ColumnInfo>();
                    grid.Add(key, bucket);
                }
                bucket.Add(c);
            }

            double slack = Units.ToFeet(_s.StackSearchToleranceMm);
            double vTol = Units.ToFeet(_s.StackVerticalToleranceMm);

            foreach (ColumnInfo column in columns)
            {
                int ix = (int)Math.Floor(column.BasePoint.X / cell);
                int iy = (int)Math.Floor(column.BasePoint.Y / cell);

                ColumnInfo above = null, below = null;
                for (int dx = -1; dx <= 1; dx++)
                {
                    for (int dy = -1; dy <= 1; dy++)
                    {
                        List<ColumnInfo> bucket;
                        if (!grid.TryGetValue(CellKey(ix + dx, iy + dy), out bucket)) continue;

                        foreach (ColumnInfo other in bucket)
                        {
                            if (ReferenceEquals(other, column)) continue;

                            double reach = slack + Math.Min(column.LeastPlanDimension,
                                                            other.LeastPlanDimension) / 2.0;
                            double dxx = other.BasePoint.X - column.BasePoint.X;
                            double dyy = other.BasePoint.Y - column.BasePoint.Y;
                            if (Math.Sqrt(dxx * dxx + dyy * dyy) > reach) continue;

                            bool sitsAbove = other.BasePoint.Z >= column.TopPoint.Z - vTol
                                             && other.TopPoint.Z > column.TopPoint.Z + 1e-6;
                            if (sitsAbove && (above == null || other.BasePoint.Z < above.BasePoint.Z))
                                above = other;

                            bool sitsBelow = other.TopPoint.Z <= column.BasePoint.Z + vTol
                                             && other.BasePoint.Z < column.BasePoint.Z - 1e-6;
                            if (sitsBelow && (below == null || other.TopPoint.Z > below.TopPoint.Z))
                                below = other;
                        }
                    }
                }

                column.Above = above;
                column.Below = below;
                ColumnSignature sig = column.Signature;

                sig.HasColumnAbove = above != null;
                if (above != null)
                {
                    sig.SizeAboveText = above.Signature.SizeText;
                    sig.SizeChangesAbove = !string.Equals(sig.SizeAboveText, sig.SizeText,
                        StringComparison.OrdinalIgnoreCase);
                }

                sig.HasColumnBelow = below != null;
                if (below != null)
                {
                    sig.SizeBelowText = below.Signature.SizeText;
                    sig.SizeChangesBelow = !string.Equals(sig.SizeBelowText, sig.SizeText,
                        StringComparison.OrdinalIgnoreCase);
                }
            }
        }

        private static long CellKey(int x, int y)
        {
            return ((long)x << 32) ^ (uint)y;
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
            info.FoundationId = best.Element.Id;
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
                info.BeamIds.Add(beam.Element.Id);
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


    // SectionFactory.cs
    // --------------------

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

        /// <summary>Hides everything in the view but this column and what belongs to
        /// it, so the section is of the column rather than of the building.</summary>
        private void ShowOnly(View view, ColumnInfo column)
        {
            try
            {
                var keep = new List<ElementId> { column.Instance.Id };
                if (column.FoundationId != null && column.FoundationId != ElementId.InvalidElementId)
                    keep.Add(column.FoundationId);
                keep.AddRange(column.BeamIds);
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
            lines.AddRange(group.Signature.DescriptionLines());

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

        /// <summary>The column and nothing else: what the view is sized from.</summary>
        private static IEnumerable<XYZ> ColumnPoints(ColumnInfo column)
        {
            foreach (XYZ p in Corners(column.Box)) yield return p;
            yield return column.BasePoint;
            yield return column.TopPoint;
        }

        /// <summary>The foundation under it and the first stretch of the lifts above
        /// and below, so the section frames the footing and any change of size at
        /// either end - within the limits the caller puts on them.</summary>
        private static IEnumerable<XYZ> NeighbourPoints(ColumnInfo column, Settings s)
        {
            if (column.FoundationBox != null)
                foreach (XYZ p in Corners(column.FoundationBox)) yield return p;

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


    // ColumnSectionsJob.cs
    // -----------------------

    /// <summary>
    /// The work itself, with nothing add-in specific about it: the ribbon commands
    /// and the macro version both call straight into this.
    /// </summary>
    public static class ColumnSectionsJob
    {
        /// <summary>Sorts the columns into types and cuts one cross section for each,
        /// with a note in it saying how many columns share the type.</summary>
        public static bool CreateSections(UIDocument uidoc, out string problem)
        {
            problem = null;
            Document doc = uidoc.Document;
            if (doc.IsFamilyDocument)
            {
                problem = "Run this in a project, not in the family editor.";
                return false;
            }

            Settings settings = Settings.Default;

            List<FamilyInstance> columns = Selected(uidoc);
            bool fromSelection = columns.Count > 0;
            if (!fromSelection) columns = ColumnScanner.AllColumns(doc);
            if (columns.Count == 0)
            {
                TaskDialog.Show("Column sections", "No columns found in this model.");
                return true;
            }

            var scanner = new ColumnScanner(doc, settings);
            List<ColumnTypeGroup> groups = scanner.Scan(columns);
            if (groups.Count == 0)
            {
                TaskDialog.Show("Column sections", "None of the columns could be measured.");
                return true;
            }

            var factory = new SectionFactory(doc, settings);
            if (!factory.Prepare(out problem)) return false;

            var ask = new TaskDialog("Column sections")
            {
                MainInstruction = string.Format("{0} column{1} in {2} type{3}.",
                    columns.Count, columns.Count == 1 ? "" : "s",
                    groups.Count, groups.Count == 1 ? "" : "s"),
                MainContent = string.Format(
                    "Read from {0}. Ground is taken from level \"{1}\".\n\n" +
                    "A type is a size, a foundation below, a beam connection, a level " +
                    "against ground, and what the stack does above and below it. One " +
                    "cross section will be created for each, with a note in it saying " +
                    "how many columns share that type.",
                    fromSelection ? "your selection" : "the whole model",
                    scanner.GroundLevelName),
                ExpandedContent = Summary(groups),
                CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
                DefaultButton = TaskDialogResult.Yes
            };
            if (ask.Show() != TaskDialogResult.Yes) return true;

            var failed = new List<string>();
            using (var t = new Transaction(doc, "Column type cross sections"))
            {
                t.Start();
                foreach (ColumnTypeGroup group in groups)
                {
                    try
                    {
                        factory.Create(group);
                        if (settings.StampTypeCodeInComments) Stamp(group);
                    }
                    catch (Exception ex)
                    {
                        failed.Add(group.Code + ": " + ex.Message);
                    }
                }
                t.Commit();
            }

            int made = groups.Count - failed.Count;
            var done = new TaskDialog("Column sections")
            {
                MainInstruction = string.Format("{0} section{1} created.", made, made == 1 ? "" : "s"),
                MainContent = failed.Count == 0
                    ? "They are in the project browser under Sections."
                    : string.Format("{0} could not be created:\n{1}",
                        failed.Count, string.Join("\n", failed.ToArray())),
                ExpandedContent = Summary(groups)
            };
            done.Show();
            return true;
        }

        /// <summary>The same grouping, reported and written to CSV, without touching
        /// the model.</summary>
        public static bool Report(UIDocument uidoc, out string problem)
        {
            problem = null;
            Document doc = uidoc.Document;
            if (doc.IsFamilyDocument)
            {
                problem = "Run this in a project, not in the family editor.";
                return false;
            }

            List<FamilyInstance> columns = ColumnScanner.AllColumns(doc);
            if (columns.Count == 0)
            {
                TaskDialog.Show("Column types", "No columns found in this model.");
                return true;
            }

            var scanner = new ColumnScanner(doc, Settings.Default);
            List<ColumnTypeGroup> groups = scanner.Scan(columns);

            string path;
            try { path = WriteCsv(doc, groups); }
            catch (Exception ex) { path = "could not be written: " + ex.Message; }

            var dialog = new TaskDialog("Column types")
            {
                MainInstruction = string.Format("{0} columns in {1} types.",
                    columns.Count, groups.Count),
                MainContent = string.Format("Ground is taken from level \"{0}\".\n\nCSV: {1}",
                    scanner.GroundLevelName, path),
                ExpandedContent = Summary(groups)
            };
            dialog.Show();
            return true;
        }

        // -----------------------------------------------------------------

        /// <summary>The columns in the current selection, if any are selected.</summary>
        private static List<FamilyInstance> Selected(UIDocument uidoc)
        {
            Document doc = uidoc.Document;
            var wanted = new List<ElementId>();
            var categories = new[] { BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Columns };
            foreach (BuiltInCategory bic in categories)
            {
                Category category = Category.GetCategory(doc, bic);
                if (category != null) wanted.Add(category.Id);
            }

            var columns = new List<FamilyInstance>();
            foreach (ElementId id in uidoc.Selection.GetElementIds())
            {
                var instance = doc.GetElement(id) as FamilyInstance;
                if (instance == null || instance.Category == null) continue;
                foreach (ElementId w in wanted)
                {
                    if (w == instance.Category.Id)
                    {
                        columns.Add(instance);
                        break;
                    }
                }
            }
            return columns;
        }

        /// <summary>Writes the type code into each column's Comments, for tagging.</summary>
        private static void Stamp(ColumnTypeGroup group)
        {
            foreach (ColumnInfo member in group.Members)
            {
                Parameter p = member.Instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                if (p != null && !p.IsReadOnly) p.Set(group.Code);
            }
        }

        /// <summary>One line per type, for the dialogs.</summary>
        public static string Summary(List<ColumnTypeGroup> groups)
        {
            var text = new StringBuilder();
            foreach (ColumnTypeGroup g in groups)
            {
                text.AppendFormat("{0}  x{1}  {2}  |  {3}  |  {4}  |  {5}  |  STACK {6}\n",
                    g.Code, g.Count, g.Signature.SizeText, g.Signature.FoundationText,
                    g.Signature.BeamText, g.Signature.GroundText, g.Signature.StackText);
            }
            return text.ToString();
        }

        private static string WriteCsv(Document doc, List<ColumnTypeGroup> groups)
        {
            string name = string.IsNullOrEmpty(doc.Title) ? "model" : doc.Title;
            string path = Path.Combine(Path.GetTempPath(),
                string.Format("{0}-column-types-{1:yyyyMMdd-HHmmss}.csv", name, DateTime.Now));

            var c = CultureInfo.InvariantCulture;
            var text = new StringBuilder();
            text.AppendLine("Type,Count,Family,Type name,Size,Height mm,Foundation,Foundation top mm," +
                            "Foundation thickness mm,Beams,Beam at top,Base level,Base mm,Top mm," +
                            "Base below ground mm,Size below,Size above,Size changes,Stack position,Marks");
            foreach (ColumnTypeGroup g in groups)
            {
                ColumnSignature s = g.Signature;
                var marks = new List<string>();
                foreach (ColumnInfo m in g.Members) marks.Add(m.Mark);
                text.AppendFormat(c,
                    "{0},{1},{2},{3},{4},{5:0},{6},{7:0},{8:0},{9},{10},{11},{12:0},{13:0},{14:0}," +
                    "{15},{16},{17},{18},{19}\n",
                    Csv(g.Code), g.Count, Csv(s.FamilyName), Csv(s.TypeName), Csv(s.SizeText),
                    s.HeightMm, s.HasFoundation ? Csv(s.FoundationTypeName) : "none",
                    s.FoundationTopMm, s.FoundationThicknessMm, s.BeamCount, s.BeamAtTop ? "yes" : "no",
                    Csv(s.BaseLevelName), s.BaseElevationMm, s.TopElevationMm, s.BaseBelowGroundMm,
                    s.HasColumnBelow ? Csv(s.SizeBelowText) : "none",
                    s.HasColumnAbove ? Csv(s.SizeAboveText) : "none",
                    s.SizeChangesBelow || s.SizeChangesAbove ? "yes" : "no",
                    Csv(s.StackPosition),
                    Csv(string.Join(" ", marks.ToArray())));
            }
            File.WriteAllText(path, text.ToString(), Encoding.UTF8);
            return path;
        }

        private static string Csv(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.IndexOfAny(new[] { ',', '"', '\n' }) >= 0
                ? "\"" + value.Replace("\"", "\"\"") + "\""
                : value;
        }
    }

}
