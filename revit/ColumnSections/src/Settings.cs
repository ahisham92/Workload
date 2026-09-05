using Autodesk.Revit.DB;

namespace ColumnSections
{
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
}
