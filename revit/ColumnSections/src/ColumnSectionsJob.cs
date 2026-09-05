using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
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
                    Subjects(groups), Subjects(groups) == 1 ? "" : "s",
                    groups.Count, groups.Count == 1 ? "" : "s"),
                MainContent = string.Format(
                    "Read from {0}, {1} columns in all. Ground is taken from level \"{2}\".\n\n{3}" +
                    "A type is a size, a foundation below, a beam connection, a level " +
                    "against ground, and what the stack does above and below it. One " +
                    "cross section will be created for each, with a note in it saying " +
                    "how many columns share that type.",
                    fromSelection ? "your selection" : "the whole model",
                    columns.Count, scanner.GroundLevelName,
                    settings.OneSectionPerStack
                        ? "A column standing on another is one column here, not two: the section "
                          + "is taken on the one that starts at the foundation and covers every "
                          + "lift above it.\n\n"
                        : ""),
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

        /// <summary>How many columns the sections are of, once a stack counts once.</summary>
        private static int Subjects(List<ColumnTypeGroup> groups)
        {
            int total = 0;
            foreach (ColumnTypeGroup g in groups) total += g.Count;
            return total;
        }

        /// <summary>One line per type, for the dialogs.</summary>
        public static string Summary(List<ColumnTypeGroup> groups)
        {
            var text = new StringBuilder();
            foreach (ColumnTypeGroup g in groups)
            {
                text.AppendFormat("{0}  {8}x{1}  {2}  |  {3}  |  {4}  |  {5}  |  {6} lift(s): {7}\n",
                    g.Code, g.Count, g.Signature.SizeText, g.Signature.FoundationText,
                    g.Signature.BeamText + ", " + g.Signature.FloorText, g.Signature.GroundText,
                    g.Representative.Lifts.Count,
                    string.Join(" / ", g.Signature.LiftSizes.Length > 0
                        ? g.Signature.LiftSizes
                        : new[] { g.Signature.SizeText }),
                    g.Signature.Tag.Length > 0 ? "[" + g.Signature.Tag + "]  " : "");
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
            text.AppendLine("Type,Tag,Count,Family,Type name,Size,Height mm,Foundation,Foundation top mm," +
                            "Foundation thickness mm,Beams,Beam at top,Floors,Slab at top,Slab thickness mm," +
                            "Base level,Top level,Base mm,Top mm," +
                            "Base below ground mm,Lifts,Lift sizes,Stack position,Marks");
            foreach (ColumnTypeGroup g in groups)
            {
                ColumnSignature s = g.Signature;
                var marks = new List<string>();
                foreach (ColumnInfo m in g.Members) marks.Add(m.Mark);
                text.AppendFormat(c,
                    "{0},{1},{2},{3},{4},{5},{6:0},{7},{8:0},{9:0},{10},{11},{12},{13},{14:0}," +
                    "{15},{16},{17:0},{18:0},{19:0},{20},{21},{22},{23}\n",
                    Csv(g.Code), Csv(s.Tag), g.Count, Csv(s.FamilyName), Csv(s.TypeName), Csv(s.SizeText),
                    s.HeightMm, s.HasFoundation ? Csv(s.FoundationTypeName) : "none",
                    s.FoundationTopMm, s.FoundationThicknessMm, s.BeamCount, s.BeamAtTop ? "yes" : "no",
                    s.FloorCount, s.FloorAtTop ? "yes" : "no", s.FloorThicknessMm,
                    Csv(s.BaseLevelName), Csv(s.TopLevelName),
                    s.BaseElevationMm, s.TopElevationMm, s.BaseBelowGroundMm,
                    g.Representative.Lifts.Count,
                    Csv(string.Join(" / ", s.LiftSizes.Length > 0 ? s.LiftSizes : new[] { s.SizeText })),
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
