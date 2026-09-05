using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    /// <summary>
    /// Sorts the columns into types — by size, by the foundation under them, by
    /// whether a beam frames in, by where they sit against ground level and by what
    /// the stack does above and below — then cuts one cross section per type and
    /// notes in it how many columns it stands for.
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

            string problem;
            if (ColumnSectionsJob.CreateSections(uidoc, out problem)) return Result.Succeeded;
            message = problem;
            return Result.Failed;
        }
    }
}
