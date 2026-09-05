// ===========================================================================
//  COLUMN SECTIONS - for a paste-in code runner (DevKit and the like)
//  Revit 2021 and later. Tested shape: the tool wraps this inside a method.
// ---------------------------------------------------------------------------
//  One cross section per column TYPE, with a note in it saying how many
//  columns share that type. Two columns are the same type when all of these
//  agree: their size, the foundation under them, whether a beam frames in,
//  how far the base sits below ground, and what sits on the same location
//  above and below (600x900 carrying a 400x900 is not 600x900 carrying
//  600x900, nor one with nothing above).
// ---------------------------------------------------------------------------
//  THIS FILE IS STATEMENTS ONLY - no using lines, no namespace, no class - so
//  it can be pasted into a box that wraps your code in a method. Every type is
//  written out in full for the same reason: it does not care what the tool has
//  already imported.
//
//  Written for DevKit, which hands the code a Document called doc. In another
//  tool change the one line under "How this gets hold of the model".
// ===========================================================================

// How this gets hold of the model. DevKit hands the code a Document called doc,
// which is all it needs:
Autodesk.Revit.DB.Document theDoc = doc;
//
// In another tool the name will be its own. If the compiler says doc does not
// exist, use whatever that tool calls the model - one of these usually:
// Autodesk.Revit.DB.Document theDoc = uidoc.Document;
// Autodesk.Revit.DB.Document theDoc = uiapp.ActiveUIDocument.Document;
// Autodesk.Revit.DB.Document theDoc = app.ActiveUIDocument.Document;
// Autodesk.Revit.DB.Document theDoc = commandData.Application.ActiveUIDocument.Document;

// --------------------------------------------------------------- settings --
// Rounded before anything is compared, so a millimetre out is not a new type.
double sizeToleranceMm = 5.0;
double levelToleranceMm = 10.0;

// What counts as a different type.
bool familyNameIsPartOfType = true;   // false: size alone, whatever the family
bool heightIsPartOfType = true;       // false: storey height stops mattering
bool countBeamsSeparately = true;     // false: only connected / not connected
bool stackChangeIsPartOfType = true;  // false: what is above and below stops counting

// How far out something still belongs to this column.
double foundationSearchToleranceMm = 250.0;
double beamSearchToleranceMm = 200.0;    // past the column face, in plan
double beamVerticalToleranceMm = 900.0;  // above the top, for a beam sitting on it
double stackSearchToleranceMm = 300.0;   // plus half the smaller column's least side
double stackVerticalToleranceMm = 600.0; // a slab thickness between two lifts

// The level ground is read from. Empty: the level nearest project zero.
string groundLevelName = "";

// The sections that get drawn. Kept tight to the column: raise these if you
// want more of the frame around it in the view.
int viewScale = 50;
double sideClearanceMm = 1000.0;      // crop, left and right of the column
double topClearanceMm = 600.0;
double bottomClearanceMm = 600.0;

// Seen below the base of the column even where no foundation was found, so the
// footing is in the view whatever it was modelled as.
double alwaysShowBelowBaseMm = 1000.0;

// How far past the column's own faces the view looks. This alone sets the far
// clip: nothing else is allowed to push it out, so a raft under the column
// cannot turn the section into a view of the whole building.
double viewDepthClearanceMm = 500.0;

// How far past the column's faces a footing may widen the view, before the side
// clearance is added on top. A pad footing shows; a raft is cut off here, so it
// cannot make the view the size of the building.
double maxExtraWidthMm = 1000.0;

// One section per column STACK, not per column: the section is taken on the
// column that starts at the foundation and covers everything standing on it, so
// a 600x900 with a 400x900 over it is one section counted once, not two. The
// count in the note is then a count of columns on the ground, which is what a
// schedule of column sections is counting.
bool oneSectionPerStack = true;
int maxLiftsInNote = 12;
double showAboveMm = 600.0;   // how much of the next lift up the section takes in
double showBelowMm = 300.0;

// Hide everything in the section except this column, its foundation, the beams
// framing into it, the lift above and below, the levels and grids, and the
// categories listed below.
bool showOnlyThisColumn = true;

// Kept visible even so - the floors the column carries, first of all. The view
// only sees 150mm past the column, so what shows of them is the slice at the
// column and nothing else. Add a line for anything else you want left in:
// OST_Walls, OST_Roofs, OST_StructuralFraming, OST_Stairs...
Autodesk.Revit.DB.BuiltInCategory[] alwaysVisibleCategories =
    new Autodesk.Revit.DB.BuiltInCategory[]
{
    Autodesk.Revit.DB.BuiltInCategory.OST_Floors,
    Autodesk.Revit.DB.BuiltInCategory.OST_StructuralFoundation
};

// The note sits above the crop, so it does not force the view wide. True puts
// it inside the crop instead, which makes the view as wide as the longest line.
bool expandCropForNote = false;
string viewNamePrefix = "COL SECTION";
string typeCodePrefix = "CT";
int maxMarksInNote = 12;

bool stampTypeCodeInComments = false;  // writes the code into each column's Comments
bool writeCsvToTemp = true;

// Section size parameters looked for, in order, before the solid is measured.
string[] widthParameterNames = new string[] { "b", "Width", "Depth 1", "bf" };
string[] depthParameterNames = new string[] { "h", "Depth", "Height", "d" };
string[] diameterParameterNames = new string[] { "Diameter", "D", "d" };

// ===========================================================================

var inv = System.Globalization.CultureInfo.InvariantCulture;
var theUiDoc = new Autodesk.Revit.UI.UIDocument(theDoc);

System.Func<double, double> toMm = feet =>
    Autodesk.Revit.DB.UnitUtils.ConvertFromInternalUnits(
        feet, Autodesk.Revit.DB.UnitTypeId.Millimeters);
System.Func<double, double> toFeet = mm =>
    Autodesk.Revit.DB.UnitUtils.ConvertToInternalUnits(
        mm, Autodesk.Revit.DB.UnitTypeId.Millimeters);
System.Func<double, double, double> snap = (value, step) =>
    step <= 0 ? value : System.Math.Round(value / step, System.MidpointRounding.AwayFromZero) * step;

// Slots in the number row kept for each column. Feet where the name says so,
// millimetres everywhere else; 1 and 0 stand in for yes and no.
const int N_BASE_Z_FT = 0;
const int N_TOP_Z_FT = 1;
const int N_ROTATION = 2;
const int N_WIDTH = 3;
const int N_DEPTH = 4;
const int N_IS_ROUND = 5;
const int N_HEIGHT = 6;
const int N_BASE = 7;
const int N_TOP = 8;
const int N_BELOW_GROUND = 9;
const int N_HAS_FOUNDATION = 10;
const int N_FOUNDATION_TOP = 11;
const int N_FOUNDATION_THICKNESS = 12;
const int N_BEAMS = 13;
const int N_BEAM_AT_TOP = 14;
const int NUMBER_SLOTS = 15;

