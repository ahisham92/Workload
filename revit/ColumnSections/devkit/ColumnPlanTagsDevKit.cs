// ===========================================================================
//  COLUMN PLAN TAGS - a script of its own, for DevKit
//  Revit 2021 and later.  GENERATED - do not edit; see tools/build_macro.py.
// ---------------------------------------------------------------------------
//  Run it with a PLAN OPEN. Beside every column the plan cuts it puts:
//
//      ( 01-C02 )        [column]     01-C 02
//      (   01   )                     (600x800)
//
//  On the right, the column's tag and its size. On the left, a bubble with a
//  leader to the column: the tag above the line, and below it the number of the
//  detail the column is drawn on - read off the section views themselves where
//  they exist, so the two agree, and off the type's own number where they do
//  not.
//
//  It knows the tags, the sizes and the types because the middle of this file
//  is the sections script's own code. It does not clear anything: a column
//  something is already written beside is left alone.
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
// Rounded before anything is compared, so a millimetre out is not a new type.
double sizeToleranceMm = 5.0;
double levelToleranceMm = 10.0;

// The tag you have written on each column. Read from this instance parameter;
// change the name if your tag lives somewhere else - "Mark", or a shared
// parameter. Columns with different tags are always different types.
string tagParameterName = "Comments";
bool tagIsPartOfType = true;

// What counts as a different type.
bool floorsArePartOfType = true;      // the slabs the column meets
bool levelNamesArePartOfType = true;  // which levels it runs between
bool familyNameIsPartOfType = true;   // false: size alone, whatever the family
bool heightIsPartOfType = true;       // false: storey height stops mattering
bool countBeamsSeparately = true;     // false: only connected / not connected
bool stackChangeIsPartOfType = true;  // false: what is above and below stops counting

// How far out something still belongs to this column.
double foundationSearchToleranceMm = 250.0;
double beamSearchToleranceMm = 200.0;    // past the column face, in plan
double beamVerticalToleranceMm = 900.0;  // above the top, for a beam sitting on it
double floorSearchToleranceMm = 600.0;   // above the top, for a slab landing on it
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

// The section is cut through the MIDDLE of the column, and this is all it sees
// behind that plane. 50mm: what the plane cuts, and next to nothing else.
double farClipOffsetMm = 50.0;

// Grids are hidden in every section made.
bool hideGridsInSections = true;

// Break lines where a floor, a beam or a foundation runs out of the view, at the
// edge it leaves by. These are drawn in detail lines; ColumnBreakLinesDevKit
// places your own break line family instead, which is why this is off. Sizes
// are ON PAPER.
bool drawBreakLines = false;
double breakLineKinkMm = 3.0;
double breakLineWidthMm = 2.0;
double breakLineInsetMm = 2.0;

// Used by the break line script: the detail item family it places, the type of
// it, and how far round to turn each one - the family is drawn across the page,
// and a member leaving by a side edge is broken by a line up it. Empty type
// name: the first type of the family. It also looks for a length parameter to
// set to the thickness of what is being broken.
string breakFamilyName = "DT_BreakLine";
string breakTypeName = "BreakLine";
double breakLineRotationDegrees = 90.0;
bool replaceExistingBreakLines = true;
string[] breakLengthParameterNames = new string[]
    { "Length", "L", "Break Length", "Width", "Size" };

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

// The table on each section: column type, how many there are, where each one
// stands against the grid, and the detail number. Drawn as the section is made,
// so one run does the lot. ColumnTableDevKit draws the same table on sections
// that already exist. Sizes are ON PAPER.
bool drawTable = true;
bool keepTextNoteAsWell = false;   // true: the written note is placed too
double tableLabelWidthMm = 32.0;
double tableValueWidthMm = 64.0;
double tableRowHeightMm = 7.0;
int maxLocationRows = 12;

// A column is ON the axis within this of the grid line, and NEAR it beyond.
double onAxisToleranceMm = 100.0;

// Work on the columns you have selected, where any are. The table script sets
// this false: it counts the whole model however you leave it here.
bool useSelectionWhenAny = false;   // the plan tags always reads the whole model

