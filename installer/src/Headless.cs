using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;

namespace Amped2Installer
{
    /// <summary>
    /// The installer without its window, for launchers:
    ///
    ///   RE-Amped2-Setup.exe --prepare --game &lt;disc image&gt; --dir &lt;folder&gt;
    ///                       [--menus] [--look] [--accept-tools]
    ///
    /// It runs the same InstallJob the wizard runs, into the given folder
    /// (usually the folder this .exe was unpacked to). RecompLauncher runs it
    /// as the "prepare" step of installer\recomplauncher.json, on its setup
    /// screen. Its stdout carries only progress lines, as RecompLauncher reads
    /// them: "progress 0.42 Compiling the game". Messages go to stderr; the
    /// full log is install.log in the folder.
    ///
    /// Build tools (MSVC Build Tools, Python, Java for the menus) are
    /// installed only with --accept-tools, which the launcher passes when the
    /// player ticks the box naming them and their licences. Without it, a
    /// missing tool ends the step with ExitTools and says which.
    /// </summary>
    static class Headless
    {
        public const int ExitOk = 0;
        public const int ExitUsage = 1;       // bad arguments, or the wizard is open
        public const int ExitDisc = 2;        // not the retail Amped 2 (USA or Europe)
        public const int ExitTools = 3;       // build tools missing and not allowed, or not installable
        public const int ExitBuild = 4;       // the build failed (install.log has why)
        public const int ExitCancelled = 5;
        public const int ExitFolder = 6;      // a folder the game can't live in

        public static bool Wanted(string[] args) =>
            args.Any(a => string.Equals(a, "--prepare", StringComparison.OrdinalIgnoreCase));

        [DllImport("kernel32.dll")]
        static extern bool AttachConsole(int pid);

        static TextWriter _out = Console.Out, _err = Console.Error;

        static void Progress(double f, string text)
        {
            f = Math.Max(0, Math.Min(1, f));
            _out.WriteLine("progress " + f.ToString("0.000", CultureInfo.InvariantCulture) + " " + text);
            _out.Flush();
        }

        static void Say(string text)
        {
            _err.WriteLine(text);
            _err.Flush();
        }

        public static int Run(string[] args)
        {
            // A GUI .exe has no console. Started from a command prompt, print
            // there; started by a launcher, stdout is already its pipe.
            if (Console.IsOutputRedirected == false && AttachConsole(-1))
            {
                _out = new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true };
                _err = new StreamWriter(Console.OpenStandardError()) { AutoFlush = true };
            }

            string game = null, dir = null;
            bool menus = false, look = false, acceptTools = false;
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant();
                if (a == "--prepare") continue;
                else if (a == "--game" && i + 1 < args.Length) game = args[++i];
                else if (a == "--dir" && i + 1 < args.Length) dir = args[++i];
                else if (a == "--menus") menus = true;
                else if (a == "--look") look = true;
                else if (a == "--accept-tools") acceptTools = true;
                else
                {
                    Say("Unknown argument: " + args[i]);
                    return Usage();
                }
            }
            if (game == null || dir == null)
                return Usage();

            string why = CheckFolder(ref dir);
            if (why != null)
            {
                Say(why);
                return ExitFolder;
            }
            if (!Payload.Available)
            {
                Say("This installer is incomplete: its built-in files are missing. Download it again.");
                return ExitUsage;
            }