// Slots in the text row. An empty string means there is none.
const int T_FAMILY = 0;
const int T_TYPE = 1;
const int T_FOUNDATION = 2;
const int T_MARK = 3;
const int T_BASE_LEVEL = 4;
const int T_SIZE_ABOVE = 5;
const int T_SIZE_BELOW = 6;
const int TEXT_SLOTS = 7;

var ids = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
var instanceOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.FamilyInstance>();
var numberOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, double[]>();
var textOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, string[]>();
var boxOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.BoundingBoxXYZ>();
var foundationBoxOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.BoundingBoxXYZ>();
var basePointOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.XYZ>();
var topPointOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.XYZ>();
var aboveOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.ElementId>();
var belowOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.ElementId>();
var foundationIdOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.ElementId>();
var beamIdsOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId,
    System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>>();

// "400 x 900", or "D500" for a round one.
System.Func<double[], string> sizeTextOf = n => n[N_IS_ROUND] > 0.5
    ? string.Format(inv, "D{0:0}", n[N_WIDTH])
    : string.Format(inv, "{0:0} x {1:0}", n[N_WIDTH], n[N_DEPTH]);

// ------------------------------------------------------- the columns to do --

var wantedCategories = new Autodesk.Revit.DB.BuiltInCategory[]
{
    Autodesk.Revit.DB.BuiltInCategory.OST_StructuralColumns,
    Autodesk.Revit.DB.BuiltInCategory.OST_Columns
};

var columns = new System.Collections.Generic.List<Autodesk.Revit.DB.FamilyInstance>();
foreach (Autodesk.Revit.DB.ElementId selectedId in theUiDoc.Selection.GetElementIds())
{
    var picked = theDoc.GetElement(selectedId) as Autodesk.Revit.DB.FamilyInstance;
    if (picked == null || picked.Category == null) continue;
    foreach (Autodesk.Revit.DB.BuiltInCategory bic in wantedCategories)
    {
        Autodesk.Revit.DB.Category category = Autodesk.Revit.DB.Category.GetCategory(theDoc, bic);
        if (category != null && category.Id == picked.Category.Id)
        {
            columns.Add(picked);
            break;
        }
    }
}

bool fromSelection = columns.Count > 0;
if (!fromSelection)
{
    foreach (Autodesk.Revit.DB.BuiltInCategory bic in wantedCategories)
    {
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfCategory(bic)
            .OfClass(typeof(Autodesk.Revit.DB.FamilyInstance))
            .WhereElementIsNotElementType())
        {
            var instance = e as Autodesk.Revit.DB.FamilyInstance;
            if (instance != null) columns.Add(instance);
        }
    }
}