// Used by the plan script: the tag put beside each column on a plan - its name
// and size on the right, and on the left the bubble with the detail number of
// the section that column is drawn on. Sizes are ON PAPER.
double planCutOffsetMm = 1200.0;      // how far above its level the plan cuts
double planLabelOffsetMm = 8.0;       // right of the column
double planBubbleOffsetMm = 18.0;     // left of the column - the leader spans it
double planBubbleRadiusXMm = 9.0;
double planBubbleRadiusYMm = 5.5;
double planArrowMm = 2.5;
string planSizeFormat = "({0})";
bool skipWhereAlreadyTagged = true;   // leave columns something is written by

// Used by the title script: the box drawn under each section. {0} is the tag on
// the first line, the detail number on the second and on the right of the third,
// and the view's scale in the middle of it. Sizes are ON PAPER.
string titleLine1Format = "{0} COLUMNS RFT.";
string titleLine2Format = "SEC. ELEVATION {0}-{0}";
string titleScaleFormat = "SCALE   1:{0}";
string titleDetailFormat = "DETAIL {0}";
double titleRowHeightMm = 7.0;
double titleMarginMm = 4.0;
double titleInnerInsetMm = 1.5;
double titleGapBelowMm = 8.0;
bool underlineSecondLine = true;
bool growCropForTitle = true;
bool replaceExistingTitle = true;

// Used by the table script only: which sections it draws on, how far above the
// crop the table hangs, and whether it clears what it drew before.
bool onlyTheActiveView = true;    // the plan you have open
string viewNameContains = "COL SECTION";
bool clearExistingAnnotation = true;
double tableGapAboveViewMm = 4.0;

// How far from a section's own origin the column it was cut on may be before
// the table script gives up on it and reads the view's name instead.
double matchToleranceMm = 2000.0;

// The crop region cuts detail lines - text it leaves alone - so a table drawn
// above the crop comes out as words with no box around them. This grows the
// crop to take the table in. The table is hung off the top of the column, not
// off the crop, so running the script again puts it in the same place.
bool expandCropToFitTable = true;

// Sections made by an older run of the sections script carry the count of that
// run in their names. True renames them to what the criteria give now.
bool renameSectionsToMatch = false;

// The left location cell names the grid running parallel to Y, the right one
// the grid running parallel to X. True swaps the two columns over.
bool swapAxisColumns = false;
string viewNamePrefix = "COL SECTION";
string typeCodePrefix = "CT";
int maxMarksInNote = 12;

// Leave this off now that Comments holds your tags: it would write over them.
bool stampTypeCodeInComments = false;
bool writeCsvToTemp = true;

// Section size parameters looked for, in order, before the solid is measured.
string[] widthParameterNames = new string[] { "b", "Width", "Depth 1", "bf" };
string[] depthParameterNames = new string[] { "h", "Depth", "Height", "d" };
string[] diameterParameterNames = new string[] { "Diameter", "D", "d" };

// it groups the columns by exactly what the sections were made from
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
const int N_FLOORS = 15;
const int N_FLOOR_AT_TOP = 16;
const int N_FLOOR_THICKNESS = 17;
const int NUMBER_SLOTS = 18;

