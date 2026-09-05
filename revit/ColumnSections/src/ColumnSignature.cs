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
        /// <summary>The tag written on the column, from the settings' parameter.</summary>
        public string Tag = "";

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

        // The slabs it meets
        public int FloorCount;
        public bool FloorAtTop;
        public double FloorThicknessMm;

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

        /// <summary>The sizes of the stack this column starts, bottom first, once
        /// the key is built. Empty when it is not the bottom of one.</summary>
        public string[] LiftSizes = new string[0];

        /// <summary>Freezes the signature: rounds every measurement to the
        /// tolerances in <paramref name="s"/> and builds the comparison key.
        /// <paramref name="lifts"/> is the stack standing on this column.</summary>
        public void Build(Settings s, System.Collections.Generic.List<ColumnInfo> lifts)
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

            FloorThicknessMm = Units.Snap(FloorThicknessMm, s.LevelToleranceMm);

            var k = new StringBuilder();
            var c = CultureInfo.InvariantCulture;

            // Every part that reads down the stack works off this: the lifts
            // standing on the column, or the column alone where there are none.
            var run = lifts != null && lifts.Count > 0
                ? lifts
                : new System.Collections.Generic.List<ColumnInfo>();

            // The tag first: whatever else two columns share, a different tag
            // makes them different columns.
            if (s.TagIsPartOfType)
            {
                k.Append("T:").Append(Tag);
                foreach (ColumnInfo lift in run) k.Append(';').Append(lift.Signature.Tag);
                k.Append('|');
            }

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

            // The slabs, and the levels each lift runs between.
            if (s.FloorsArePartOfType)
            {
                k.Append("D:").AppendFormat(c, "{0}:{1}:{2:0}", FloorCount, FloorAtTop ? 1 : 0, FloorThicknessMm);
                foreach (ColumnInfo lift in run)
                {
                    ColumnSignature g = lift.Signature;
                    k.AppendFormat(c, ";{0}:{1}:{2:0}", g.FloorCount, g.FloorAtTop ? 1 : 0, g.FloorThicknessMm);
                }
                k.Append('|');
            }
            if (s.LevelNamesArePartOfType)
            {
                k.Append("V:").Append(BaseLevelName).Append('>').Append(TopLevelName);
                foreach (ColumnInfo lift in run)
                    k.Append(';').Append(lift.Signature.BaseLevelName)
                     .Append('>').Append(lift.Signature.TopLevelName);
                k.Append('|');
            }

            k.Append(string.Format(c, "G:{0:0}", BaseBelowGroundMm));

            if (s.StackChangeIsPartOfType)
            {
                k.Append('|');
                if (s.OneSectionPerStack && lifts != null && lifts.Count > 0)
                {
                    // Every lift of the stack, in order: two stacks are the same
                    // only if they change size at the same places.
                    var sizes = new string[lifts.Count];
                    k.Append("L:");
                    for (int i = 0; i < lifts.Count; i++)
                    {
                        sizes[i] = lifts[i].Signature.SizeText;
                        k.Append(sizes[i]);
                        if (s.HeightIsPartOfType)
                            k.AppendFormat(c, "@{0:0}", lifts[i].Signature.HeightMm);
                        k.Append(';');
                    }
                    LiftSizes = sizes;
                }
                else
                {
                    k.Append("A:").Append(HasColumnAbove ? SizeAboveText : "none").Append('|');
                    k.Append("U:").Append(HasColumnBelow ? SizeBelowText : "none");
                }
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

        public string FloorText
        {
            get
            {
                var c = CultureInfo.InvariantCulture;
                if (FloorAtTop)
                    return string.Format(c, "SLAB AT TOP ({0:0} THK), {1} FLOOR{2} IN ALL",
                        FloorThicknessMm, FloorCount, FloorCount == 1 ? "" : "S");
                if (FloorCount == 0) return "NO FLOOR MET";
                return string.Format(c, "{0} FLOOR{1} MET, NONE AT TOP",
                    FloorCount, FloorCount == 1 ? "" : "S");
            }
        }

        public string LevelText
        {
            get
            {
                if (BaseLevelName.Length == 0 && TopLevelName.Length == 0) return "LEVELS: NOT SET";
                return "LEVELS: " + (BaseLevelName.Length > 0 ? BaseLevelName : "?")
                    + " TO " + (TopLevelName.Length > 0 ? TopLevelName : "?");
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

        /// <summary>The criteria, one per line, for the note in the section. Where
        /// the lifts are listed above it, what is above and below is already said
        /// and is left out.</summary>
        public string[] DescriptionLines(bool liftsAreListed)
        {
            var c = CultureInfo.InvariantCulture;
            var lines = new System.Collections.Generic.List<string>();
            if (Tag.Length > 0) lines.Add("TAG: " + Tag);
            if (!liftsAreListed) lines.Add("SIZE: " + SizeText + "  (" + TypeName + ")");
            lines.Add(FoundationText);
            lines.Add(BeamText);
            lines.Add(FloorText);
            lines.Add(LevelText);
            lines.Add(GroundText);
            if (!liftsAreListed)
            {
                lines.Add(BelowText);
                lines.Add(AboveText);
                lines.Add(string.Format(c, "BASE {0:0} / TOP {1:0} / HT {2:0}",
                    BaseElevationMm, TopElevationMm, HeightMm));
            }
            return lines.ToArray();
        }
    }
}