if (columns.Count == 0)
{
    Autodesk.Revit.UI.TaskDialog.Show("Column sections", "No columns found in this model.");
}
else
{
    // ------------------------------------------- the model around them --

    // Foundations, with the footprint and the type name kept.
    var foundationBoxes = new System.Collections.Generic.List<Autodesk.Revit.DB.BoundingBoxXYZ>();
    var foundationNames = new System.Collections.Generic.List<string>();
    var foundationIds = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_StructuralFoundation)
        .WhereElementIsNotElementType())
    {
        Autodesk.Revit.DB.BoundingBoxXYZ bb = e.get_BoundingBox(null);
        if (bb == null) continue;
        var elementType = theDoc.GetElement(e.GetTypeId()) as Autodesk.Revit.DB.ElementType;
        foundationBoxes.Add(bb);
        foundationNames.Add(elementType != null ? elementType.Name : e.Name);
        foundationIds.Add(e.Id);
    }

    // Beams, as a tessellated centre line and the height band it lies in.
    var beamPoints = new System.Collections.Generic.List<System.Collections.Generic.IList<Autodesk.Revit.DB.XYZ>>();
    var beamZMin = new System.Collections.Generic.List<double>();
    var beamZMax = new System.Collections.Generic.List<double>();
    var beamIds = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType())
    {
        var line = e.Location as Autodesk.Revit.DB.LocationCurve;
        if (line == null || line.Curve == null) continue;
        System.Collections.Generic.IList<Autodesk.Revit.DB.XYZ> pts = line.Curve.Tessellate();
        if (pts == null || pts.Count < 2) continue;
        double zLow = pts[0].Z, zHigh = pts[0].Z;
        foreach (Autodesk.Revit.DB.XYZ p in pts)
        {
            if (p.Z < zLow) zLow = p.Z;
            if (p.Z > zHigh) zHigh = p.Z;
        }
        beamPoints.Add(pts);
        beamZMin.Add(zLow);
        beamZMax.Add(zHigh);
        beamIds.Add(e.Id);
    }

    // Ground: the level named above, or the one nearest project zero.
    double groundElevation = 0.0;
    string groundFrom = "elevation 0";
    Autodesk.Revit.DB.Level groundLevel = null;
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfClass(typeof(Autodesk.Revit.DB.Level)))
    {
        var level = e as Autodesk.Revit.DB.Level;
        if (level == null) continue;
        if (!string.IsNullOrEmpty(groundLevelName))
        {
            if (string.Equals(level.Name, groundLevelName, System.StringComparison.OrdinalIgnoreCase))
            {
                groundLevel = level;
                break;
            }
        }
        else if (groundLevel == null
                 || System.Math.Abs(level.Elevation) < System.Math.Abs(groundLevel.Elevation))
        {
            groundLevel = level;
        }
    }
    if (groundLevel != null)
    {
        groundElevation = groundLevel.Elevation;
        groundFrom = groundLevel.Name;
    }

    // ----------------------------------------------------- small helpers --

    // First of the named parameters that holds a length, on the instance or
    // its type. Zero when none of them do.
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

    // Every vertex of an element's solids, in model coordinates.
    System.Action<Autodesk.Revit.DB.GeometryElement,
                  System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>> collect = null;
    collect = (geometry, into) =>
    {
        foreach (Autodesk.Revit.DB.GeometryObject go in geometry)
        {
            var solid = go as Autodesk.Revit.DB.Solid;
            if (solid != null && solid.Volume > 1e-9)
            {
                foreach (Autodesk.Revit.DB.Edge edge in solid.Edges)
                {
                    foreach (Autodesk.Revit.DB.XYZ p in edge.Tessellate()) into.Add(p);
                }
                continue;
            }
            var nested = go as Autodesk.Revit.DB.GeometryInstance;
            if (nested != null)
            {
                Autodesk.Revit.DB.GeometryElement inner = nested.GetInstanceGeometry();
                if (inner != null) collect(inner, into);
            }
        }
    };

    // The eight corners of a bounding box, in model coordinates.
    System.Func<Autodesk.Revit.DB.BoundingBoxXYZ,
                System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>> cornersOf = bb =>
    {
        var result = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
        Autodesk.Revit.DB.Transform t = bb.Transform != null
            ? bb.Transform : Autodesk.Revit.DB.Transform.Identity;
        double[] xs = new double[] { bb.Min.X, bb.Max.X };
        double[] ys = new double[] { bb.Min.Y, bb.Max.Y };
        double[] zs = new double[] { bb.Min.Z, bb.Max.Z };
        foreach (double x in xs)
        {
            foreach (double y in ys)
            {
                foreach (double z in zs)
                    result.Add(t.OfPoint(new Autodesk.Revit.DB.XYZ(x, y, z)));
            }
        }
        return result;
    };

    // Shortest distance in plan from a point to a tessellated curve.
    System.Func<System.Collections.Generic.IList<Autodesk.Revit.DB.XYZ>,
                Autodesk.Revit.DB.XYZ, double> planDistance = (points, target) =>
    {
        double best = double.MaxValue;
        for (int i = 0; i < points.Count - 1; i++)
        {
            double ax = points[i].X, ay = points[i].Y;
            double dx = points[i + 1].X - ax, dy = points[i + 1].Y - ay;
            double lengthSquared = dx * dx + dy * dy;
            double t = lengthSquared < 1e-12
                ? 0.0
                : ((target.X - ax) * dx + (target.Y - ay) * dy) / lengthSquared;
            if (t < 0) t = 0; else if (t > 1) t = 1;
            double cx = ax + t * dx, cy = ay + t * dy;
            double d = System.Math.Sqrt((target.X - cx) * (target.X - cx)
                                      + (target.Y - cy) * (target.Y - cy));
            if (d < best) best = d;
        }
        return best;
    };

    // ------------------------------------------------- measure the columns --

    foreach (Autodesk.Revit.DB.FamilyInstance column in columns)
    {
        Autodesk.Revit.DB.BoundingBoxXYZ box = column.get_BoundingBox(null);
        if (box == null) continue;

        double[] n = new double[NUMBER_SLOTS];
        string[] s = new string[TEXT_SLOTS];
        for (int i = 0; i < TEXT_SLOTS; i++) s[i] = "";

        // Which way it faces, so the section looks square-on at it.
        double rotation = 0.0;
        var point = column.Location as Autodesk.Revit.DB.LocationPoint;
        var curve = column.Location as Autodesk.Revit.DB.LocationCurve;
        if (point != null)
        {
            try { rotation = point.Rotation; }
            catch { rotation = 0.0; }
        }
        else if (curve != null && curve.Curve != null)
        {
            Autodesk.Revit.DB.XYZ run = curve.Curve.GetEndPoint(1) - curve.Curve.GetEndPoint(0);
            var flat = new Autodesk.Revit.DB.XYZ(run.X, run.Y, 0);
            if (flat.GetLength() > 1e-6)
                rotation = System.Math.Atan2(flat.Y, flat.X) + System.Math.PI / 2.0;
        }
        n[N_ROTATION] = rotation;

        // Base and top: the level parameters where it has them, the solid where
        // it does not (a slanted column).
        double baseZ = box.Min.Z, topZ = box.Max.Z;
        Autodesk.Revit.DB.Parameter baseLevelParam =
            column.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
        Autodesk.Revit.DB.Parameter topLevelParam =
            column.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
        if (baseLevelParam != null && baseLevelParam.StorageType == Autodesk.Revit.DB.StorageType.ElementId)
        {
            var level = theDoc.GetElement(baseLevelParam.AsElementId()) as Autodesk.Revit.DB.Level;
            if (level != null)
            {
                double offset = 0.0;
                Autodesk.Revit.DB.Parameter o = column.get_Parameter(
                    Autodesk.Revit.DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
                if (o != null && o.StorageType == Autodesk.Revit.DB.StorageType.Double) offset = o.AsDouble();
                baseZ = level.Elevation + offset;
                s[T_BASE_LEVEL] = level.Name;
            }
        }
        if (topLevelParam != null && topLevelParam.StorageType == Autodesk.Revit.DB.StorageType.ElementId)
        {
            var level = theDoc.GetElement(topLevelParam.AsElementId()) as Autodesk.Revit.DB.Level;
            if (level != null)
            {
                double offset = 0.0;
                Autodesk.Revit.DB.Parameter o = column.get_Parameter(
                    Autodesk.Revit.DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
                if (o != null && o.StorageType == Autodesk.Revit.DB.StorageType.Double) offset = o.AsDouble();
                topZ = level.Elevation + offset;
            }
        }
        if (topZ < baseZ)
        {
            double swap = baseZ; baseZ = topZ; topZ = swap;
        }

        var centre = new Autodesk.Revit.DB.XYZ(
            (box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0, 0);
        if (point != null) centre = new Autodesk.Revit.DB.XYZ(point.Point.X, point.Point.Y, 0);

        // Its size: the parameters if the family has them, the solid if not.
        Autodesk.Revit.DB.FamilySymbol symbol = column.Symbol;
        string familyName = symbol != null && symbol.Family != null ? symbol.Family.Name : "";
        string typeName = symbol != null ? symbol.Name : "";
        string wholeName = (familyName + " " + typeName).ToUpperInvariant();
        bool looksRound = wholeName.Contains("CIRC") || wholeName.Contains("ROUND")
                       || wholeName.Contains("PIPE") || wholeName.Contains("DIAM")
                       || wholeName.Contains("CYLIND");

        double widthMm = 0.0, depthMm = 0.0;
        bool isRound = false;
        double diameter = firstLength(column, symbol, diameterParameterNames);
        if (diameter > 0 && looksRound)
        {
            isRound = true;
            widthMm = toMm(diameter);
            depthMm = widthMm;
        }
        else
        {
            double width = firstLength(column, symbol, widthParameterNames);
            double depth = firstLength(column, symbol, depthParameterNames);
            if (width > 0 && depth > 0)
            {
                widthMm = toMm(width);
                depthMm = toMm(depth);
            }
            else
            {
                var right = new Autodesk.Revit.DB.XYZ(
                    System.Math.Cos(rotation), System.Math.Sin(rotation), 0);
                Autodesk.Revit.DB.XYZ into = right.CrossProduct(Autodesk.Revit.DB.XYZ.BasisZ);
                var vertices = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
                var options = new Autodesk.Revit.DB.Options();
                options.ComputeReferences = false;
                options.IncludeNonVisibleObjects = false;
                options.DetailLevel = Autodesk.Revit.DB.ViewDetailLevel.Medium;
                Autodesk.Revit.DB.GeometryElement geometry = column.get_Geometry(options);
                if (geometry != null) collect(geometry, vertices);

                if (vertices.Count > 0)
                {
                    double minR = double.MaxValue, maxR = double.MinValue;
                    double minI = double.MaxValue, maxI = double.MinValue;
                    foreach (Autodesk.Revit.DB.XYZ p in vertices)
                    {
                        double r = p.DotProduct(right), i = p.DotProduct(into);
                        if (r < minR) minR = r;
                        if (r > maxR) maxR = r;
                        if (i < minI) minI = i;
                        if (i > maxI) maxI = i;
                    }
                    widthMm = toMm(maxR - minR);
                    depthMm = toMm(maxI - minI);
                }
                else
                {
                    widthMm = toMm(box.Max.X - box.Min.X);
                    depthMm = toMm(box.Max.Y - box.Min.Y);
                }
                isRound = looksRound && System.Math.Abs(widthMm - depthMm) < sizeToleranceMm;
            }
        }

        n[N_BASE_Z_FT] = baseZ;
        n[N_TOP_Z_FT] = topZ;
        n[N_WIDTH] = snap(widthMm, sizeToleranceMm);
        n[N_DEPTH] = snap(depthMm, sizeToleranceMm);
        n[N_IS_ROUND] = isRound ? 1 : 0;
        n[N_HEIGHT] = snap(toMm(topZ - baseZ), levelToleranceMm);
        n[N_BASE] = snap(toMm(baseZ), levelToleranceMm);
        n[N_TOP] = snap(toMm(topZ), levelToleranceMm);
        n[N_BELOW_GROUND] = snap(toMm(groundElevation - baseZ), levelToleranceMm);

        s[T_FAMILY] = familyName;
        s[T_TYPE] = typeName;
        Autodesk.Revit.DB.Parameter markParam =
            column.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ALL_MODEL_MARK);
        string mark = markParam != null ? markParam.AsString() : null;
        s[T_MARK] = string.IsNullOrEmpty(mark) ? column.Id.ToString() : mark.Trim();

        var basePoint = new Autodesk.Revit.DB.XYZ(centre.X, centre.Y, baseZ);
        var topPoint = new Autodesk.Revit.DB.XYZ(centre.X, centre.Y, topZ);

        // The foundation under it: the highest one whose footprint it stands on,
        // so a footing wins over the raft it sits in.
        double foundationTolerance = toFeet(foundationSearchToleranceMm);
        int bestFoundation = -1;
        for (int i = 0; i < foundationBoxes.Count; i++)
        {
            Autodesk.Revit.DB.BoundingBoxXYZ bb = foundationBoxes[i];
            if (basePoint.X < bb.Min.X - foundationTolerance || basePoint.X > bb.Max.X + foundationTolerance) continue;
            if (basePoint.Y < bb.Min.Y - foundationTolerance || basePoint.Y > bb.Max.Y + foundationTolerance) continue;
            if (bb.Max.Z > baseZ + foundationTolerance) continue;
            if (bestFoundation < 0 || bb.Max.Z > foundationBoxes[bestFoundation].Max.Z) bestFoundation = i;
        }
        if (bestFoundation >= 0)
        {
            Autodesk.Revit.DB.BoundingBoxXYZ bb = foundationBoxes[bestFoundation];
            n[N_HAS_FOUNDATION] = 1;
            n[N_FOUNDATION_TOP] = snap(toMm(bb.Max.Z), levelToleranceMm);
            n[N_FOUNDATION_THICKNESS] = snap(toMm(bb.Max.Z - bb.Min.Z), levelToleranceMm);
            s[T_FOUNDATION] = foundationNames[bestFoundation];
            foundationBoxOf[column.Id] = bb;
            foundationIdOf[column.Id] = foundationIds[bestFoundation];
        }

        // The beams framing into it: centre lines passing close to it in plan
        // while their height overlaps it, so a beam running over the column
        // counts as well as one stopping at it.
        double planReach = toFeet(System.Math.Max(n[N_WIDTH], n[N_DEPTH])) / 2.0
                         + toFeet(beamSearchToleranceMm);
        double beamReach = toFeet(beamVerticalToleranceMm);
        int beams = 0;
        bool beamAtTop = false;
        var connectedBeams = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
        for (int i = 0; i < beamPoints.Count; i++)
        {
            if (beamZMax[i] < baseZ - beamReach || beamZMin[i] > topZ + beamReach) continue;
            if (planDistance(beamPoints[i], basePoint) > planReach) continue;
            beams++;
            connectedBeams.Add(beamIds[i]);
            if (beamZMax[i] > topZ - beamReach) beamAtTop = true;
        }
        beamIdsOf[column.Id] = connectedBeams;
        n[N_BEAMS] = beams;
        n[N_BEAM_AT_TOP] = beamAtTop ? 1 : 0;

        ids.Add(column.Id);
        instanceOf[column.Id] = column;
        numberOf[column.Id] = n;
        textOf[column.Id] = s;
        boxOf[column.Id] = box;
        basePointOf[column.Id] = basePoint;
        topPointOf[column.Id] = topPoint;
    }

    // ------------------------------ what sits above and below, same location --

    double stackSlack = toFeet(stackSearchToleranceMm);
    double stackReach = toFeet(stackVerticalToleranceMm);
    foreach (Autodesk.Revit.DB.ElementId id in ids)
    {
        double[] n = numberOf[id];
        Autodesk.Revit.DB.XYZ here = basePointOf[id];
        double leastHere = toFeet(System.Math.Min(n[N_WIDTH], n[N_DEPTH]));

        Autodesk.Revit.DB.ElementId above = null, below = null;
        foreach (Autodesk.Revit.DB.ElementId other in ids)
        {
            if (other == id) continue;
            double[] m = numberOf[other];
            Autodesk.Revit.DB.XYZ there = basePointOf[other];

            // Allowed to step in by half the smaller column's least side, so one
            // flush on a face is still the same stack.
            double reach = stackSlack
                + System.Math.Min(leastHere, toFeet(System.Math.Min(m[N_WIDTH], m[N_DEPTH]))) / 2.0;
            double dx = there.X - here.X, dy = there.Y - here.Y;
            if (System.Math.Abs(dx) > reach || System.Math.Abs(dy) > reach) continue;
            if (System.Math.Sqrt(dx * dx + dy * dy) > reach) continue;

            bool sitsAbove = m[N_BASE_Z_FT] >= n[N_TOP_Z_FT] - stackReach
                          && m[N_TOP_Z_FT] > n[N_TOP_Z_FT] + 1e-6;
            if (sitsAbove && (above == null || m[N_BASE_Z_FT] < numberOf[above][N_BASE_Z_FT]))
                above = other;

            bool sitsBelow = m[N_TOP_Z_FT] <= n[N_BASE_Z_FT] + stackReach
                          && m[N_BASE_Z_FT] < n[N_BASE_Z_FT] - 1e-6;
            if (sitsBelow && (below == null || m[N_TOP_Z_FT] > numberOf[below][N_TOP_Z_FT]))
                below = other;
        }

        if (above != null)
        {
            aboveOf[id] = above;
            textOf[id][T_SIZE_ABOVE] = sizeTextOf(numberOf[above]);
        }
        if (below != null)
        {
            belowOf[id] = below;
            textOf[id][T_SIZE_BELOW] = sizeTextOf(numberOf[below]);
        }
    }

    // ------------------------------------ the stack each column belongs to --

    // Walking aboveOf from a column with nothing under it gives one column line,
    // bottom lift first. That line is what gets a section: the 600x900 and the
    // 400x900 standing on it are one column, counted once.
    var chainOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId, System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>>();
    var subjects = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
    var claimed = new System.Collections.Generic.HashSet<Autodesk.Revit.DB.ElementId>();

    if (oneSectionPerStack)
    {
        // Bottoms first, so every stack is walked from the ground up.
        for (int pass = 0; pass < 2; pass++)
        {
            foreach (Autodesk.Revit.DB.ElementId id in ids)
            {
                if (claimed.Contains(id)) continue;
                // The second pass picks up anything the first could not reach.
                if (pass == 0 && belowOf.ContainsKey(id)) continue;

                var chain = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                Autodesk.Revit.DB.ElementId walk = id;
                while (walk != null && !claimed.Contains(walk) && chain.Count < 200)
                {
                    chain.Add(walk);
                    claimed.Add(walk);
                    walk = aboveOf.ContainsKey(walk) ? aboveOf[walk] : null;
                }
                chainOf[id] = chain;
                subjects.Add(id);
            }
        }
    }
    else
    {
        foreach (Autodesk.Revit.DB.ElementId id in ids)
        {
            var chain = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
            chain.Add(id);
            chainOf[id] = chain;
            subjects.Add(id);
        }
    }

    // ----------------------------------------------- sort them into types --

    var membersOf = new System.Collections.Generic.Dictionary<string, System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>>();
    var keys = new System.Collections.Generic.List<string>();

    foreach (Autodesk.Revit.DB.ElementId id in subjects)
    {
        double[] n = numberOf[id];
        string[] s = textOf[id];
        var key = new System.Text.StringBuilder();

        if (familyNameIsPartOfType) key.Append(s[T_FAMILY]).Append('|').Append(s[T_TYPE]).Append('|');
        key.Append(sizeTextOf(n)).Append('|');
        if (heightIsPartOfType) key.AppendFormat(inv, "H{0:0}|", n[N_HEIGHT]);
        key.Append(n[N_HAS_FOUNDATION] > 0.5
            ? string.Format(inv, "F:{0}:{1:0}:{2:0}", s[T_FOUNDATION], n[N_FOUNDATION_TOP], n[N_FOUNDATION_THICKNESS])
            : "F:none").Append('|');
        key.Append(countBeamsSeparately
            ? string.Format(inv, "B:{0:0}:{1:0}", n[N_BEAMS], n[N_BEAM_AT_TOP])
            : string.Format(inv, "B:{0}", n[N_BEAMS] > 0.5 ? 1 : 0)).Append('|');
        key.AppendFormat(inv, "G:{0:0}", n[N_BELOW_GROUND]);
        if (stackChangeIsPartOfType)
        {
            if (oneSectionPerStack)
            {
                // Every lift of the stack, in order: two stacks are the same only
                // if they change size at the same places.
                key.Append("|L:");
                foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
                {
                    key.Append(sizeTextOf(numberOf[member]));
                    if (heightIsPartOfType) key.AppendFormat(inv, "@{0:0}", numberOf[member][N_HEIGHT]);
                    key.Append(';');
                }
            }
            else
            {
                key.Append("|A:").Append(s[T_SIZE_ABOVE].Length > 0 ? s[T_SIZE_ABOVE] : "none");
                key.Append("|U:").Append(s[T_SIZE_BELOW].Length > 0 ? s[T_SIZE_BELOW] : "none");
            }
        }

        string signature = key.ToString();
        System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members;
        if (!membersOf.TryGetValue(signature, out members))
        {
            members = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
            membersOf.Add(signature, members);
            keys.Add(signature);
        }
        members.Add(id);
    }

    // The type that repeats most becomes CT-01.
    keys.Sort(delegate(string a, string b)
    {
        int byCount = membersOf[b].Count.CompareTo(membersOf[a].Count);
        if (byCount != 0) return byCount;
        return string.Compare(a, b, System.StringComparison.Ordinal);
    });
    foreach (string key in keys)
    {
        membersOf[key].Sort(delegate(Autodesk.Revit.DB.ElementId a, Autodesk.Revit.DB.ElementId b)
        {
            return string.Compare(textOf[a][T_MARK], textOf[b][T_MARK],
                System.StringComparison.OrdinalIgnoreCase);
        });
    }

    // --------------------------------------- the view type and text type --

    Autodesk.Revit.DB.ViewFamilyType sectionType = null;
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfClass(typeof(Autodesk.Revit.DB.ViewFamilyType)))
    {
        var candidate = e as Autodesk.Revit.DB.ViewFamilyType;
        if (candidate != null && candidate.ViewFamily == Autodesk.Revit.DB.ViewFamily.Section)
        {
            sectionType = candidate;
            break;
        }
    }

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

    if (sectionType == null || textType == null)
    {
        Autodesk.Revit.UI.TaskDialog.Show("Column sections", sectionType == null
            ? "This model has no section view type, so no section can be created."
            : "This model has no text type, so the note cannot be written.");
    }
    else
    {
        double textSizeFeet = 0.0082;
        double textWidthFactor = 1.0;
        Autodesk.Revit.DB.Parameter textSizeParam =
            textType.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.TEXT_SIZE);
        if (textSizeParam != null && textSizeParam.AsDouble() > 1e-9) textSizeFeet = textSizeParam.AsDouble();
        Autodesk.Revit.DB.Parameter widthFactorParam =
            textType.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.TEXT_WIDTH_SCALE);
        if (widthFactorParam != null && widthFactorParam.AsDouble() > 1e-9) textWidthFactor = widthFactorParam.AsDouble();

        var usedNames = new System.Collections.Generic.HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfClass(typeof(Autodesk.Revit.DB.View)))
        {
            var view = e as Autodesk.Revit.DB.View;
            if (view != null) usedNames.Add(view.Name);
        }

        // What every section keeps, whatever column it is of: the datums, and the
        // categories named in the settings - the floors above, above all.
        var alwaysVisibleIds = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfClass(typeof(Autodesk.Revit.DB.Level)))
        {
            alwaysVisibleIds.Add(e.Id);
        }
        foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
            .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_Grids).WhereElementIsNotElementType())
        {
            alwaysVisibleIds.Add(e.Id);
        }
        foreach (Autodesk.Revit.DB.BuiltInCategory bic in alwaysVisibleCategories)
        {
            foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
                .OfCategory(bic).WhereElementIsNotElementType())
            {
                alwaysVisibleIds.Add(e.Id);
            }
        }

        // The lines of the note, and the summary line, for one type.
        System.Func<Autodesk.Revit.DB.ElementId, string, int, string[]> noteLinesOf =
            (id, code, count) =>
        {
            double[] n = numberOf[id];
            string[] s = textOf[id];
            var lines = new System.Collections.Generic.List<string>();
            lines.Add(string.Format(inv, "{0} - {1} COLUMN{2} OF THIS TYPE",
                code, count, count == 1 ? "" : "S"));

            var chain = chainOf.ContainsKey(id) ? chainOf[id] : null;
            if (chain != null && chain.Count > 1)
            {
                lines.Add(string.Format(inv, "{0} LIFTS, FOUNDATION UP", chain.Count));
                int shownLifts = 0;
                foreach (Autodesk.Revit.DB.ElementId member in chain)
                {
                    if (shownLifts >= maxLiftsInNote)
                    {
                        lines.Add(string.Format(inv, "(+{0} MORE LIFTS)", chain.Count - shownLifts));
                        break;
                    }
                    double[] mn = numberOf[member];
                    lines.Add(string.Format(inv, "LIFT {0}: {1}  ({2:0} TO {3:0})",
                        shownLifts + 1, sizeTextOf(mn), mn[N_BASE], mn[N_TOP]));
                    shownLifts++;
                }
            }
            else
            {
                lines.Add("SIZE: " + sizeTextOf(n) + "  (" + s[T_TYPE] + ")");
            }
            lines.Add(n[N_HAS_FOUNDATION] > 0.5
                ? string.Format(inv, "FDN TOP {0:+0;-0;0} ({1:0} THK)", n[N_FOUNDATION_TOP], n[N_FOUNDATION_THICKNESS])
                : "NO FOUNDATION FOUND");
            lines.Add(n[N_BEAMS] < 0.5
                ? "NO BEAM CONNECTED"
                : string.Format(inv, "{0:0} BEAM{1} CONNECTED{2}", n[N_BEAMS],
                    n[N_BEAMS] > 1.5 ? "S" : "", n[N_BEAM_AT_TOP] > 0.5 ? " (AT TOP)" : ""));
            lines.Add(System.Math.Abs(n[N_BELOW_GROUND]) < 1.0
                ? "BASE AT GROUND LEVEL"
                : (n[N_BELOW_GROUND] > 0
                    ? string.Format(inv, "BASE {0:0} BELOW GROUND", n[N_BELOW_GROUND])
                    : string.Format(inv, "BASE {0:0} ABOVE GROUND", -n[N_BELOW_GROUND])));
            if (chain == null || chain.Count < 2)
            {
                lines.Add(s[T_SIZE_BELOW].Length == 0
                    ? "NOTHING BELOW (COLUMN STARTS HERE)"
                    : "BELOW: " + s[T_SIZE_BELOW] + (s[T_SIZE_BELOW] == sizeTextOf(n)
                        ? " - SAME SIZE" : " - SIZE CHANGES"));
                lines.Add(s[T_SIZE_ABOVE].Length == 0
                    ? "NOTHING ABOVE (TOP OF STACK)"
                    : "ABOVE: " + s[T_SIZE_ABOVE] + (s[T_SIZE_ABOVE] == sizeTextOf(n)
                        ? " - SAME SIZE" : " - SIZE CHANGES"));
                lines.Add(string.Format(inv, "BASE {0:0} / TOP {1:0} / HT {2:0}",
                    n[N_BASE], n[N_TOP], n[N_HEIGHT]));
            }

            // The marks themselves are added by the caller, which knows the
            // whole group.
            return lines.ToArray();
        };

        // A summary of every type, for the dialogs.
        var summary = new System.Text.StringBuilder();
        for (int i = 0; i < keys.Count; i++)
        {
            System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members = membersOf[keys[i]];
            double[] n = numberOf[members[0]];
            string[] s = textOf[members[0]];
            summary.AppendFormat(inv, "{0}-{1:00}  x{2}  {3}  |  {4}  |  {5} beam(s)  |  {6:0} below ground  |  {7} > {8} > {9}  |  {10} lift(s)\n",
                typeCodePrefix, i + 1, members.Count, sizeTextOf(n),
                n[N_HAS_FOUNDATION] > 0.5 ? s[T_FOUNDATION] : "no foundation",
                n[N_BEAMS], n[N_BELOW_GROUND],
                s[T_SIZE_BELOW].Length > 0 ? s[T_SIZE_BELOW] : "-",
                sizeTextOf(n),
                s[T_SIZE_ABOVE].Length > 0 ? s[T_SIZE_ABOVE] : "-",
                chainOf.ContainsKey(members[0]) ? chainOf[members[0]].Count : 1);
        }

        var ask = new Autodesk.Revit.UI.TaskDialog("Column sections");
        ask.MainInstruction = string.Format(inv, "{0} column{1} in {2} type{3}.",
            subjects.Count, subjects.Count == 1 ? "" : "s", keys.Count, keys.Count == 1 ? "" : "s");
        ask.MainContent = string.Format(inv,
            "Read from {0}, {1} columns in all. Ground is taken from level \"{2}\".\n\n{3}"
            + "One cross section will be created for each type, with a note in it saying how "
            + "many columns share that type.",
            fromSelection ? "your selection" : "the whole model", ids.Count, groundFrom,
            oneSectionPerStack
                ? "A column standing on another is one column here, not two: the section is "
                  + "taken on the one that starts at the foundation and covers every lift above "
                  + "it, so the counts are counts of columns on the ground.\n\n"
                : "");
        ask.ExpandedContent = summary.ToString();
        ask.CommonButtons = Autodesk.Revit.UI.TaskDialogCommonButtons.Yes
                          | Autodesk.Revit.UI.TaskDialogCommonButtons.No;
        ask.DefaultButton = Autodesk.Revit.UI.TaskDialogResult.Yes;

        if (ask.Show() == Autodesk.Revit.UI.TaskDialogResult.Yes)
        {
            var failures = new System.Collections.Generic.List<string>();
            int made = 0;

            using (var transaction = new Autodesk.Revit.DB.Transaction(theDoc, "Column type cross sections"))
            {
                transaction.Start();

                for (int index = 0; index < keys.Count; index++)
                {
                    System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members = membersOf[keys[index]];
                    Autodesk.Revit.DB.ElementId id = members[0];
                    string code = string.Format(inv, "{0}-{1:00}", typeCodePrefix, index + 1);

                    try
                    {
                        double[] n = numberOf[id];
                        Autodesk.Revit.DB.XYZ origin = basePointOf[id];

                        var right = new Autodesk.Revit.DB.XYZ(
                            System.Math.Cos(n[N_ROTATION]), System.Math.Sin(n[N_ROTATION]), 0).Normalize();
                        Autodesk.Revit.DB.XYZ up = Autodesk.Revit.DB.XYZ.BasisZ;
                        Autodesk.Revit.DB.XYZ towardsViewer = right.CrossProduct(up).Normalize();

                        // The stack itself, and nothing else, decides how wide
                        // and how deep the view is - and how tall: every lift of
                        // it is in the section, foundation to roof.
                        var columnPoints = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
                        foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
                        {
                            columnPoints.AddRange(cornersOf(boxOf[member]));
                            columnPoints.Add(basePointOf[member]);
                            columnPoints.Add(topPointOf[member]);
                        }

                        double minR = 0, maxR = 0, minU = 0, maxU = 0, minD = 0, maxD = 0;
                        bool first = true;
                        foreach (Autodesk.Revit.DB.XYZ p in columnPoints)
                        {
                            Autodesk.Revit.DB.XYZ v = p - origin;
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

                        // The footing below and the lift above may take the view
                        // higher or lower, and only so much wider. They may not
                        // take it deeper at all - that is what kept the far clip
                        // out at the size of the raft.
                        var extraPoints = new System.Collections.Generic.List<Autodesk.Revit.DB.XYZ>();
                        if (foundationBoxOf.ContainsKey(id))
                            extraPoints.AddRange(cornersOf(foundationBoxOf[id]));

                        // Below the base whatever happens, so the footing is in
                        // the view even where none was found to measure.
                        extraPoints.Add(new Autodesk.Revit.DB.XYZ(
                            origin.X, origin.Y, origin.Z - toFeet(alwaysShowBelowBaseMm)));

                        if (!oneSectionPerStack)
                        {
                            // Without stacks, the lifts either side are only
                            // glimpsed rather than drawn whole.
                            if (aboveOf.ContainsKey(id) && boxOf.ContainsKey(aboveOf[id]))
                            {
                                double ceiling = topPointOf[id].Z + toFeet(showAboveMm);
                                foreach (Autodesk.Revit.DB.XYZ p in cornersOf(boxOf[aboveOf[id]]))
                                    extraPoints.Add(new Autodesk.Revit.DB.XYZ(p.X, p.Y, System.Math.Min(p.Z, ceiling)));
                            }
                            if (belowOf.ContainsKey(id) && boxOf.ContainsKey(belowOf[id]))
                            {
                                double floor = origin.Z - toFeet(showBelowMm);
                                foreach (Autodesk.Revit.DB.XYZ p in cornersOf(boxOf[belowOf[id]]))
                                    extraPoints.Add(new Autodesk.Revit.DB.XYZ(p.X, p.Y, System.Math.Max(p.Z, floor)));
                            }
                        }

                        double reachLeft = minR - toFeet(maxExtraWidthMm);
                        double reachRight = maxR + toFeet(maxExtraWidthMm);
                        foreach (Autodesk.Revit.DB.XYZ p in extraPoints)
                        {
                            Autodesk.Revit.DB.XYZ v = p - origin;
                            double r = v.DotProduct(right), u = v.DotProduct(up);
                            if (r < reachLeft) r = reachLeft; else if (r > reachRight) r = reachRight;
                            if (r < minR) minR = r; else if (r > maxR) maxR = r;
                            if (u < minU) minU = u; else if (u > maxU) maxU = u;
                        }

                        minR -= toFeet(sideClearanceMm);
                        maxR += toFeet(sideClearanceMm);
                        minU -= toFeet(bottomClearanceMm);
                        maxU += toFeet(topClearanceMm);
                        minD -= toFeet(viewDepthClearanceMm);
                        maxD += toFeet(viewDepthClearanceMm);

                        // The note goes in a band above the column, never on it.
                        string[] lines = noteLinesOf(id, code, members.Count);
                        var noteText = new System.Text.StringBuilder();
                        int longest = 0;
                        for (int i = 0; i < lines.Length; i++)
                        {
                            if (lines[i].Length == 0) continue;
                            if (i > 0) noteText.Append("\n");
                            noteText.Append(lines[i]);
                            if (lines[i].Length > longest) longest = lines[i].Length;
                        }
                        if (maxMarksInNote > 0)
                        {
                            var marks = new System.Text.StringBuilder("MARKS: ");
                            int shown = 0;
                            foreach (Autodesk.Revit.DB.ElementId member in members)
                            {
                                if (shown >= maxMarksInNote) break;
                                if (shown > 0) marks.Append(", ");
                                marks.Append(textOf[member][T_MARK]);
                                shown++;
                            }
                            if (members.Count > shown)
                                marks.AppendFormat(inv, " (+{0} MORE)", members.Count - shown);
                            noteText.Append("\n").Append(marks.ToString());
                            if (marks.Length > longest) longest = marks.Length;
                        }

                        double lineHeight = textSizeFeet * viewScale * 1.4;
                        double noteHeight = lineHeight * (lines.Length + 1);
                        double noteWidth = longest * textSizeFeet * textWidthFactor * 0.62 * viewScale;
                        double inset = textSizeFeet * viewScale;

                        if (expandCropForNote)
                        {
                            // Room made for the note inside the crop, which is
                            // what makes the view as wide as the longest line.
                            maxU += noteHeight + 2 * inset;
                            double needed = noteWidth + 2 * inset;
                            if (maxR - minR < needed)
                            {
                                double grow = (needed - (maxR - minR)) / 2.0;
                                minR -= grow;
                                maxR += grow;
                            }
                        }

                        Autodesk.Revit.DB.XYZ centreOfBox = origin
                            + right * ((minR + maxR) / 2.0)
                            + up * ((minU + maxU) / 2.0)
                            + towardsViewer * ((minD + maxD) / 2.0);

                        Autodesk.Revit.DB.Transform transform = Autodesk.Revit.DB.Transform.Identity;
                        transform.Origin = centreOfBox;
                        transform.BasisX = right;
                        transform.BasisY = up;
                        transform.BasisZ = towardsViewer;

                        double halfWidth = (maxR - minR) / 2.0;
                        double halfHeight = (maxU - minU) / 2.0;
                        double halfDepth = (maxD - minD) / 2.0;

                        var sectionBox = new Autodesk.Revit.DB.BoundingBoxXYZ();
                        sectionBox.Transform = transform;
                        sectionBox.Min = new Autodesk.Revit.DB.XYZ(-halfWidth, -halfHeight, -halfDepth);
                        sectionBox.Max = new Autodesk.Revit.DB.XYZ(halfWidth, halfHeight, halfDepth);

                        Autodesk.Revit.DB.ViewSection view =
                            Autodesk.Revit.DB.ViewSection.CreateSection(theDoc, sectionType.Id, sectionBox);
                        view.Scale = viewScale;
                        try { view.DetailLevel = Autodesk.Revit.DB.ViewDetailLevel.Fine; }
                        catch { /* a view template may be holding it */ }
                        try { view.CropBoxVisible = false; }
                        catch { /* likewise */ }

                        string wanted = string.Format(inv, "{0} - {1} ({2} NO{3})",
                            viewNamePrefix, code, members.Count, members.Count == 1 ? "" : "S");
                        char[] illegal = new char[] { '\\', ':', '{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~' };
                        var cleaned = new System.Text.StringBuilder();
                        foreach (char ch in wanted)
                            cleaned.Append(System.Array.IndexOf(illegal, ch) >= 0 ? '-' : ch);
                        string name = cleaned.ToString().Trim();
                        string unique = name;
                        int suffix = 2;
                        while (usedNames.Contains(unique))
                        {
                            unique = name + " " + suffix;
                            suffix++;
                        }
                        usedNames.Add(unique);
                        view.Name = unique;

                        theDoc.Regenerate();

                        if (showOnlyThisColumn)
                        {
                            try
                            {
                                var keep = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
                                foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
                                {
                                    keep.Add(member);
                                    if (foundationIdOf.ContainsKey(member)) keep.Add(foundationIdOf[member]);
                                    if (beamIdsOf.ContainsKey(member)) keep.AddRange(beamIdsOf[member]);
                                }
                                if (aboveOf.ContainsKey(id)) keep.Add(aboveOf[id]);
                                if (belowOf.ContainsKey(id)) keep.Add(belowOf[id]);
                                keep.AddRange(alwaysVisibleIds);
                                view.IsolateElementsTemporary(keep);
                                view.ConvertTemporaryHideIsolateToPermanent();
                                theDoc.Regenerate();
                            }
                            catch { /* a view template may own the visibility */ }
                        }

                        // Above the crop unless the crop was widened for it, so
                        // the drawing stays the size of the column.
                        Autodesk.Revit.DB.XYZ notePoint = expandCropForNote
                            ? centreOfBox + right * (-halfWidth + inset) + up * (halfHeight - inset)
                            : centreOfBox + right * (-halfWidth) + up * (halfHeight + inset + noteHeight);
                        var noteOptions = new Autodesk.Revit.DB.TextNoteOptions(textType.Id);
                        noteOptions.HorizontalAlignment = Autodesk.Revit.DB.HorizontalTextAlignment.Left;
                        noteOptions.Rotation = 0.0;
                        Autodesk.Revit.DB.TextNote.Create(theDoc, view.Id, notePoint,
                            noteText.ToString(), noteOptions);

                        if (stampTypeCodeInComments)
                        {
                            foreach (Autodesk.Revit.DB.ElementId member in members)
                            {
                                Autodesk.Revit.DB.Parameter comments = instanceOf[member].get_Parameter(
                                    Autodesk.Revit.DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                                if (comments != null && !comments.IsReadOnly) comments.Set(code);
                            }
                        }
                        made++;
                    }
                    catch (System.Exception ex)
                    {
                        failures.Add(code + ": " + ex.Message);
                    }
                }

                transaction.Commit();
            }

            string csvPath = "";
            if (writeCsvToTemp)
            {
                try
                {
                    string title = string.IsNullOrEmpty(theDoc.Title) ? "model" : theDoc.Title;
                    csvPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                        string.Format(inv, "{0}-column-types-{1:yyyyMMdd-HHmmss}.csv", title, System.DateTime.Now));
                    var csv = new System.Text.StringBuilder();
                    csv.AppendLine("Type,Count,Lifts,Family,Type name,Size,Height mm,Foundation,Foundation top mm,"
                        + "Beams,Beam at top,Base mm,Top mm,Base below ground mm,Size below,Size above,Lift sizes,Marks");
                    for (int i = 0; i < keys.Count; i++)
                    {
                        System.Collections.Generic.List<Autodesk.Revit.DB.ElementId> members = membersOf[keys[i]];
                        double[] n = numberOf[members[0]];
                        string[] s = textOf[members[0]];
                        var marks = new System.Text.StringBuilder();
                        foreach (Autodesk.Revit.DB.ElementId member in members)
                        {
                            if (marks.Length > 0) marks.Append(" ");
                            marks.Append(textOf[member][T_MARK]);
                        }
                        var lifts = new System.Text.StringBuilder();
                        if (chainOf.ContainsKey(members[0]))
                        {
                            foreach (Autodesk.Revit.DB.ElementId member in chainOf[members[0]])
                            {
                                if (lifts.Length > 0) lifts.Append(" / ");
                                lifts.Append(sizeTextOf(numberOf[member]));
                            }
                        }
                        csv.AppendFormat(inv,
                            "{0}-{1:00},{2},{3},\"{4}\",\"{5}\",\"{6}\",{7:0},\"{8}\",{9:0},{10:0},{11},{12:0},{13:0},{14:0},\"{15}\",\"{16}\",\"{17}\",\"{18}\"\n",
                            typeCodePrefix, i + 1, members.Count,
                            chainOf.ContainsKey(members[0]) ? chainOf[members[0]].Count : 1,
                            s[T_FAMILY], s[T_TYPE], sizeTextOf(n),
                            n[N_HEIGHT], n[N_HAS_FOUNDATION] > 0.5 ? s[T_FOUNDATION] : "none",
                            n[N_FOUNDATION_TOP], n[N_BEAMS], n[N_BEAM_AT_TOP] > 0.5 ? "yes" : "no",
                            n[N_BASE], n[N_TOP], n[N_BELOW_GROUND],
                            s[T_SIZE_BELOW].Length > 0 ? s[T_SIZE_BELOW] : "none",
                            s[T_SIZE_ABOVE].Length > 0 ? s[T_SIZE_ABOVE] : "none",
                            lifts.ToString(), marks.ToString());
                    }
                    System.IO.File.WriteAllText(csvPath, csv.ToString(), System.Text.Encoding.UTF8);
                }
                catch (System.Exception ex)
                {
                    csvPath = "could not be written: " + ex.Message;
                }
            }

            var done = new Autodesk.Revit.UI.TaskDialog("Column sections");
            done.MainInstruction = string.Format(inv, "{0} section{1} created.", made, made == 1 ? "" : "s");
            done.MainContent = (failures.Count == 0
                    ? "They are in the project browser under Sections."
                    : string.Format(inv, "{0} could not be created:\n{1}", failures.Count,
                        string.Join("\n", failures.ToArray())))
                + (csvPath.Length > 0 ? "\n\nCSV: " + csvPath : "");
            done.ExpandedContent = summary.ToString();
            done.Show();
        }
    }
}

// If your tool complains that not all code paths return a value, put the line
// it wants here - usually one of these:
// return Autodesk.Revit.UI.Result.Succeeded;
// return true;
