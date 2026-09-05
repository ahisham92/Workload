using System;
using System.Reflection;
using Autodesk.Revit.UI;

namespace ColumnSections
{
    /// <summary>Puts the two commands on a ribbon panel of their own.</summary>
    public class App : IExternalApplication
    {
        private const string TabName = "Structure Tools";
        private const string PanelName = "Column Sections";

        public Result OnStartup(UIControlledApplication application)
        {
            try { application.CreateRibbonTab(TabName); }
            catch (Exception) { /* another add-in made it already */ }

            RibbonPanel panel = application.CreateRibbonPanel(TabName, PanelName);
            string assembly = Assembly.GetExecutingAssembly().Location;

            panel.AddItem(new PushButtonData(
                "ColumnSectionsCreate", "Column\nSections",
                assembly, typeof(CreateColumnSectionsCommand).FullName)
            {
                ToolTip = "One cross section per column type",
                LongDescription =
                    "Groups the columns by size, by the foundation under them, by whether a beam " +
                    "frames into them and by how they sit against ground level, then creates one " +
                    "cross section per group with a note saying how many columns share it."
            });

            panel.AddItem(new PushButtonData(
                "ColumnSectionsReport", "Type\nReport",
                assembly, typeof(ReportColumnTypesCommand).FullName)
            {
                ToolTip = "Count the types without drawing anything",
                LongDescription =
                    "Does the same grouping and reports it, writing a CSV, without changing the model."
            });

            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            return Result.Succeeded;
        }
    }
}
