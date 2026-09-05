using System.Collections.Generic;
using Autodesk.Revit.DB;

namespace ColumnSections
{
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
        public ColumnSignature Signature;
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
}
