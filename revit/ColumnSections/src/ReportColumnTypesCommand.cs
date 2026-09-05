using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    /// <summary>
    /// The same sorting, without touching the model: says how many types there are
    /// and writes them to a CSV, so the tolerances can be checked before sections
    /// are cut.
    /// </summary>
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public class ReportColumnTypesCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            if (uidoc == null || uidoc.Document == null || uidoc.Document.IsFamilyDocument)
            {
                message = "Open a project first.";
                return Result.Failed;
            }
            Document doc = uidoc.Document;

            List<FamilyInstance> columns = ColumnScanner.AllColumns(doc);
            if (columns.Count == 0)
            {
                TaskDialog.Show("Column types", "No columns found in this model.");
                return Result.Cancelled;
            }

            var scanner = new ColumnScanner(doc, Settings.Default);
            List<ColumnTypeGroup> groups = scanner.Scan(columns);

            string path = null;
            try { path = WriteCsv(doc, groups); }
            catch (Exception ex) { path = "could not be written: " + ex.Message; }

            var dialog = new TaskDialog("Column types")
            {
                MainInstruction = string.Format("{0} columns in {1} types.",
                    columns.Count, groups.Count),
                MainContent = string.Format("Ground is taken from level \"{0}\".\n\nCSV: {1}",
                    scanner.GroundLevelName, path),
                ExpandedContent = CreateColumnSectionsCommand.Summary(groups)
            };
            dialog.Show();
            return Result.Succeeded;
        }

        private static string WriteCsv(Document doc, List<ColumnTypeGroup> groups)
        {
            string name = string.IsNullOrEmpty(doc.Title) ? "model" : doc.Title;
            string path = Path.Combine(Path.GetTempPath(),
                string.Format("{0}-column-types-{1:yyyyMMdd-HHmmss}.csv", name, DateTime.Now));

            var c = CultureInfo.InvariantCulture;
            var text = new StringBuilder();
            text.AppendLine("Type,Count,Family,Type name,Size,Height mm,Foundation,Foundation top mm," +
                            "Foundation thickness mm,Beams,Beam at top,Base level,Base mm,Top mm," +
                            "Base below ground mm,Marks");
            foreach (ColumnTypeGroup g in groups)
            {
                ColumnSignature s = g.Signature;
                var marks = new List<string>();
                foreach (ColumnInfo m in g.Members) marks.Add(m.Mark);
                text.AppendFormat(c,
                    "{0},{1},{2},{3},{4},{5:0},{6},{7:0},{8:0},{9},{10},{11},{12:0},{13:0},{14:0},{15}\n",
                    Csv(g.Code), g.Count, Csv(s.FamilyName), Csv(s.TypeName), Csv(s.SizeText),
                    s.HeightMm, s.HasFoundation ? Csv(s.FoundationTypeName) : "none",
                    s.FoundationTopMm, s.FoundationThicknessMm, s.BeamCount, s.BeamAtTop ? "yes" : "no",
                    Csv(s.BaseLevelName), s.BaseElevationMm, s.TopElevationMm, s.BaseBelowGroundMm,
                    Csv(string.Join(" ", marks)));
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