            using (var single = new Mutex(true, @"Local\Amped2Installer", out bool first))
            {
                if (!first)
                {
                    Say("The RE-Amped2 installer is already running. Close it and try again.");
                    return ExitUsage;
                }
                try
                {
                    return Install(game, dir, menus, look, acceptTools);
                }
                finally
                {
                    Payload.CleanScratch();
                }
            }
        }

        static int Usage()
        {
            Say("Usage: RE-Amped2-Setup.exe --prepare --game <disc image> --dir <folder> [--menus] [--look] [--accept-tools]");
            return ExitUsage;
        }

        /// <summary>The wizard's folder rules: a full path, not a drive's top, not Program Files or Windows.</summary>
        static string CheckFolder(ref string dir)
        {
            try
            {
                if (!Path.IsPathRooted(dir)) throw new ArgumentException();
                dir = Path.GetFullPath(dir).TrimEnd('\\');
            }
            catch (Exception)
            {
                return "The folder must be a full path, such as C:\\Games\\RE-Amped2.";
            }
            if (dir.Length <= 3)
                return "Choose a folder, not the top of a drive.";
            foreach (var special in new[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86,
                                            Environment.SpecialFolder.Windows })
            {
                var sp = Environment.GetFolderPath(special);
                if (sp.Length > 0 && dir.StartsWith(sp, StringComparison.OrdinalIgnoreCase))
                    return "The game keeps its saves and settings in its own folder, which Windows doesn't allow inside " + sp + ".";
            }
            return null;
        }

        static int Install(string game, string dir, bool menus, bool look, bool acceptTools)
        {
            Progress(0, "Checking the disc image");
            DiscInfo disc;
            try
            {
                disc = DiscImage.Inspect(game);
            }
            catch (UserFacingException e)
            {
                Say(e.Message + (string.IsNullOrEmpty(e.Advice) ? "" : " " + e.Advice));
                return ExitDisc;
            }
            catch (Exception e)
            {
                Say("The disc image couldn't be read: " + e.Message);
                return ExitDisc;
            }

            // The same consent as the wizard's dialog, given up front by the
            // launcher's licence tick.
            Progress(0.005, "Looking for the build tools");
            var tools = Toolchain.Detect(menus);
            var missing = tools.Describe(menus).Where(t => !t.Found).ToList();
            var manual = missing.Where(t => !t.CanInstall && t.Name != Toolchain.JavaTool).ToList();
            if (manual.Count > 0)
            {
                foreach (var t in manual)
                    Say($"{t.Name} is missing and can't be installed automatically on this PC: install it from {t.ManualUrl}, then set up again.");
                return ExitTools;
            }
            var installable = missing.Where(t => t.CanInstall).ToList();
            if (installable.Count > 0 && !acceptTools)
            {
                Say("These build tools are missing: " + string.Join(", ", installable.Select(t => t.Name)) +
                    ". Allow installing them (the build tools tick, --accept-tools) and set up again.");
                return ExitTools;
            }

            var o = new InstallOptions
            {
                Disc = disc,
                InstallDir = dir,
                DesktopShortcut = false,       // the launcher is where it's started from
                MenuMod = menus,
                Look = look,
                HdMovies = false,              // a few hours: not a setup step
                Android = false,
                ApprovedTools = new HashSet<string>(installable.Select(t => t.Name)),
            };
            var job = new InstallJob(o);
            Console.CancelKeyPress += (s, e) => { e.Cancel = true; job.Cancel(); };

            var worker = new Thread(job.Run) { IsBackground = true, Name = "install" };
            worker.Start();
            string last = null;
            double shown = 0.01;   // past the checks above: the bar never goes back
            while (!worker.Join(500))
            {
                int stage = job.Stage;
                string title = stage >= 0 && stage < InstallJob.StageTitles.Length ? InstallJob.StageTitles[stage] : "Starting";
                string detail = job.Detail;
                string text = string.IsNullOrEmpty(detail) || detail == title ? title : title + ": " + detail;
                shown = Math.Max(shown, job.Percent / 100.0);
                string line = ((int)(shown * 1000)).ToString(CultureInfo.InvariantCulture) + text;
                if (line != last)
                {
                    Progress(shown, text);
                    last = line;
                }
            }

            var r = job.Result;
            if (r == null)
            {
                Say("The install stopped without a result; see install.log.");
                return ExitBuild;
            }
            if (r.Cancelled)
                return ExitCancelled;
            if (!r.Success)
            {
                Say((r.FailedStage != null ? r.FailedStage + ": " : "") + r.Error +
                    (string.IsNullOrEmpty(r.Advice) ? "" : " " + r.Advice));
                return r.FailedStage == InstallJob.StageTitles[0] ? ExitTools : ExitBuild;
            }
            foreach (var note in new[] { r.MenuModNote }.Concat(r.Warnings).Where(n => !string.IsNullOrEmpty(n)))
                Say(note);
            Progress(1, "Ready to play");
            return ExitOk;
        }
    }
}
