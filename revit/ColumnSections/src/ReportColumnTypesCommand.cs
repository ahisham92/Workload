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
            if (uidoc == null || uidoc.Document == null)
            {
                message = "Open a project first.";
                return Result.Failed;
            }

            string problem;
            if (ColumnSectionsJob.Report(uidoc, out problem)) return Result.Succeeded;
            message = problem;
            return Result.Failed;
        }
    }
}
