using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using Microsoft.Win32;

namespace Amped2Installer
{
    /// <summary>One build tool as the location page lists it.</summary>
    sealed class ToolStatus
    {
        public string Name;          // "Python", ...
        public string Purpose;       // what the player is told it is for
        public bool Found;
        public string FoundAs;       // e.g. "Python 3.13"
        public bool CanInstall;      // winget can fetch it
        public string InstallNote;   // e.g. "about 3 GB download, asks for administrator rights"
        public string ManualUrl;     // where to get it by hand
        public bool Optional;        // the menu improvements' Java
    }

    /// <summary>
    /// Finds the tools the build needs (Python 3.10+, the Visual Studio C++
    /// build tools with a Windows SDK, CMake, and Java for the menu mod) and
    /// installs missing ones with winget.
    /// </summary>
    sealed class Toolchain
    {
        public string PythonExe, PythonVersion;
        public string VsPath, VsName;
        public int VsMajor;
        public bool WindowsSdk;
        public string CMakeExe, CMakeGenerator;
        public string JavaExe;
        public string WingetExe;

        public bool BuildReady => PythonExe != null && VsPath != null && WindowsSdk && CMakeExe != null;

        // ── Detection ────────────────────────────────────────────────

        public static Toolchain Detect(bool wantJava)
        {
            RefreshPath();
            var t = new Toolchain();
            t.FindPython();
            t.FindVisualStudio();
            t.FindCMake();
            if (wantJava)
                t.FindJava();
            t.FindWinget();
            return t;
        }

        public List<ToolStatus> Describe(bool wantJava)
        {
            bool winget = WingetExe != null;
            var list = new List<ToolStatus>
            {
                new ToolStatus
                {
                    Name = "Visual Studio C++ Build Tools",
                    Purpose = "Microsoft's free compiler, turns the translated code into the game",
                    Found = VsPath != null && WindowsSdk,
                    FoundAs = VsName,
                    CanInstall = winget,
                    InstallNote = "about 3 GB download, needs about 7 GB on drive C: and asks for administrator rights",
                    ManualUrl = "https://visualstudio.microsoft.com/visual-cpp-build-tools/",
                },
                new ToolStatus
                {
                    Name = "Python",
                    Purpose = "runs the recompiler that translates the game's code",
                    Found = PythonExe != null,
                    FoundAs = PythonVersion != null ? "version " + PythonVersion : null,
                    CanInstall = winget,
                    InstallNote = "about 30 MB download",
                    ManualUrl = "https://www.python.org/downloads/windows/",
                },
            };
            // CMake comes with the build tools; list it only when they are
            // there without it.
            if (VsPath != null && CMakeExe == null)
                list.Add(new ToolStatus
                {
                    Name = "CMake",
                    Purpose = "organises the build",
                    Found = false,
                    CanInstall = winget,
                    InstallNote = "about 40 MB download",
                    ManualUrl = "https://cmake.org/download/",
                });
            if (wantJava)
                list.Add(new ToolStatus
                {
                    Name = "Java",
                    Purpose = "needed only for the menu improvements",
                    Found = JavaExe != null,
                    FoundAs = JavaExe != null ? "Java" : null,
                    CanInstall = winget,
                    InstallNote = "about 180 MB download",
                    ManualUrl = "https://learn.microsoft.com/java/openjdk/download",
                    Optional = true,
                });
            return list;
        }

        void FindPython()
        {
            var candidates = new List<string>();

            // Registered installs (PEP 514), which a fresh install has even
            // before this process sees the new PATH.
            foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
                foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
                {
                    try
                    {
                        using (var root = RegistryKey.OpenBaseKey(hive, view))
                        using (var core = root.OpenSubKey(@"SOFTWARE\Python\PythonCore"))
                        {
                            if (core == null) continue;
                            foreach (var tag in core.GetSubKeyNames())
                                using (var ip = core.OpenSubKey(tag + @"\InstallPath"))
                                {
                                    var exe = ip?.GetValue("ExecutablePath") as string;
                                    var dir = ip?.GetValue(null) as string;
                                    if (exe == null && dir != null) exe = Path.Combine(dir, "python.exe");
                                    if (exe != null) candidates.Add(exe);
                                }
                        }
                    }
                    catch (Exception) { }
                }

            // The py launcher's list ("-V:3.13 *  C:\...\python.exe" or " -3.14-64  C:\...").
            var py = Which("py.exe");
            if (py != null)
            {
                var list = ProcessRunner.Capture(py, "-0p", out _, 15000) ?? "";
                foreach (Match m in Regex.Matches(list, @"(?m)^\s*-\S+\s+(?:\*\s+)?(\S.*?\.exe)\s*$"))
                    candidates.Add(m.Groups[1].Value);
            }
            var onPath = Which("python.exe");
            if (onPath != null && onPath.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) < 0)
                candidates.Add(onPath);