// Slots in the text row. An empty string means there is none.
const int T_FAMILY = 0;
const int T_TYPE = 1;
const int T_FOUNDATION = 2;
const int T_MARK = 3;
const int T_BASE_LEVEL = 4;
const int T_SIZE_ABOVE = 5;
const int T_SIZE_BELOW = 6;
const int T_TAG = 7;
const int T_TOP_LEVEL = 8;
const int T_LOCATION_Y = 9;
const int T_LOCATION_X = 10;
const int TEXT_SLOTS = 11;

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
var floorIdsOf = new System.Collections.Generic.Dictionary<Autodesk.Revit.DB.ElementId,
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
if (useSelectionWhenAny)
{
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

    // Floors, as footprints: a column meets the slab that covers it.
    var floorBoxes = new System.Collections.Generic.List<Autodesk.Revit.DB.BoundingBoxXYZ>();
    var floorIds = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
    foreach (Autodesk.Revit.DB.Element e in new Autodesk.Revit.DB.FilteredElementCollector(theDoc)
        .OfCategory(Autodesk.Revit.DB.BuiltInCategory.OST_Floors)
        .WhereElementIsNotElementType())
    {
        Autodesk.Revit.DB.BoundingBoxXYZ bb = e.get_BoundingBox(null);
        if (bb == null) continue;
        floorBoxes.Add(bb);
        floorIds.Add(e.Id);
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

    // The grids, so each column can be placed against them.
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
                s[T_TOP_LEVEL] = level.Name;
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

        // The tag written on the column. Named parameter first, Comments after.
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
        s[T_TAG] = tag;
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

        // The slabs it meets: any floor whose footprint covers the column and
        // whose thickness falls within its height, and whether one lands on top.
        double floorReach = toFeet(floorSearchToleranceMm);
        int floors = 0;
        bool floorAtTop = false;
        double floorThickness = 0.0;
        var metFloors = new System.Collections.Generic.List<Autodesk.Revit.DB.ElementId>();
        for (int fi = 0; fi < floorBoxes.Count; fi++)
        {
            Autodesk.Revit.DB.BoundingBoxXYZ bb = floorBoxes[fi];
            if (basePoint.X < bb.Min.X || basePoint.X > bb.Max.X) continue;
            if (basePoint.Y < bb.Min.Y || basePoint.Y > bb.Max.Y) continue;
            if (bb.Max.Z < baseZ - floorReach || bb.Min.Z > topZ + floorReach) continue;
            floors++;
            metFloors.Add(floorIds[fi]);
            if (bb.Max.Z > topZ - floorReach && bb.Min.Z < topZ + floorReach)
            {
                floorAtTop = true;
                floorThickness = toMm(bb.Max.Z - bb.Min.Z);
            }
        }
        // Where it stands against the grid: the nearest grid running parallel to
        // Y, and the nearest running parallel to X, and whether it is on the line
        // or only near it.
        double onAxis = toFeet(onAxisToleranceMm);
        string nearestY = "", nearestX = "";
        double bestY = double.MaxValue, bestX = double.MaxValue;
        for (int i = 0; i < gridNames.Count; i++)
        {
            Autodesk.Revit.DB.XYZ a = gridStarts[i], dir = gridDirections[i];
            // Perpendicular distance in plan from the column to the grid line.
            double vx = basePoint.X - a.X, vy = basePoint.Y - a.Y;
            double distance = System.Math.Abs(vx * dir.Y - vy * dir.X);
            bool runsAlongY = System.Math.Abs(dir.Y) >= System.Math.Abs(dir.X);

            if (runsAlongY)
            {
                if (distance < bestY)
                {
                    bestY = distance;
                    nearestY = string.Format(inv, "{0}( {1} )",
                        distance <= onAxis ? "ON.AXIS" : "NEAR.AXIS.", gridNames[i]);
                }
            }
            else if (distance < bestX)
            {
                bestX = distance;
                nearestX = string.Format(inv, "{0}( {1} )",
                    distance <= onAxis ? "ON.AXIS" : "NEAR.AXIS.", gridNames[i]);
            }
        }
        s[T_LOCATION_Y] = swapAxisColumns ? nearestX : nearestY;
        s[T_LOCATION_X] = swapAxisColumns ? nearestY : nearestX;

        n[N_FLOORS] = floors;
        n[N_FLOOR_AT_TOP] = floorAtTop ? 1 : 0;
        n[N_FLOOR_THICKNESS] = snap(floorThickness, levelToleranceMm);
        floorIdsOf[column.Id] = metFloors;

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

        // The tag first: whatever else two columns share, a different tag makes
        // them different columns. Where a stack is tagged lift by lift, the
        // whole run of tags counts.
        if (tagIsPartOfType)
        {
            key.Append("T:");
            foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
                key.Append(textOf[member][T_TAG]).Append(';');
            key.Append('|');
        }

        if (familyNameIsPartOfType) key.Append(s[T_FAMILY]).Append('|').Append(s[T_TYPE]).Append('|');
        key.Append(sizeTextOf(n)).Append('|');
        if (heightIsPartOfType) key.AppendFormat(inv, "H{0:0}|", n[N_HEIGHT]);
        key.Append(n[N_HAS_FOUNDATION] > 0.5
            ? string.Format(inv, "F:{0}:{1:0}:{2:0}", s[T_FOUNDATION], n[N_FOUNDATION_TOP], n[N_FOUNDATION_THICKNESS])
            : "F:none").Append('|');
        key.Append(countBeamsSeparately
            ? string.Format(inv, "B:{0:0}:{1:0}", n[N_BEAMS], n[N_BEAM_AT_TOP])
            : string.Format(inv, "B:{0}", n[N_BEAMS] > 0.5 ? 1 : 0)).Append('|');

        // The slabs, and the levels each lift runs between.
        if (floorsArePartOfType)
        {
            key.Append("D:");
            foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
            {
                double[] mn = numberOf[member];
                key.AppendFormat(inv, "{0:0}:{1:0}:{2:0};",
                    mn[N_FLOORS], mn[N_FLOOR_AT_TOP], mn[N_FLOOR_THICKNESS]);
            }
            key.Append('|');
        }
        if (levelNamesArePartOfType)
        {
            key.Append("V:");
            foreach (Autodesk.Revit.DB.ElementId member in chainOf[id])
                key.Append(textOf[member][T_BASE_LEVEL]).Append('>')
                   .Append(textOf[member][T_TOP_LEVEL]).Append(';');
            key.Append('|');
        }
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

    // Which type each column belongs to, whichever lift of its stack it is:
    // the table script looks a column up this way.
    var subjectOf = new System.Collections.Generic.Dictionary<
        Autodesk.Revit.DB.ElementId, Autodesk.Revit.DB.ElementId>();
    var keyOfSubject = new System.Collections.Generic.Dictionary<
        Autodesk.Revit.DB.ElementId, string>();
    foreach (string key in keys)
    {
        foreach (Autodesk.Revit.DB.ElementId subject in membersOf[key])
        {
            keyOfSubject[subject] = key;
            foreach (Autodesk.Revit.DB.ElementId member in chainOf[subject])
                subjectOf[member] = subject;
        }
    }

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

                    // Which height a detail line has to be drawn at to count as
                    // being in this plan's plane. Revit refuses the wrong one, so
                    // the candidates are tried on a line that is thrown away.
                    var candidateHeights = new System.Collections.Generic.List<double>();
                    try
                    {
                        // The view's own answer, where it has one.
                        if (plan.SketchPlane != null && plan.SketchPlane.GetPlane() != null)
                            candidateHeights.Add(plan.SketchPlane.GetPlane().Origin.Z);
                    }
                    catch { /* the view has no sketch plane of its own */ }
                    if (plan.Origin != null) candidateHeights.Add(plan.Origin.Z);
                    candidateHeights.Add(plan.GenLevel.Elevation);
                    candidateHeights.Add(plan.GenLevel.ProjectElevation);
                    candidateHeights.Add(plan.GenLevel.Elevation + toFeet(planCutOffsetMm));
                    candidateHeights.Add(0.0);

                    double planZ = candidateHeights[0];
                    bool planeFound = false;
                    foreach (double height in candidateHeights)
                    {
                        try
                        {
                            Autodesk.Revit.DB.DetailCurve probe = theDoc.Create.NewDetailCurve(plan,
                                Autodesk.Revit.DB.Line.CreateBound(
                                    new Autodesk.Revit.DB.XYZ(0, 0, height),
                                    new Autodesk.Revit.DB.XYZ(toFeet(1000.0), 0, height)));
                            theDoc.Delete(probe.Id);
                            planZ = height;
                            planeFound = true;
                            break;
                        }
                        catch { /* not this plane; try the next */ }
                    }
                    if (!planeFound)
                    {
                        skipped.Add(plan.Name + ": no line can be drawn in this view at all - "
                            + "a view template may be holding it");
                        continue;
                    }

                    // Whatever the probe settled on, every line goes down at this
                    // height, and if Revit still refuses one the rest of the
                    // candidates are tried on it rather than losing the drawing.
                    double[] drawAt = new double[] { planZ };
                    int[] refusedStrokes = new int[] { 0 };

                    // One line of the drawing, put down at whichever height this
                    // view will take. Revit is the judge, not us.
                    System.Action<Autodesk.Revit.DB.XYZ, Autodesk.Revit.DB.XYZ> stroke = (a, b) =>
                    {
                        if (a.DistanceTo(b) < 1e-7) return;
                        var tryThese = new System.Collections.Generic.List<double>();
                        tryThese.Add(drawAt[0]);
                        tryThese.AddRange(candidateHeights);
                        foreach (double height in tryThese)
                        {
                            try
                            {
                                theDoc.Create.NewDetailCurve(plan,
                                    Autodesk.Revit.DB.Line.CreateBound(
                                        new Autodesk.Revit.DB.XYZ(a.X, a.Y, height),
                                        new Autodesk.Revit.DB.XYZ(b.X, b.Y, height)));
                                drawAt[0] = height;
                                return;
                            }
                            catch { /* not this plane; try the next */ }
                        }
                        refusedStrokes[0]++;
                    };
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
                    string firstComplaint = null;
                    int refused = 0;
                    foreach (Autodesk.Revit.DB.ElementId id in ids)
                    {
                      try
                      {
                        double[] n = numberOf[id];
                        // Only the columns this plan cuts.
                        if (cutAt < n[N_BASE_Z_FT] - 1e-6 || cutAt > n[N_TOP_Z_FT] + 1e-6) continue;

                        Autodesk.Revit.DB.XYZ stands = basePointOf[id];
                        Autodesk.Revit.DB.XYZ point = new Autodesk.Revit.DB.XYZ(
                            stands.X, stands.Y, drawAt[0]);

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
                            stroke(centre + right * -radiusX + up * radiusY,
                                   centre + right * radiusX + up * radiusY);
                            stroke(centre + right * -radiusX - up * radiusY,
                                   centre + right * radiusX - up * radiusY);
                            stroke(centre + right * -radiusX - up * radiusY,
                                   centre + right * -radiusX + up * radiusY);
                            stroke(centre + right * radiusX - up * radiusY,
                                   centre + right * radiusX + up * radiusY);
                        }

                        stroke(centre - right * radiusX, centre + right * radiusX);
                        write(plan, tag, centre + up * (textHeight + textHeight / 4.0),
                            Autodesk.Revit.DB.HorizontalTextAlignment.Center);
                        write(plan, detail, centre - up * (textHeight / 4.0),
                            Autodesk.Revit.DB.HorizontalTextAlignment.Center);

                        // The leader, from the bubble to the face of the column.
                        double halfSide = toFeet(System.Math.Max(n[N_WIDTH], n[N_DEPTH])) / 2.0;
                        Autodesk.Revit.DB.XYZ tip = point - right * halfSide;
                        Autodesk.Revit.DB.XYZ from = centre + right * radiusX;
                        stroke(from, tip);

                        // Its head: two strokes back along the leader.
                        Autodesk.Revit.DB.XYZ along = (tip - from);
                        if (along.GetLength() > 1e-9)
                        {
                            along = along.Normalize();
                            Autodesk.Revit.DB.XYZ across = up.CrossProduct(along).Normalize();
                            stroke(tip, tip - along * arrow + across * (arrow / 3.0));
                            stroke(tip, tip - along * arrow - across * (arrow / 3.0));
                        }

                        taggedCount++;
                        onThisPlan++;
                      }
                      catch (System.Exception ex)
                      {
                        refused++;
                        if (firstComplaint == null) firstComplaint = ex.Message;
                      }
                    }

                    if (refusedStrokes[0] > 0)
                        skipped.Add(string.Format(inv,
                            "{0}: {1} line{2} refused by the view; the words are there without them",
                            plan.Name, refusedStrokes[0], refusedStrokes[0] == 1 ? "" : "s"));

                    tagged.Add(string.Format(inv, "{0}  ->  {1} column{2}{3}",
                        plan.Name, onThisPlan, onThisPlan == 1 ? "" : "s",
                        refused == 0 ? "" : string.Format(inv, ", {0} refused: {1}",
                            refused, firstComplaint)));
                    if (refused > 0)
                        skipped.Add(string.Format(inv, "{0}: {1} column{2} refused - {3}",
                            plan.Name, refused, refused == 1 ? "" : "s", firstComplaint));
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
            "{0} left alone, having something written beside them already. "
            + "Nothing tagged at all usually means the plan does not cut any column: "
            + "planCutOffsetMm is how far above the level it cuts.{1}",
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
