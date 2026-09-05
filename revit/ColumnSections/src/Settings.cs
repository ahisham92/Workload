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

        /// <summary>Empty space left around the column in the section.</summary>
        public double SideClearanceMm = 600.0;
        public double TopClearanceMm = 900.0;
        public double BottomClearanceMm = 600.0;

        /// <summary>How deep the section looks past the column.</summary>
        public double ViewDepthClearanceMm = 900.0;

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
