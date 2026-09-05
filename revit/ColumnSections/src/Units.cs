using Autodesk.Revit.DB;

namespace ColumnSections
{
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
}
