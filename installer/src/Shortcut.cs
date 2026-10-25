using System;
using System.Diagnostics;

namespace Amped2Installer
{
    static class Links
    {
        // The public repository. If it is renamed, update these (GitHub
        // redirects the old name, but only for a rename it knows about).
        public const string Repository = "https://github.com/Nico-D-eu/RE-Amped2";
        public const string Issues = Repository + "/issues";
        public const string Releases = Repository + "/releases";

        public static void Open(string target)
        {
            try { Process.Start(new ProcessStartInfo(target) { UseShellExecute = true }); }
            catch (Exception) { }
        }
    }

    static class Shortcut
    {
        /// <summary>A .lnk through the shell's own scripting object.</summary>
        public static void Create(string lnkPath, string target, string workDir, string icon, string description)
        {
            var type = Type.GetTypeFromProgID("WScript.Shell")
                       ?? throw new InvalidOperationException("WScript.Shell is not available");
            dynamic shell = Activator.CreateInstance(type);
            try
            {
                dynamic link = shell.CreateShortcut(lnkPath);
                link.TargetPath = target;
                link.WorkingDirectory = workDir;
                link.IconLocation = icon + ",0";
                link.Description = description;
                link.Save();
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            }
        }
    }
}
