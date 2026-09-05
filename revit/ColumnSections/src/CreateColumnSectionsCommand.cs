using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    /// <summary>
    /// Sorts the columns into types — by size, by the foundation under them, by
    /// whether a beam frames in, and by where they sit against ground level — then
    /// cuts one cross section per type and notes in it how many columns it stands for.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class CreateColumnSectionsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            if (uidoc == null || uidoc.Document == null)
            {
                message = "Open a project first.";
                return Result.Failed;
            }
            Document doc = uidoc.Document;
            if (doc.IsFamilyDocument)
            {
                message = "Run this in a project, not in the family editor.";
                return Result.Failed;
            }

            Settings settings = Settings.Default;

            List<FamilyInstance> columns = Selected(uidoc);
            bool fromSelection = columns.Count > 0;
            if (!fromSelection) columns = ColumnScanner.AllColumns(doc);
            if (columns.Count == 0)
            {
                TaskDialog.Show("Column sections", "No columns found in this model.");
                return Result.Cancelled;
            }

            var scanner = new ColumnScanner(doc, settings);
            List<ColumnTypeGroup> groups = scanner.Scan(columns);
            if (groups.Count == 0)
            {
                TaskDialog.Show("Column sections", "None of the columns could be measured.");
                return Result.Cancelled;
            }

            var factory = new SectionFactory(doc, settings);
            string problem;
            if (!factory.Prepare(out problem))
            {
                message = problem;
                return Result.Failed;
            }

            var ask = new TaskDialog("Column sections")
            {
                MainInstruction = string.Format("{0} column{1} in {2} type{3}.",
                    columns.Count, columns.Count == 1 ? "" : "s",
                    groups.Count, groups.Count == 1 ? "" : "s"),
                MainContent = string.Format(
                    "Read from {0}. Ground is taken from level \"{1}\".\n\n" +
                    "One cross section will be created for each type, with a note in it " +
                    "saying how many columns share that type.",
                    fromSelection ? "your selection" : "the whole model",
                    scanner.GroundLevelName),
                ExpandedContent = Summary(groups),
                CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
                DefaultButton = TaskDialogResult.Yes
            };
            if (ask.Show() != TaskDialogResult.Yes) return Result.Cancelled;

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

            var done = new TaskDialog("Column sections")
            {
                MainInstruction = string.Format("{0} section{1} created.",
                    groups.Count - failed.Count, groups.Count - failed.Count == 1 ? "" : "s"),
                MainContent = failed.Count == 0
                    ? "They are in the project browser under Sections."
                    : string.Format("{0} could not be created:\n{1}",
                        failed.Count, string.Join("\n", failed)),
                ExpandedContent = Summary(groups)
            };
            done.Show();
            return Result.Succeeded;
        }

        private static List<FamilyInstance> Selected(UIDocument uidoc)
        {
            Document doc = uidoc.Document;
            var columns = new List<FamilyInstance>();
            var wanted = new List<ElementId>();
            foreach (BuiltInCategory bic in new[]
                { BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Columns })
            {
                Category category = Category.GetCategory(doc, bic);
                if (category != null) wanted.Add(category.Id);
            }

            foreach (ElementId id in uidoc.Selection.GetElementIds())
            {
                var instance = doc.GetElement(id) as FamilyInstance;
                if (instance == null || instance.Category == null) continue;
                if (wanted.Any(w => w == instance.Category.Id)) columns.Add(instance);
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

        internal static string Summary(IEnumerable<ColumnTypeGroup> groups)
        {
            var text = new StringBuilder();
            foreach (ColumnTypeGroup g in groups)
            {
                text.AppendFormat("{0}  x{1}  {2}  |  {3}  |  {4}  |  {5}\n",
                    g.Code, g.Count, g.Signature.SizeText, g.Signature.FoundationText,
                    g.Signature.BeamText, g.Signature.GroundText);
            }
            return text.ToString();
        }
    }
}