            Version best = null;
            foreach (var exe in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (!File.Exists(exe)) continue;
                // 64-bit, 3.10 or newer, with venv (the embeddable zips have none).
                var output = ProcessRunner.Capture(exe,
                    "-c \"import sys, struct, venv; print('%d.%d' % sys.version_info[:2], struct.calcsize('P') * 8)\"",
                    out int code, 20000);
                if (output == null || code != 0) continue;
                var m = Regex.Match(output, @"(\d+)\.(\d+) 64");
                if (!m.Success) continue;
                var v = new Version(int.Parse(m.Groups[1].Value), int.Parse(m.Groups[2].Value));
                if (v < new Version(3, 10)) continue;
                if (best == null || v > best)
                {
                    best = v;
                    PythonExe = exe;
                    PythonVersion = v.ToString(2);
                }
            }
        }

        void FindVisualStudio()
        {
            var vswhere = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                                       @"Microsoft Visual Studio\Installer\vswhere.exe");
            if (File.Exists(vswhere))
            {
                var text = ProcessRunner.Capture(vswhere,
                    "-products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -sort -utf8 -format text",
                    out int code, 30000);
                if (text != null && code == 0)
                {
                    // "-sort" puts the newest first; take the first complete one.
                    foreach (var block in Regex.Split(text, @"(?m)^(?=instanceId: )"))
                    {
                        string Prop(string name) =>
                            Regex.Match(block, "(?m)^" + name + @": (.*?)\s*$") is var m && m.Success ? m.Groups[1].Value : null;
                        var path = Prop("installationPath");
                        var ver = Prop("installationVersion");
                        if (path == null || ver == null || Prop("isComplete") == "0" || !Directory.Exists(path))
                            continue;
                        VsPath = path;
                        VsName = Prop("displayName") ?? "Visual Studio";
                        int.TryParse(ver.Split('.')[0], out VsMajor);
                        break;
                    }
                }
            }

            foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
            {
                try
                {
                    using (var root = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, view))
                    using (var k = root.OpenSubKey(@"SOFTWARE\Microsoft\Windows Kits\Installed Roots"))
                    {
                        var kits = k?.GetValue("KitsRoot10") as string;
                        if (kits != null && Directory.Exists(Path.Combine(kits, "Include")) &&
                            Directory.GetDirectories(Path.Combine(kits, "Include"))
                                     .Any(d => File.Exists(Path.Combine(d, @"um\windows.h"))))
                            WindowsSdk = true;
                    }
                }
                catch (Exception) { }
            }
        }

        void FindCMake()
        {
            var candidates = new List<string>();
            if (VsPath != null)
                candidates.Add(Path.Combine(VsPath, @"Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"));
            var onPath = Which("cmake.exe");
            if (onPath != null) candidates.Add(onPath);
            candidates.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"CMake\bin\cmake.exe"));

            foreach (var exe in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (!File.Exists(exe)) continue;
                var help = ProcessRunner.Capture(exe, "--help", out int code, 20000);
                if (help == null || code != 0) continue;
                // It has to know this Visual Studio ("Visual Studio 17 2022").
                if (VsPath != null)
                {
                    var m = Regex.Match(help, @"Visual Studio " + VsMajor + @" \d{4}");
                    if (!m.Success) continue;
                    CMakeGenerator = m.Value;
                }
                CMakeExe = exe;
                return;
            }
        }

        void FindJava()
        {
            var candidates = new List<string>();
            var onPath = Which("java.exe");
            if (onPath != null) candidates.Add(onPath);
            var home = Environment.GetEnvironmentVariable("JAVA_HOME");
            if (!string.IsNullOrEmpty(home)) candidates.Add(Path.Combine(home, @"bin\java.exe"));
            foreach (var pf in new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                                       Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) })
                foreach (var vendor in new[] { "Microsoft", "Java", "Eclipse Adoptium", "Zulu", "Amazon Corretto", "BellSoft" })
                {
                    var dir = Path.Combine(pf, vendor);
                    if (!Directory.Exists(dir)) continue;
                    try
                    {
                        foreach (var jdk in Directory.GetDirectories(dir).OrderByDescending(d => d))
                            candidates.Add(Path.Combine(jdk, @"bin\java.exe"));
                    }
                    catch (Exception) { }
                }

            foreach (var exe in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (!File.Exists(exe)) continue;
                ProcessRunner.Capture(exe, "-version", out int code, 20000);
                if (code == 0) { JavaExe = exe; return; }
            }
        }

        void FindWinget()
        {
            var exe = Which("winget.exe")
                      ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                      @"Microsoft\WindowsApps\winget.exe");
            if (!File.Exists(exe)) return;
            ProcessRunner.Capture(exe, "--version", out int code, 30000);
            if (code == 0) WingetExe = exe;
        }

        // ── Installation ─────────────────────────────────────────────

        /// <summary>
        /// Installs what is missing with winget and returns a fresh detection.
        /// Throws when a required tool is still missing; a missing Java is
        /// left for the caller, which skips the menu improvements.
        /// </summary>
        public static Toolchain InstallMissing(Toolchain t, bool wantJava, Action<string> status, Action<string> log,
                                               CancellationToken ct)
        {
            if (t.BuildReady && (!wantJava || t.JavaExe != null))
                return t;
            if (t.WingetExe == null)
                throw new UserFacingException(
                    "Some of the free tools needed to build the game aren't installed, and Windows can't install them automatically on this PC.",
                    "Install them by hand (links on the previous page), then run this installer again.");

            if (t.VsPath == null || !t.WindowsSdk)
            {
                status("Installing Microsoft's C++ build tools (this can take 10-20 minutes; a Visual Studio window shows the progress)");
                Winget(t, "Microsoft.VisualStudio.2022.BuildTools",
                       "--override \"--wait --passive --norestart" +
                       " --add Microsoft.VisualStudio.Workload.VCTools" +
                       " --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64" +
                       " --add Microsoft.VisualStudio.Component.VC.CMake.Project" +
                       " --includeRecommended\"", log, ct);
            }
            if (t.PythonExe == null)
            {
                status("Installing Python");
                Winget(t, "Python.Python.3.13", "--scope user", log, ct);
            }

            var again = Detect(wantJava);
            if (again.VsPath != null && again.CMakeExe == null)
            {
                status("Installing CMake");
                Winget(again, "Kitware.CMake", "", log, ct);
                again = Detect(wantJava);
            }
            if (wantJava && again.JavaExe == null)
            {
                status("Installing Java (for the menu improvements)");
                try
                {
                    Winget(again, "Microsoft.OpenJDK.21", "", log, ct);
                }
                catch (OperationCanceledException) { throw; }
                catch (Exception e) { log("Java install failed: " + e.Message); }
                again = Detect(wantJava);
            }

            if (again.VsPath == null || !again.WindowsSdk)
                throw new UserFacingException(
                    "Microsoft's C++ build tools couldn't be installed.",
                    "If Windows asked for administrator rights, allow it next time. You can also install " +
                    "\"Build Tools for Visual Studio\" with the \"Desktop development with C++\" option by hand, then run this installer again.");
            if (again.PythonExe == null)
                throw new UserFacingException("Python couldn't be installed.",
                    "Install Python 3.10 or newer (64-bit) from python.org, then run this installer again.");
            if (again.CMakeExe == null)
                throw new UserFacingException("CMake couldn't be installed.",
                    "Install CMake from cmake.org, then run this installer again.");
            return again;
        }

        static void Winget(Toolchain t, string id, string extra, Action<string> log, CancellationToken ct)
        {
            var args = $"install --id {id} --exact --source winget --silent " +
                       "--accept-package-agreements --accept-source-agreements " + extra;
            log("> winget " + args);
            int code = ProcessRunner.Run(t.WingetExe, args, null, line =>
            {
                // winget draws progress bars with carriage returns and block characters.
                var clean = Regex.Replace(line, @"[\u2580-\u259F\-\\|/]{3,}|\s{2,}", " ").Trim();
                if (clean.Length > 0) log(clean);
            }, ct);
            log($"winget exited with {code}");
            RefreshPath();
        }

        // ── Helpers ──────────────────────────────────────────────────

        /// <summary>Picks up PATH changes installers made since this process started.</summary>
        public static void RefreshPath()
        {
            var parts = new List<string>();
            foreach (var target in new[] { EnvironmentVariableTarget.Machine, EnvironmentVariableTarget.User,
                                           EnvironmentVariableTarget.Process })
            {
                var p = Environment.GetEnvironmentVariable("PATH", target);
                if (p != null) parts.AddRange(p.Split(';'));
            }
            Environment.SetEnvironmentVariable("PATH",
                string.Join(";", parts.Select(p => Environment.ExpandEnvironmentVariables(p.Trim()))
                                      .Where(p => p.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase)));
        }

        public static string Which(string exe)
        {
            foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    if (dir.Length == 0) continue;
                    var p = Path.Combine(dir.Trim('"'), exe);
                    if (File.Exists(p)) return p;
                }
                catch (ArgumentException) { }
            }
            return null;
        }
    }
}
