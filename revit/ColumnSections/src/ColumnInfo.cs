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
        /// <summary>The foundation under it, and the beams framing into it: what the
        /// section keeps when everything else is hidden.</summary>
        public ElementId FoundationId;
        public readonly List<ElementId> BeamIds = new List<ElementId>();
        /// <summary>The columns sharing this plan location, one storey up and one down.</summary>
        public ColumnInfo Above;
        public ColumnInfo Below;

        /// <summary>On the column a section is taken of: every lift of its stack,
        /// bottom first, itself included. Empty on the lifts above.</summary>
        public readonly List<ColumnInfo> Lifts = new List<ColumnInfo>();
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
}
