using System;
using System.Threading;
using System.Windows.Forms;

namespace Amped2Installer
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += (s, e) => Fail(e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) => Fail(e.ExceptionObject as Exception);

            using (var single = new Mutex(true, @"Local\Amped2Installer", out bool first))
            {
                if (!first)
                {
                    MessageBox.Show("The RE-Amped2 installer is already running.", "RE-Amped2 Installer",
                                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }
                if (!Payload.Available)
                {
                    MessageBox.Show("This installer is incomplete: its built-in files are missing. Please download it again.",
                                    "RE-Amped2 Installer", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                try
                {
                    // An image dropped on the .exe (or passed on the command line) is preselected.
                    var form = new WizardForm();
                    if (args.Length == 1 && System.IO.File.Exists(args[0]))
                        form.Shown += (s, e) => form.Preselect(args[0]);
                    Application.Run(form);
                }
                finally
                {
                    Payload.CleanScratch();
                }
            }
        }

        static void Fail(Exception e)
        {
            MessageBox.Show("Something unexpected went wrong in the installer:\n\n" + e?.Message,
                            "RE-Amped2 Installer", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
