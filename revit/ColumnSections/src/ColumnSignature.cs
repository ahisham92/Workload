using System;
using System.Globalization;
using System.Text;

namespace ColumnSections
{
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

        /// <summary>The four criteria, one per line, for the note in the section.</summary>
        public string[] DescriptionLines()
        {
            var c = CultureInfo.InvariantCulture;
            return new[]
            {
                "SIZE: " + SizeText + "  (" + TypeName + ")",
                FoundationText,
                BeamText,
                GroundText,
                string.Format(c, "BASE {0:0} / TOP {1:0} / HT {2:0}",
                    BaseElevationMm, TopElevationMm, HeightMm)
            };
        }
    }
}
